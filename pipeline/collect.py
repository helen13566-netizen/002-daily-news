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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import feedparser
import pytz
import requests
from bs4 import BeautifulSoup

from pipeline.config import (
    AI_KEYWORDS,
    CANDIDATES_JSON_PATH,
    EVENING_CUTOFF_HOUR,
    EVENING_CUTOFF_MINUTE,
    KST_TZ_NAME,
    MAX_RETRY,
    MORNING_CUTOFF_HOUR,
    MORNING_CUTOFF_MINUTE,
    RSS_FEEDS,
    RSSFeed,
)

logger = logging.getLogger(__name__)

# 한국 뉴스 사이트 다수가 비브라우저 UA를 차단(403·Cloudflare·지역 차단 페이지 응답)하므로 Chrome UA로 위장.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

PER_FEED_TIMEOUT_SECONDS: float = 15.0
MAX_CONTENT_CHARS: int = 2000
KST = pytz.timezone(KST_TZ_NAME)


class FeedFetchError(Exception):
    """피드 수집 실패 — HTTP 비정상 응답 또는 비-XML 컨텐츠."""


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
    parse_failed: int = 0
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


def window_for(
    now_kst: datetime,
    *,
    window_hours: int | None = None,
) -> tuple[datetime, datetime]:
    """수집 시각(KST) 을 받아 브리핑 시간 윈도우 ``(start, end)`` 를 반환.

    - ``window_hours=None`` (기본): 오전 수집 → 전날 17:25 ~ 당일 08:25 KST,
      오후 수집 → 당일 08:25 ~ 당일 17:25 KST 로 고정 윈도우.
    - ``window_hours=N`` (정수, v20 추가): ``(now - N시간, now)`` rolling 윈도우.
      공식 AI 소스처럼 발행 주기가 낮은 피드에 72 를 주면 지난 72 시간 안의
      글을 전부 포함.
    """
    if now_kst.tzinfo is None:
        now_kst = KST.localize(now_kst)
    else:
        now_kst = now_kst.astimezone(KST)

    if window_hours is not None:
        return now_kst - timedelta(hours=window_hours), now_kst

    if now_kst.hour < 12:
        prev_day = now_kst - timedelta(days=1)
        start = prev_day.replace(
            hour=EVENING_CUTOFF_HOUR,
            minute=EVENING_CUTOFF_MINUTE,
            second=0,
            microsecond=0,
        )
        end = now_kst.replace(
            hour=MORNING_CUTOFF_HOUR,
            minute=MORNING_CUTOFF_MINUTE,
            second=0,
            microsecond=0,
        )
    else:
        start = now_kst.replace(
            hour=MORNING_CUTOFF_HOUR,
            minute=MORNING_CUTOFF_MINUTE,
            second=0,
            microsecond=0,
        )
        end = now_kst.replace(
            hour=EVENING_CUTOFF_HOUR,
            minute=EVENING_CUTOFF_MINUTE,
            second=0,
            microsecond=0,
        )
    return start, end


def window_start_for(now_kst: datetime) -> datetime:
    """(legacy alias) 윈도우 시작 시점만 반환."""
    start, _end = window_for(now_kst)
    return start


def parse_published(
    entry: Any,
    fallback_utc_now: datetime,
    *,
    default_tz: Any = None,
) -> datetime | None:
    """RSS entry 에서 published 시각을 KST-aware datetime 으로 추출.

    우선순위 (v19 에서 뒤집음 — 이전에는 struct_time 이 우선이었지만 feedparser 가
    tz 없는 pubDate 를 UTC 로 강제 해석하는 동작 때문에 한국 RSS 에서 +9h 미래
    시프트 버그가 있었음):

    1. ``entry.published`` / ``entry.updated`` / ``entry.pubDate`` **raw 문자열** 을
       ``dateutil`` 로 파싱. tz 정보가 있으면 그대로 존중, 없으면 ``default_tz``
       (피드가 명시한 기본 시간대 — 한국 소스 = KST) 로 localize.
    2. raw 가 없거나 실패 → ``published_parsed`` / ``updated_parsed`` (feedparser
       struct_time) 를 UTC 로 간주해 변환 (마지막 fallback).
    3. 모두 실패 → **None 반환** (sentinel — 호출측에서 enrich 시도).

    Args:
        default_tz: pytz timezone 또는 None. None 이면 KST 로 간주.
    """
    if default_tz is None:
        default_tz = KST

    raw = entry.get("published") or entry.get("updated") or entry.get("pubDate")
    if raw:
        try:
            from dateutil import parser as dtparser

            dt = dtparser.parse(raw)
            if dt.tzinfo is None:
                dt = default_tz.localize(dt)
            return dt.astimezone(KST)
        except Exception:
            logger.debug("published 문자열 파싱 실패: %r", raw)

    struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if struct is not None:
        try:
            dt_utc = datetime(*struct[:6], tzinfo=timezone.utc)
            return dt_utc.astimezone(KST)
        except Exception:
            logger.debug("published_parsed 변환 실패")

    _ = fallback_utc_now  # kept for signature stability
    return None


def _fetch_article_meta(url: str, timeout: float = 5.0) -> dict[str, str]:
    """기사 페이지에서 og:description + article:published_time 을 추출.

    한겨레처럼 RSS item 에 본문·시각 정보가 부족한 소스를 보강하기 위한 경량 fetch.
    실패 시 빈 dict 반환 (caller 에서 drop 결정).

    반환 키:
    - ``description``: og:description 콘텐츠 (있으면)
    - ``published_time``: article:published_time 또는 대체 태그 (있으면)
    """
    try:
        resp = requests.get(url, headers=_BROWSER_HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return {}
        soup = BeautifulSoup(resp.content, "lxml")
    except Exception as exc:  # noqa: BLE001
        logger.debug("article meta fetch 실패 %s: %s", url, exc)
        return {}

    result: dict[str, str] = {}
    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        result["description"] = og_desc["content"].strip()

    # published_time 은 여러 표준이 섞여있어 순차 시도.
    for finder in (
        lambda: soup.find("meta", property="article:published_time"),
        lambda: soup.find("meta", attrs={"name": "article:published_time"}),
        lambda: soup.find("meta", attrs={"name": "h:published_time"}),
        lambda: soup.find("meta", property="og:article:published_time"),
    ):
        tag = finder()
        if tag and tag.get("content"):
            result["published_time"] = tag["content"].strip()
            break

    return result


def match_ai_keywords(title: str, content: str) -> list[str]:
    """AI_KEYWORDS 중 title+content 본문과 매치되는 것들을 반환.

    - ASCII 키워드(영문·숫자)는 word boundary 매칭, 대소문자 무시.
      (AI 가 AIDS/airplane, GPT 가 GPTs 같은 변형에 false positive 되지 않도록.)
    - 한글/공백 포함 키워드는 literal substring 매칭.
    """
    hay = f"{title}\n{content}"
    matched: list[str] = []
    for kw in AI_KEYWORDS:
        if kw.isascii():
            pattern = rf"\b{re.escape(kw)}\b"
            if re.search(pattern, hay, re.IGNORECASE):
                matched.append(kw)
        else:
            if kw in hay:
                matched.append(kw)
    return matched


# ---------------------------------------------------------------------------
# 피드 fetch + 파싱 + 재시도
# ---------------------------------------------------------------------------


_BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "application/rss+xml, application/atom+xml, application/xml;q=0.9, "
        "text/xml;q=0.9, text/html;q=0.8, */*;q=0.5"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    # brotli('br') 은 일부 서버(OpenAI, Simon Willison 등) 가 사용하지만 Python
    # requests 기본 설치에는 디코더가 없어 content 가 압축된 상태로 feedparser
    # 에 전달돼 파싱이 깨진다. gzip/deflate 만 요청.
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def _fetch_feed_once(feed: RSSFeed) -> Any:
    """피드 1회 fetch + 파싱.

    feedparser.parse(URL) 직호출은 SAX 에러 원인을 숨긴다. 여기서는:
      1. requests 로 받아 HTTP 상태/Content-Type/선두 바이트를 진단 로깅
      2. 비정상 응답(4xx/5xx 또는 비XML)은 FeedFetchError 로 즉시 예외화
      3. 200 + XML 본문만 feedparser 에 문자열로 전달
    """
    try:
        resp = requests.get(
            feed.url,
            headers=_BROWSER_HEADERS,
            timeout=PER_FEED_TIMEOUT_SECONDS,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        raise FeedFetchError(
            f"{feed.name} network error: {type(exc).__name__}: {exc}"
        ) from exc

    status = resp.status_code
    ctype = resp.headers.get("Content-Type", "")
    body = resp.content  # bytes — feedparser 가 인코딩 판별
    preview = body[:200].decode("utf-8", errors="replace")

    if status != 200:
        raise FeedFetchError(
            f"{feed.name} HTTP {status} ctype={ctype!r} "
            f"preview={preview!r}"
        )

    # 일부 서버가 text/html 로 XML 을 돌려주는 경우가 있어 Content-Type 만으로 거르지 않는다.
    # 단, 본문이 HTML 문서(<html/<!doctype html)로 시작하면 차단/에러 페이지로 간주.
    lowered = preview.lstrip().lower()
    if lowered.startswith(("<!doctype html", "<html")):
        raise FeedFetchError(
            f"{feed.name} HTML response (likely blocked) ctype={ctype!r} "
            f"preview={preview!r}"
        )

    logger.info(
        "[%s] HTTP %d %s bytes=%d", feed.name, status, ctype, len(body)
    )
    return feedparser.parse(body)


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


def process_feed(
    feed: RSSFeed, *, now_kst: datetime | None = None
) -> FeedResult:
    """피드 1개 파싱 + 시간 윈도우 필터.

    ``now_kst`` 를 주면 그 시각 기준으로 오전/오후 윈도우를 결정한다.
    None 이면 호출 시점의 KST 현재 시각을 사용.
    """
    result = FeedResult(feed=feed)
    parsed, err = fetch_feed_with_retry(feed)
    if parsed is None:
        result.error = err
        logger.error("[%s] %d 회 재시도 후 실패: %s", feed.name, MAX_RETRY, err)
        return result

    entries: Iterable[Any] = getattr(parsed, "entries", []) or []
    now_utc = datetime.now(timezone.utc)
    if now_kst is None:
        now_kst = now_utc.astimezone(KST)
    # feed 별 window_hours (None = 기본 오전/오후 고정, 정수 = rolling)
    feed_window_hours = getattr(feed, "window_hours", None)
    window_start, _window_end = window_for(
        now_kst, window_hours=feed_window_hours
    )

    try:
        feed_default_tz = pytz.timezone(feed.default_tz)
    except Exception:
        feed_default_tz = KST

    for entry in entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue

        result.fetched += 1

        # 본문: summary 또는 description
        raw_summary = entry.get("summary") or entry.get("description") or ""
        content_text = truncate(strip_html(raw_summary))

        published_dt = parse_published(entry, now_utc, default_tz=feed_default_tz)

        # RSS item 에 본문/시각 정보가 부족하면 기사 페이지 og:meta 로 enrich 시도.
        # (한겨레 등 시각 태그 없는 RSS 를 위한 fallback.)
        if not content_text or published_dt is None:
            meta = _fetch_article_meta(link)
            if not content_text and meta.get("description"):
                content_text = truncate(meta["description"])
            if published_dt is None and meta.get("published_time"):
                try:
                    from dateutil import parser as dtparser

                    dt = dtparser.parse(meta["published_time"])
                    if dt.tzinfo is None:
                        dt = KST.localize(dt)
                    published_dt = dt.astimezone(KST)
                except Exception:
                    logger.debug(
                        "enrich published_time 파싱 실패: %r",
                        meta.get("published_time"),
                    )

        # enrich 후에도 시각 정보가 없으면 grounded 분석 대상에서 제외.
        if published_dt is None:
            result.parse_failed += 1
            continue

        # 시간 윈도우 밖 기사는 이번 brief 대상이 아니므로 드롭.
        if published_dt < window_start:
            continue

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

        # 분류 규칙 (v20):
        # - 피드의 category 가 "ai_news" 또는 "official_ai" 면 그대로 존중
        #   (공식 AI 소스는 항상 official_ai 로 분류됨).
        # - "general_news" 피드는 키워드 매칭으로 ai_news 로 승격 가능.
        if feed.category in ("ai_news", "official_ai"):
            category = feed.category
        else:
            category = "ai_news" if matched_keywords else "general_news"

        article = Article(
            article_id=article_id,
            title=title,
            source=feed.name,
            published_at=published_iso,
            original_url=link,
            content_text=content_text,
            category=category,
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


def collect(
    output_path: str | Path = CANDIDATES_JSON_PATH,
    *,
    now_kst: datetime | None = None,
) -> dict[str, Any]:
    """모든 피드를 병렬 수집 → 필터/dedup → JSON 기록.

    ``now_kst`` 는 수집 기준 시각. 주어지면 모든 피드에 동일하게 전파되어 윈도우
    경계가 일관되게 적용된다. None 이면 실제 현재 KST 시각 사용.

    Returns a summary dict with collection_timestamp, source_stats, articles.
    """
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if now_kst is None:
        now_kst = datetime.now(KST)
    elif now_kst.tzinfo is None:
        now_kst = KST.localize(now_kst)
    else:
        now_kst = now_kst.astimezone(KST)

    window_start = window_start_for(now_kst)
    logger.info(
        "수집 기준 시각 %s → 윈도우 시작 %s (윈도우 밖 기사는 드롭)",
        now_kst.isoformat(timespec="seconds"),
        window_start.isoformat(timespec="seconds"),
    )

    feed_results: list[FeedResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        future_map = {
            pool.submit(process_feed, f, now_kst=now_kst): f for f in RSS_FEEDS
        }
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
            "parse_failed": fr.parse_failed,
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
        "collection_timestamp": now_kst.isoformat(timespec="seconds"),
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
