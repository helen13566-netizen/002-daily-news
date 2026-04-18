"""RSS 수집 · AI 키워드 필터 · 중복 제거 파이프라인.

6개 RSS 피드를 병렬 수집하여 ``state/candidates.json`` 으로 덤프한다.
- ai_news 분류 피드는 AI 키워드가 하나 이상 매치되어야 통과.
- general_news 분류 피드는 전부 통과.
- ``article_id = SHA-1(feed_url||published||link)[:16]`` 기반 1차 dedup.
- 제목 정규화(소문자·공백·구두점 제거) + 같은 날짜 기준 2차 dedup.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import re
import string
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import feedparser
import pytz
from bs4 import BeautifulSoup

from pipeline.config import (
    AI_KEYWORDS,
    CANDIDATES_JSON_PATH,
    KST_TZ_NAME,
    MAX_RETRY,
    RSS_FEEDS,
    RSSFeed,
)

logger = logging.getLogger(__name__)

USER_AGENT = (
    "DailyNewsBriefing/1.0 "
    "(+https://github.com/helen13566-netizen/002-daily-news)"
)

PER_FEED_TIMEOUT_SECONDS: float = 15.0
MAX_CONTENT_CHARS: int = 2000
KST = pytz.timezone(KST_TZ_NAME)


# ---------------------------------------------------------------------------
# 데이터 클래스
# ---------------------------------------------------------------------------


@dataclass
class Article:
    article_id: str
    title: str
    source: str
    published_at: str
    original_url: str
    content_text: str
    category: str
    keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "article_id": self.article_id,
            "title": self.title,
            "source": self.source,
            "published_at": self.published_at,
            "original_url": self.original_url,
            "content_text": self.content_text,
            "category": self.category,
            "keywords": self.keywords,
        }


@dataclass
class FeedResult:
    feed: RSSFeed
    articles: list[Article] = field(default_factory=list)
    fetched: int = 0
    ai_matched: int = 0
    error: str | None = None


# ---------------------------------------------------------------------------
# 순수 함수 유틸
# ---------------------------------------------------------------------------


def generate_article_id(feed_url: str, published: str, link: str) -> str:
    """feed_url + '||' + published + '||' + link 의 SHA-1 앞 16자."""
    raw = f"{feed_url}||{published}||{link}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


_PUNCT_TABLE = str.maketrans("", "", string.punctuation + "·…·「」『』【】《》〈〉“”‘’—–‐‑·")


def normalize_title(title: str) -> str:
    """소문자 + 공백 정규화 + 구두점 제거.

    한글 구두점과 ASCII 구두점 모두 제거해서 cross-source 매칭이 되도록 한다.
    """
    if not title:
        return ""
    t = unicodedata.normalize("NFKC", title)
    t = t.lower()
    t = t.translate(_PUNCT_TABLE)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def strip_html(raw: str) -> str:
    """HTML/엔티티를 벗겨 순수 텍스트로."""
    if not raw:
        return ""
    try:
        soup = BeautifulSoup(raw, "lxml")
    except Exception:  # lxml 빠지면 html.parser 폴백
        soup = BeautifulSoup(raw, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def truncate(text: str, limit: int = MAX_CONTENT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def parse_published(entry: Any, fallback_utc_now: datetime) -> datetime:
    """RSS entry 에서 published 시각을 KST-aware datetime 으로 추출.

    - ``published_parsed`` 또는 ``updated_parsed`` (time.struct_time, UTC naive) 우선.
    - 둘 다 없으면 dateutil 로 문자열 파싱 시도.
    - 모든 실패 시 ``fallback_utc_now`` 사용.
    - tz 정보 없으면 KST 로 간주.
    """
    struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if struct is not None:
        try:
            # feedparser 는 published_parsed 를 UTC struct_time 으로 보정한다.
            dt_utc = datetime(*struct[:6], tzinfo=timezone.utc)
            return dt_utc.astimezone(KST)
        except Exception:
            logger.debug("published_parsed 변환 실패, 문자열 파싱으로 fallback")

    raw = entry.get("published") or entry.get("updated") or entry.get("pubDate")
    if raw:
        try:
            from dateutil import parser as dtparser

            dt = dtparser.parse(raw)
            if dt.tzinfo is None:
                dt = KST.localize(dt)
            return dt.astimezone(KST)
        except Exception:
            logger.debug("published 문자열 파싱 실패: %r", raw)

    return fallback_utc_now.astimezone(KST)


def match_ai_keywords(title: str, content: str) -> list[str]:
    """AI_KEYWORDS 중 title+content 본문과 매치되는 것들을 반환.

    - 영문 키워드(순수 ASCII)는 case-insensitive.
    - 한글 포함 키워드는 literal 매칭.
    """
    hay = f"{title}\n{content}"
    hay_lower = hay.lower()
    matched: list[str] = []
    for kw in AI_KEYWORDS:
        if kw.isascii():
            if kw.lower() in hay_lower:
                matched.append(kw)
        else:
            if kw in hay:
                matched.append(kw)
    return matched


# ---------------------------------------------------------------------------
# 피드 fetch + 파싱 + 재시도
# ---------------------------------------------------------------------------


def _fetch_feed_once(feed: RSSFeed) -> Any:
    """feedparser.parse 1회 호출. network timeout 은 feedparser 옵션 위임."""
    return feedparser.parse(
        feed.url,
        agent=USER_AGENT,
        request_headers={"User-Agent": USER_AGENT},
    )


def fetch_feed_with_retry(
    feed: RSSFeed,
    *,
    max_retry: int = MAX_RETRY,
    sleep_fn=time.sleep,
    parse_fn=None,
) -> tuple[Any | None, str | None]:
    """feed 를 최대 ``max_retry`` 회 재시도하며 파싱.

    Returns (parsed_feed, error_class_name_or_None).
    네트워크 예외나 parsed.bozo + bozo_exception(urllib 계열) 을 에러로 취급.

    ``parse_fn`` 을 None 으로 두면 호출 시점의 ``_fetch_feed_once`` 를 사용한다
    (monkeypatch 호환을 위해 런타임 lookup).
    """
    last_error: Exception | None = None
    for attempt in range(1, max_retry + 1):
        try:
            fn = parse_fn if parse_fn is not None else _fetch_feed_once
            parsed = fn(feed)
        except Exception as exc:  # noqa: BLE001 - 모든 예외를 재시도 대상으로
            last_error = exc
            logger.warning(
                "[%s] parse 예외 (attempt %d/%d): %s",
                feed.name,
                attempt,
                max_retry,
                exc,
            )
        else:
            # bozo 인데 entries 가 하나도 없으면 네트워크/포맷 문제로 간주.
            if getattr(parsed, "bozo", False) and not getattr(parsed, "entries", None):
                bozo_exc = getattr(parsed, "bozo_exception", None)
                if bozo_exc is not None and not _is_benign_bozo(bozo_exc):
                    last_error = bozo_exc
                    logger.warning(
                        "[%s] bozo 에러 (attempt %d/%d): %s",
                        feed.name,
                        attempt,
                        max_retry,
                        bozo_exc,
                    )
                else:
                    return parsed, None
            else:
                return parsed, None

        if attempt < max_retry:
            sleep_fn(2 ** (attempt - 1))  # 1s, 2s, 4s

    err_name = type(last_error).__name__ if last_error else "UnknownError"
    return None, err_name


def _is_benign_bozo(exc: Exception) -> bool:
    """CharacterEncodingOverride 등 entries 파싱에는 영향 없는 경고."""
    try:
        from feedparser import CharacterEncodingOverride, NonXMLContentType  # type: ignore
    except Exception:  # pragma: no cover
        CharacterEncodingOverride = ()
        NonXMLContentType = ()
    benign = tuple(
        cls for cls in (CharacterEncodingOverride, NonXMLContentType) if cls  # type: ignore[arg-type]
    )
    return bool(benign) and isinstance(exc, benign)


# ---------------------------------------------------------------------------
# 피드 단위 처리
# ---------------------------------------------------------------------------


def process_feed(feed: RSSFeed) -> FeedResult:
    result = FeedResult(feed=feed)
    parsed, err = fetch_feed_with_retry(feed)
    if parsed is None:
        result.error = err
        logger.error("[%s] %d 회 재시도 후 실패: %s", feed.name, MAX_RETRY, err)
        return result

    entries: Iterable[Any] = getattr(parsed, "entries", []) or []
    now_utc = datetime.now(timezone.utc)

    for entry in entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue

        result.fetched += 1

        # 본문: summary 또는 description
        raw_summary = entry.get("summary") or entry.get("description") or ""
        content_text = truncate(strip_html(raw_summary))

        published_dt = parse_published(entry, now_utc)
        published_raw = (
            entry.get("published")
            or entry.get("updated")
            or entry.get("pubDate")
            or published_dt.isoformat()
        )
        published_iso = published_dt.isoformat()
        article_id = generate_article_id(feed.url, published_raw, link)

        matched_keywords = match_ai_keywords(title, content_text)
        if matched_keywords:
            result.ai_matched += 1

        # ai_news 피드는 AI 키워드 매치된 기사만 유지, general_news 는 전부 유지.
        if feed.category == "ai_news" and not matched_keywords:
            continue

        article = Article(
            article_id=article_id,
            title=title,
            source=feed.name,
            published_at=published_iso,
            original_url=link,
            content_text=content_text,
            category=feed.category,
            keywords=matched_keywords,
        )
        result.articles.append(article)

    return result


# ---------------------------------------------------------------------------
# 중복 제거
# ---------------------------------------------------------------------------


def dedupe_articles(articles: list[Article]) -> list[Article]:
    """``article_id`` 또는 (normalized_title + 같은 날짜) 기준 dedup.

    순회 순서(= RSS_FEEDS 순서)를 유지하며 처음 등장한 기사를 남긴다.
    """
    seen_ids: set[str] = set()
    seen_title_day: set[tuple[str, str]] = set()
    kept: list[Article] = []

    for art in articles:
        if art.article_id in seen_ids:
            continue
        norm = normalize_title(art.title)
        day = art.published_at[:10]  # 'YYYY-MM-DD'
        key = (norm, day)
        if norm and key in seen_title_day:
            continue

        seen_ids.add(art.article_id)
        if norm:
            seen_title_day.add(key)
        kept.append(art)

    return kept


# ---------------------------------------------------------------------------
# 오케스트레이션
# ---------------------------------------------------------------------------


def collect(output_path: str | Path = CANDIDATES_JSON_PATH) -> dict[str, Any]:
    """모든 피드를 병렬 수집 → 필터/dedup → JSON 기록.

    Returns a summary dict with collection_timestamp, source_stats, articles.
    """
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    feed_results: list[FeedResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        future_map = {pool.submit(process_feed, f): f for f in RSS_FEEDS}
        for future in concurrent.futures.as_completed(
            future_map, timeout=PER_FEED_TIMEOUT_SECONDS * MAX_RETRY + 10
        ):
            feed = future_map[future]
            try:
                feed_results.append(future.result(timeout=0))
            except Exception as exc:  # noqa: BLE001
                logger.exception("[%s] 미처리 예외", feed.name)
                feed_results.append(
                    FeedResult(feed=feed, error=type(exc).__name__)
                )

    # RSS_FEEDS 순서대로 정렬 (dedup 이 선순위 피드를 유지하기 위함).
    order_index = {f.name: i for i, f in enumerate(RSS_FEEDS)}
    feed_results.sort(key=lambda r: order_index.get(r.feed.name, 999))

    all_articles: list[Article] = []
    source_stats: dict[str, dict[str, Any]] = {}
    for fr in feed_results:
        stat: dict[str, Any] = {
            "fetched": fr.fetched,
            "ai_matched": fr.ai_matched,
            "kept": len(fr.articles),
        }
        if fr.error:
            stat["error"] = fr.error
        source_stats[fr.feed.name] = stat
        all_articles.extend(fr.articles)

    deduped = dedupe_articles(all_articles)

    # dedup 으로 드롭된 기사는 source_stats.kept 에 반영 (교차 dedup 로 줄어들 수 있음).
    kept_per_source: dict[str, int] = {}
    for art in deduped:
        kept_per_source[art.source] = kept_per_source.get(art.source, 0) + 1
    for name, stat in source_stats.items():
        stat["kept"] = kept_per_source.get(name, 0)

    summary = {
        "collection_timestamp": datetime.now(KST).isoformat(timespec="seconds"),
        "source_stats": source_stats,
        "articles": [a.to_dict() for a in deduped],
    }

    out_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(
        "candidates.json 기록: %s (%d articles, %d sources)",
        out_path,
        len(deduped),
        len(source_stats),
    )
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    summary = collect()
    print(
        json.dumps(
            summary["source_stats"],
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    _main()
