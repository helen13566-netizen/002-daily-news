"""pipeline.collect 모듈 단위 테스트.

네트워크를 타지 않기 위해 ``feedparser.parse`` 와 ``time.sleep`` 을
monkeypatch 로 치환한다.
"""

from __future__ import annotations

import json
import time
import types
from pathlib import Path
from typing import Any

import pytest

from pipeline import collect as collect_mod
from pipeline.config import RSSFeed


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_parsed(entries: list[dict[str, Any]], *, bozo: bool = False) -> Any:
    """feedparser.parse() 결과를 흉내내는 가짜 객체."""
    obj = types.SimpleNamespace()
    obj.entries = [types.SimpleNamespace(**e) | _MappingShim(e) for e in entries]
    # feedparser 의 entry 는 dict-like 이기도 하므로 .get() 을 지원해야 한다.
    for entry, src in zip(obj.entries, entries):
        entry.get = src.get  # type: ignore[attr-defined]
    obj.bozo = bozo
    obj.feed = types.SimpleNamespace(title="mock feed")
    return obj


class _MappingShim:
    """SimpleNamespace 에 __or__ 를 지원하기 위한 no-op 보조."""

    def __init__(self, src: dict[str, Any]) -> None:
        self._src = src

    def __ror__(self, other: Any) -> Any:  # type: ignore[override]
        return other  # 그냥 other 그대로 반환


# ---------------------------------------------------------------------------
# 1) article_id 안정성
# ---------------------------------------------------------------------------


def test_generate_article_id_is_stable() -> None:
    a = collect_mod.generate_article_id(
        "https://example.com/rss",
        "Mon, 19 Apr 2026 07:00:00 +0900",
        "https://example.com/news/1",
    )
    b = collect_mod.generate_article_id(
        "https://example.com/rss",
        "Mon, 19 Apr 2026 07:00:00 +0900",
        "https://example.com/news/1",
    )
    c = collect_mod.generate_article_id(
        "https://example.com/rss",
        "Mon, 19 Apr 2026 07:00:00 +0900",
        "https://example.com/news/2",
    )
    assert a == b
    assert a != c
    assert len(a) == 16


# ---------------------------------------------------------------------------
# 2) 제목 정규화 기반 dedup
# ---------------------------------------------------------------------------


def test_normalize_title_dedup() -> None:
    a1 = collect_mod.Article(
        article_id="id1",
        title="GPT-5, 새로운 모델 발표!!",
        source="AI타임스",
        published_at="2026-04-19T07:00:00+09:00",
        original_url="https://a.com/1",
        content_text="",
        category="ai_news",
        keywords=["GPT"],
    )
    a2 = collect_mod.Article(
        article_id="id2",  # id 는 다르지만
        title="gpt-5  새로운 모델 발표",  # 정규화하면 동일
        source="ZDNet Korea",
        published_at="2026-04-19T12:30:00+09:00",  # 같은 날
        original_url="https://b.com/1",
        content_text="",
        category="ai_news",
        keywords=["GPT"],
    )
    a3 = collect_mod.Article(
        article_id="id3",
        title="GPT-5, 새로운 모델 발표",
        source="AI타임스",
        published_at="2026-04-20T07:00:00+09:00",  # 다른 날 → 유지
        original_url="https://a.com/2",
        content_text="",
        category="ai_news",
        keywords=["GPT"],
    )

    deduped = collect_mod.dedupe_articles([a1, a2, a3])
    assert [a.article_id for a in deduped] == ["id1", "id3"]


def test_normalize_title_case_and_punctuation() -> None:
    assert collect_mod.normalize_title("Hello, World!!") == "hello world"
    assert collect_mod.normalize_title("  AI  모델 출시  ") == "ai 모델 출시"


# ---------------------------------------------------------------------------
# 3) AI 피드 키워드 필터
# ---------------------------------------------------------------------------


def test_filter_ai_feeds_requires_keyword(monkeypatch: pytest.MonkeyPatch) -> None:
    ai_feed = RSSFeed("AI타임스", "https://ai.example/rss", "ai_news")
    gen_feed = RSSFeed("연합뉴스", "https://yna.example/rss", "general_news")

    ai_entries = [
        # 첫 기사: AI 키워드 매칭 O → 유지
        {
            "title": "GPT 모델 최신 업데이트",
            "link": "https://ai.example/a1",
            "summary": "LLM 기반 성능 개선.",
            "published": "Sun, 19 Apr 2026 07:00:00 +0900",
            "published_parsed": time.strptime(
                "2026-04-19 07:00:00", "%Y-%m-%d %H:%M:%S"
            ),
        },
        # 둘째 기사: AI 키워드 없음 → 드롭
        {
            "title": "반도체 업계 뉴스",
            "link": "https://ai.example/a2",
            "summary": "반도체 생산 동향.",
            "published": "Sun, 19 Apr 2026 08:00:00 +0900",
            "published_parsed": time.strptime(
                "2026-04-19 08:00:00", "%Y-%m-%d %H:%M:%S"
            ),
        },
    ]
    gen_entries = [
        # general_news: AI 키워드 없어도 유지
        {
            "title": "경제 동향 브리핑",
            "link": "https://yna.example/g1",
            "summary": "원달러 환율 상승.",
            "published": "Sun, 19 Apr 2026 09:00:00 +0900",
            "published_parsed": time.strptime(
                "2026-04-19 09:00:00", "%Y-%m-%d %H:%M:%S"
            ),
        },
    ]

    def fake_parse(feed: RSSFeed) -> Any:
        if feed.url == ai_feed.url:
            return _make_parsed(ai_entries)
        return _make_parsed(gen_entries)

    monkeypatch.setattr(collect_mod, "_fetch_feed_once", fake_parse)

    ai_res = collect_mod.process_feed(ai_feed)
    gen_res = collect_mod.process_feed(gen_feed)

    assert ai_res.fetched == 2
    assert ai_res.ai_matched == 1
    assert [a.title for a in ai_res.articles] == ["GPT 모델 최신 업데이트"]

    assert gen_res.fetched == 1
    assert len(gen_res.articles) == 1
    assert gen_res.articles[0].keywords == []


# ---------------------------------------------------------------------------
# 4) 재시도: 2회 실패 후 3회차 성공
# ---------------------------------------------------------------------------


def test_feed_fetch_retry_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    feed = RSSFeed("test", "https://t.example/rss", "ai_news")
    calls: list[int] = []
    sleeps: list[float] = []

    success_parsed = _make_parsed(
        [
            {
                "title": "GPT 소식",
                "link": "https://t.example/1",
                "summary": "",
                "published": "Sun, 19 Apr 2026 07:00:00 +0900",
                "published_parsed": time.strptime(
                    "2026-04-19 07:00:00", "%Y-%m-%d %H:%M:%S"
                ),
            }
        ]
    )

    def flaky_parse(_feed: RSSFeed) -> Any:
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("mock network flap")
        return success_parsed

    parsed, err = collect_mod.fetch_feed_with_retry(
        feed,
        max_retry=3,
        sleep_fn=sleeps.append,
        parse_fn=flaky_parse,
    )

    assert err is None
    assert parsed is success_parsed
    assert len(calls) == 3
    assert sleeps == [1, 2]  # 1s, 2s backoff (3회차는 성공이라 sleep 없음)


# ---------------------------------------------------------------------------
# 5) 3회 모두 실패 시 에러 기록
# ---------------------------------------------------------------------------


def test_feed_fetch_gives_up_after_3_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    feed = RSSFeed("test", "https://t.example/rss", "ai_news")
    calls: list[int] = []
    sleeps: list[float] = []

    def always_fail(_feed: RSSFeed) -> Any:
        calls.append(1)
        raise TimeoutError("mock timeout")

    parsed, err = collect_mod.fetch_feed_with_retry(
        feed,
        max_retry=3,
        sleep_fn=sleeps.append,
        parse_fn=always_fail,
    )

    assert parsed is None
    assert err == "TimeoutError"
    assert len(calls) == 3
    assert sleeps == [1, 2]  # 세 번째 시도 후에는 sleep 하지 않는다.

    # process_feed 전체 경로에서도 에러가 전파되지 않고 기록만 되어야 한다.
    monkeypatch.setattr(collect_mod, "_fetch_feed_once", always_fail)
    monkeypatch.setattr(collect_mod.time, "sleep", lambda _s: None)
    result = collect_mod.process_feed(feed)
    assert result.articles == []
    assert result.error == "TimeoutError"


# ---------------------------------------------------------------------------
# 6) 전체 collect() 흐름 → candidates.json 스키마 검증
# ---------------------------------------------------------------------------


def test_collect_writes_candidates_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ai_feed = RSSFeed("AI타임스", "https://ai.example/rss", "ai_news")
    gen_feed = RSSFeed("연합뉴스", "https://yna.example/rss", "general_news")
    monkeypatch.setattr(collect_mod, "RSS_FEEDS", (ai_feed, gen_feed))

    ai_entries = [
        {
            "title": "Claude 3.5 국내 출시",
            "link": "https://ai.example/1",
            "summary": "생성형 AI <b>신제품</b> 발표.",
            "published": "Sun, 19 Apr 2026 07:00:00 +0900",
            "published_parsed": time.strptime(
                "2026-04-19 07:00:00", "%Y-%m-%d %H:%M:%S"
            ),
        },
        # 키워드 없음 → ai_news 라 드롭되어야 함
        {
            "title": "반도체 업황 개선",
            "link": "https://ai.example/2",
            "summary": "DRAM 가격 반등.",
            "published": "Sun, 19 Apr 2026 07:30:00 +0900",
            "published_parsed": time.strptime(
                "2026-04-19 07:30:00", "%Y-%m-%d %H:%M:%S"
            ),
        },
    ]
    gen_entries = [
        {
            "title": "한국은행 기준금리 동결",
            "link": "https://yna.example/1",
            "summary": "금통위 결정.",
            "published": "Sun, 19 Apr 2026 10:00:00 +0900",
            "published_parsed": time.strptime(
                "2026-04-19 10:00:00", "%Y-%m-%d %H:%M:%S"
            ),
        },
    ]

    def fake_parse(feed: RSSFeed) -> Any:
        if feed.url == ai_feed.url:
            return _make_parsed(ai_entries)
        return _make_parsed(gen_entries)

    monkeypatch.setattr(collect_mod, "_fetch_feed_once", fake_parse)
    monkeypatch.setattr(collect_mod.time, "sleep", lambda _s: None)

    out_path = tmp_path / "candidates.json"
    summary = collect_mod.collect(output_path=out_path)

    assert out_path.exists()
    on_disk = json.loads(out_path.read_text(encoding="utf-8"))
    assert on_disk == summary

    assert set(summary) == {"collection_timestamp", "source_stats", "articles"}
    assert summary["collection_timestamp"].endswith("+09:00")

    stats = summary["source_stats"]
    assert set(stats) == {"AI타임스", "연합뉴스"}
    assert stats["AI타임스"]["fetched"] == 2
    assert stats["AI타임스"]["ai_matched"] == 1
    assert stats["AI타임스"]["kept"] == 1
    assert stats["연합뉴스"]["fetched"] == 1
    assert stats["연합뉴스"]["kept"] == 1

    articles = summary["articles"]
    assert len(articles) == 2
    for art in articles:
        assert set(art) == {
            "article_id",
            "title",
            "source",
            "published_at",
            "original_url",
            "content_text",
            "category",
            "keywords",
        }
        assert art["published_at"].endswith("+09:00")

    # content_text 가 HTML 태그 없이 정리되어 있는지
    ai_article = next(a for a in articles if a["source"] == "AI타임스")
    assert "<b>" not in ai_article["content_text"]
    assert "생성형 AI" in ai_article["content_text"]
    assert "생성형 AI" in ai_article["keywords"]


def test_collect_handles_all_feeds_failing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """모든 피드가 실패해도 빈 articles 로 JSON 을 남긴다."""
    ai_feed = RSSFeed("AI타임스", "https://ai.example/rss", "ai_news")
    gen_feed = RSSFeed("연합뉴스", "https://yna.example/rss", "general_news")
    monkeypatch.setattr(collect_mod, "RSS_FEEDS", (ai_feed, gen_feed))

    def always_fail(_feed: RSSFeed) -> Any:
        raise ConnectionError("down")

    monkeypatch.setattr(collect_mod, "_fetch_feed_once", always_fail)
    monkeypatch.setattr(collect_mod.time, "sleep", lambda _s: None)

    out_path = tmp_path / "candidates.json"
    summary = collect_mod.collect(output_path=out_path)

    assert summary["articles"] == []
    for name in ("AI타임스", "연합뉴스"):
        assert summary["source_stats"][name]["error"] == "ConnectionError"
        assert summary["source_stats"][name]["kept"] == 0
