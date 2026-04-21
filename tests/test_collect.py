"""pipeline.collect 모듈 단위 테스트.

네트워크를 타지 않기 위해 ``feedparser.parse`` 와 ``time.sleep`` 을
monkeypatch 로 치환한다.
"""

from __future__ import annotations

import json
import time
import types
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import pytz

from pipeline import collect as collect_mod
from pipeline.config import RSSFeed

KST = pytz.timezone("Asia/Seoul")


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
# 3) 분류는 피드 카테고리가 아니라 AI 키워드 매칭 결과로 결정
# ---------------------------------------------------------------------------


def test_category_is_decided_by_keyword_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """general_news 카테고리 피드에서는 AI 키워드 매칭으로 분류가 결정된다 (v19).

    ai_news 카테고리 피드는 별도 테스트(feed_category_ai_news_forces)에서 다룸.
    종합·경제 피드에서는 여전히 키워드 매칭이 분류 기준.
    """
    # v19: 두 피드 모두 general_news 로 선언 → 키워드 매칭에 따라 분류됨.
    ai_feed = RSSFeed("경제일반", "https://ai.example/rss", "general_news")
    gen_feed = RSSFeed("연합뉴스", "https://yna.example/rss", "general_news")

    ai_entries = [
        # AI 키워드 O → ai_news (KST 10:00 — evening window 08:25~17:25 안)
        {
            "title": "GPT 모델 최신 업데이트",
            "link": "https://ai.example/a1",
            "summary": "LLM 기반 성능 개선.",
            "published": "Sun, 19 Apr 2026 10:00:00 +0900",
            "published_parsed": time.strptime(
                "2026-04-19 10:00:00", "%Y-%m-%d %H:%M:%S"
            ),
        },
        # AI 키워드 X → general_news (KST 11:00)
        {
            "title": "반도체 업계 뉴스",
            "link": "https://ai.example/a2",
            "summary": "반도체 생산 동향.",
            "published": "Sun, 19 Apr 2026 11:00:00 +0900",
            "published_parsed": time.strptime(
                "2026-04-19 11:00:00", "%Y-%m-%d %H:%M:%S"
            ),
        },
    ]
    gen_entries = [
        # 종합 피드인데 AI 키워드 O → ai_news 로 분류
        {
            "title": "OpenAI 신제품 공개",
            "link": "https://yna.example/g1",
            "summary": "챗GPT 기반 기능 추가.",
            "published": "Sun, 19 Apr 2026 09:00:00 +0900",
            "published_parsed": time.strptime(
                "2026-04-19 09:00:00", "%Y-%m-%d %H:%M:%S"
            ),
        },
        # 종합 피드, 키워드 X → general_news
        {
            "title": "경제 동향 브리핑",
            "link": "https://yna.example/g2",
            "summary": "원달러 환율 상승.",
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

    # fixture 의 published_parsed 는 UTC 로 해석되어 KST 16:00~19:00 으로 떨어진다.
    # 2026-04-19 19:30 KST (오후 evening 윈도우 = 당일 08:25 이후) 에서 수집한다고 고정.
    fixed_now = KST.localize(datetime(2026, 4, 19, 19, 30, 0))

    ai_res = collect_mod.process_feed(ai_feed, now_kst=fixed_now)
    gen_res = collect_mod.process_feed(gen_feed, now_kst=fixed_now)

    # AI 피드: 두 기사 모두 유지 (드롭 없음), 분류만 다름
    assert ai_res.fetched == 2
    assert len(ai_res.articles) == 2
    by_title = {a.title: a for a in ai_res.articles}
    assert by_title["GPT 모델 최신 업데이트"].category == "ai_news"
    assert by_title["반도체 업계 뉴스"].category == "general_news"

    # 종합 피드: 두 기사 모두 유지, AI 키워드 매칭된 것은 ai_news
    assert gen_res.fetched == 2
    assert len(gen_res.articles) == 2
    gen_by_title = {a.title: a for a in gen_res.articles}
    assert gen_by_title["OpenAI 신제품 공개"].category == "ai_news"
    assert gen_by_title["경제 동향 브리핑"].category == "general_news"


def test_match_ai_keywords_word_boundary() -> None:
    """짧은 ASCII 키워드(AI, GPT 등)가 word boundary 매칭을 쓴다.

    예: AIDS, airplane, GPTs 는 매치되지 않아야.
    """
    # 긍정 케이스
    assert "AI" in collect_mod.match_ai_keywords("AI 열풍 가속", "")
    assert "GPT" in collect_mod.match_ai_keywords("GPT-6 발표", "")
    assert "Google" in collect_mod.match_ai_keywords("Google announces…", "")
    # false positive 방지
    assert collect_mod.match_ai_keywords("AIDS 환자 증가", "") == []
    assert collect_mod.match_ai_keywords("airplane 추락", "") == []
    # 한글 키워드는 literal 매칭 유지
    assert "인공지능" in collect_mod.match_ai_keywords("인공지능 기술 발전", "")


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
            "published": "Sun, 19 Apr 2026 10:00:00 +0900",
            "published_parsed": time.strptime(
                "2026-04-19 10:00:00", "%Y-%m-%d %H:%M:%S"
            ),
        },
        # 키워드 없음 → general_news 로 분류되어 유지됨 (이전에는 드롭)
        {
            "title": "반도체 업황 개선",
            "link": "https://ai.example/2",
            "summary": "DRAM 가격 반등.",
            "published": "Sun, 19 Apr 2026 10:30:00 +0900",
            "published_parsed": time.strptime(
                "2026-04-19 10:30:00", "%Y-%m-%d %H:%M:%S"
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

    # fixture 의 published_parsed (07:00 UTC = 16:00 KST 등) 이 윈도우 안에 들어오도록
    # 2026-04-19 19:30 KST (evening) 로 고정.
    fixed_now = KST.localize(datetime(2026, 4, 19, 19, 30, 0))

    out_path = tmp_path / "candidates.json"
    summary = collect_mod.collect(output_path=out_path, now_kst=fixed_now)

    assert out_path.exists()
    on_disk = json.loads(out_path.read_text(encoding="utf-8"))
    assert on_disk == summary

    assert set(summary) == {"collection_timestamp", "source_stats", "articles"}
    assert summary["collection_timestamp"].endswith("+09:00")

    stats = summary["source_stats"]
    assert set(stats) == {"AI타임스", "연합뉴스"}
    # AI 피드도 이제 키워드 없는 기사 드롭 안 함 — kept=2
    assert stats["AI타임스"]["fetched"] == 2
    assert stats["AI타임스"]["ai_matched"] == 1
    assert stats["AI타임스"]["kept"] == 2
    assert stats["연합뉴스"]["fetched"] == 1
    assert stats["연합뉴스"]["kept"] == 1

    articles = summary["articles"]
    # 총 3건 유지 (AI 피드 2 + 종합 피드 1)
    assert len(articles) == 3
    # v19: ai_news 카테고리 피드는 키워드 무관하게 ai_news 로 강제 분류 →
    # AI 피드 2건 모두 ai_news. 종합 피드는 키워드 없으므로 general_news.
    ai_articles = [a for a in articles if a["category"] == "ai_news"]
    gen_articles = [a for a in articles if a["category"] == "general_news"]
    assert len(ai_articles) == 2
    assert len(gen_articles) == 1
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


# ---------------------------------------------------------------------------
# 7) 시간 윈도우 필터 — 오전/오후 브리핑 별로 기간이 다르다.
#    - 오전 브리핑 (08:25 KST) 용 수집: 전날 17:25 KST ~ 수집 시각
#    - 오후 브리핑 (17:25 KST) 용 수집: 당일 08:25 KST ~ 수집 시각
# ---------------------------------------------------------------------------


def test_window_start_for_morning_returns_previous_day_evening() -> None:
    """수집 시각이 정오 이전이면 전날 17:25 KST 를 반환한다."""
    now = KST.localize(datetime(2026, 4, 20, 8, 15, 0))  # 오전 08:15 KST 수집
    start = collect_mod.window_start_for(now)
    assert start == KST.localize(datetime(2026, 4, 19, 17, 25, 0))


def test_window_start_for_evening_returns_same_day_morning() -> None:
    """수집 시각이 정오 이후면 당일 08:25 KST 를 반환한다."""
    now = KST.localize(datetime(2026, 4, 20, 17, 15, 0))  # 오후 17:15 KST 수집
    start = collect_mod.window_start_for(now)
    assert start == KST.localize(datetime(2026, 4, 20, 8, 25, 0))


def test_window_start_for_boundary_noon() -> None:
    """정오(12:00) 는 '이후' 로 취급 (오후 윈도우)."""
    now = KST.localize(datetime(2026, 4, 20, 12, 0, 0))
    start = collect_mod.window_start_for(now)
    assert start == KST.localize(datetime(2026, 4, 20, 8, 25, 0))


def test_process_feed_drops_articles_before_morning_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """오전 수집: 전날 17:25 KST 이전 기사는 드롭된다."""
    feed = RSSFeed("test", "https://t.example/rss", "ai_news")
    # 수집 시각: 2026-04-20 08:15 KST → 윈도우 시작 = 2026-04-19 17:25 KST
    fixed_now = KST.localize(datetime(2026, 4, 20, 8, 15, 0))

    # published_parsed 는 UTC 로 해석됨 → UTC 08:26 = KST 17:26 (윈도우 안),
    # UTC 08:24 = KST 17:24 (윈도우 밖, 딱 1분 일찍).
    entries = [
        {
            "title": "GPT 신규 업데이트 (윈도우 안)",
            "link": "https://t.example/inside",
            "summary": "AI 관련 본문.",
            "published": "Sun, 19 Apr 2026 08:26:00 +0000",
            "published_parsed": time.strptime(
                "2026-04-19 08:26:00", "%Y-%m-%d %H:%M:%S"
            ),
        },
        {
            "title": "이전 GPT 뉴스 (윈도우 밖)",
            "link": "https://t.example/outside",
            "summary": "너무 오래된 기사.",
            "published": "Sun, 19 Apr 2026 08:24:00 +0000",
            "published_parsed": time.strptime(
                "2026-04-19 08:24:00", "%Y-%m-%d %H:%M:%S"
            ),
        },
        {
            "title": "아주 오래된 기사 (이틀 전)",
            "link": "https://t.example/old",
            "summary": "하루 이상 전.",
            "published": "Sat, 18 Apr 2026 03:00:00 +0000",
            "published_parsed": time.strptime(
                "2026-04-18 03:00:00", "%Y-%m-%d %H:%M:%S"
            ),
        },
    ]

    def fake_parse(_feed: RSSFeed) -> Any:
        return _make_parsed(entries)

    monkeypatch.setattr(collect_mod, "_fetch_feed_once", fake_parse)
    result = collect_mod.process_feed(feed, now_kst=fixed_now)

    # fetched 는 전체 3건 카운트되지만, 윈도우 안 1건만 articles 에 남는다.
    kept_titles = [a.title for a in result.articles]
    assert kept_titles == ["GPT 신규 업데이트 (윈도우 안)"]


def test_process_feed_drops_articles_before_evening_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """오후 수집: 당일 08:25 KST 이전 기사는 드롭된다."""
    feed = RSSFeed("test", "https://t.example/rss", "ai_news")
    # 수집 시각: 2026-04-20 17:15 KST → 윈도우 시작 = 2026-04-20 08:25 KST
    fixed_now = KST.localize(datetime(2026, 4, 20, 17, 15, 0))

    # UTC 00:00 = KST 09:00 (윈도우 안)
    # UTC 23:00 (전날) = KST 08:00 (윈도우 밖)
    entries = [
        {
            "title": "AI 오전 기사 (윈도우 안)",
            "link": "https://t.example/morning",
            "summary": "당일 09시 KST.",
            "published": "Mon, 20 Apr 2026 00:00:00 +0000",
            "published_parsed": time.strptime(
                "2026-04-20 00:00:00", "%Y-%m-%d %H:%M:%S"
            ),
        },
        {
            "title": "AI 전날 저녁 기사 (윈도우 밖)",
            "link": "https://t.example/yesterday-evening",
            "summary": "전날 19시 KST.",
            "published": "Sun, 19 Apr 2026 10:00:00 +0000",
            "published_parsed": time.strptime(
                "2026-04-19 10:00:00", "%Y-%m-%d %H:%M:%S"
            ),
        },
    ]

    def fake_parse(_feed: RSSFeed) -> Any:
        return _make_parsed(entries)

    monkeypatch.setattr(collect_mod, "_fetch_feed_once", fake_parse)
    result = collect_mod.process_feed(feed, now_kst=fixed_now)

    kept_titles = [a.title for a in result.articles]
    assert kept_titles == ["AI 오전 기사 (윈도우 안)"]


def test_collect_respects_window_with_injected_now(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """collect() 가 now_kst 를 전 피드에 일관적으로 전파한다."""
    ai_feed = RSSFeed("AI타임스", "https://ai.example/rss", "ai_news")
    monkeypatch.setattr(collect_mod, "RSS_FEEDS", (ai_feed,))

    # 오전 수집 시각 고정
    fixed_now = KST.localize(datetime(2026, 4, 20, 8, 15, 0))

    entries = [
        # 윈도우 안 (전날 18:00 KST = UTC 09:00)
        {
            "title": "Claude 신규 발표",
            "link": "https://ai.example/new",
            "summary": "어제 저녁 발표.",
            "published": "Sun, 19 Apr 2026 09:00:00 +0000",
            "published_parsed": time.strptime(
                "2026-04-19 09:00:00", "%Y-%m-%d %H:%M:%S"
            ),
        },
        # 윈도우 밖 (전날 10:00 KST = UTC 01:00)
        {
            "title": "옛 AI 기사",
            "link": "https://ai.example/old",
            "summary": "어제 오전 기사.",
            "published": "Sun, 19 Apr 2026 01:00:00 +0000",
            "published_parsed": time.strptime(
                "2026-04-19 01:00:00", "%Y-%m-%d %H:%M:%S"
            ),
        },
    ]

    monkeypatch.setattr(
        collect_mod, "_fetch_feed_once", lambda _f: _make_parsed(entries)
    )
    monkeypatch.setattr(collect_mod.time, "sleep", lambda _s: None)

    summary = collect_mod.collect(
        output_path=tmp_path / "candidates.json", now_kst=fixed_now
    )

    titles = [a["title"] for a in summary["articles"]]
    assert titles == ["Claude 신규 발표"]
    # collection_timestamp 는 주입된 now_kst 에 기반
    assert summary["collection_timestamp"].startswith("2026-04-20T08:15:00")


# ---------------------------------------------------------------------------
# v18 — parse_published sentinel + 한겨레 og:meta enrich
# ---------------------------------------------------------------------------


def test_parse_published_returns_none_when_nothing_available() -> None:
    """모든 published 관련 필드가 없으면 None 반환 (sentinel).

    이전에는 fallback_utc_now 를 반환해서 윈도우 필터를 우회했음.
    """

    class _Entry:
        def get(self, key, default=None):
            return default

    entry = _Entry()
    now_utc = datetime(2026, 4, 21, 0, 0, 0, tzinfo=pytz.utc)
    result = collect_mod.parse_published(entry, now_utc)
    assert result is None


def test_parse_published_keeps_parsing_from_struct() -> None:
    """published_parsed (struct_time) 이 있으면 정상 파싱한다 (기존 동작 유지)."""

    class _Entry:
        def get(self, key, default=None):
            if key == "published_parsed":
                return time.strptime("2026-04-19 05:00:00", "%Y-%m-%d %H:%M:%S")
            return default

    entry = _Entry()
    now_utc = datetime(2026, 4, 21, 0, 0, 0, tzinfo=pytz.utc)
    result = collect_mod.parse_published(entry, now_utc)
    assert result is not None
    assert result.hour == 14  # UTC 05:00 → KST 14:00


def test_process_feed_enriches_missing_content_from_article_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RSS entry 의 content/published 가 부족하면 기사 페이지 og:meta 로 복구."""
    feed = RSSFeed("한겨레", "https://www.hani.co.kr/rss/", "general_news")
    fixed_now = KST.localize(datetime(2026, 4, 21, 17, 30, 0))

    # 한겨레 style — published 없고 description 은 이미지 HTML 뿐
    entries = [
        {
            "title": "테스트 기사",
            "link": "https://www.hani.co.kr/arti/test/1234.html",
            "summary": "<table><tr><td><img src=x></td></tr></table>",
            # published_parsed / published 일부러 생략
        },
    ]

    def fake_parse(_f: RSSFeed) -> Any:
        return _make_parsed(entries)

    # enrich fetch mock: og:description + article:published_time 제공
    def fake_enrich(url: str, timeout: float = 5.0) -> dict[str, str]:
        return {
            "description": "이 기사의 본문 요약입니다.",
            "published_time": "2026-04-21T15:00:00+09:00",
        }

    monkeypatch.setattr(collect_mod, "_fetch_feed_once", fake_parse)
    monkeypatch.setattr(collect_mod, "_fetch_article_meta", fake_enrich)

    result = collect_mod.process_feed(feed, now_kst=fixed_now)
    assert len(result.articles) == 1
    art = result.articles[0]
    assert "본문 요약" in art.content_text
    assert art.published_at.startswith("2026-04-21T15:00:00")


def test_process_feed_drops_article_when_enrich_also_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RSS 가 부족하고 enrich 도 실패하면 parse_failed 카운트 + 드롭."""
    feed = RSSFeed("한겨레", "https://www.hani.co.kr/rss/", "general_news")
    fixed_now = KST.localize(datetime(2026, 4, 21, 17, 30, 0))

    entries = [
        {
            "title": "시각 없는 기사",
            "link": "https://www.hani.co.kr/arti/test/9999.html",
            "summary": "",
        },
    ]

    def fake_parse(_f: RSSFeed) -> Any:
        return _make_parsed(entries)

    def fake_enrich(url: str, timeout: float = 5.0) -> dict[str, str]:
        return {}  # 전부 실패

    monkeypatch.setattr(collect_mod, "_fetch_feed_once", fake_parse)
    monkeypatch.setattr(collect_mod, "_fetch_article_meta", fake_enrich)

    result = collect_mod.process_feed(feed, now_kst=fixed_now)
    assert result.articles == []
    assert result.parse_failed == 1
    assert result.fetched == 1


def test_feed_category_ai_news_forces_ai_classification_regardless_of_keywords(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """피드의 category='ai_news' 면 본문에 AI 키워드가 없어도 ai_news 로 분류한다 (v19).

    Anthropic / OpenAI / DeepMind 같은 공식 AI 소스는 제목/본문에 'AI' 가
    안 써 있어도 AI 소식이므로 피드 카테고리 선언을 우선 존중.
    """
    from pipeline.config import RSSFeed

    feed = RSSFeed(
        name="OpenAI", url="https://openai.com/blog/rss.xml",
        category="ai_news", default_tz="UTC",
    )
    fixed_now = KST.localize(datetime(2026, 4, 21, 20, 0, 0))

    entries = [
        # AI_KEYWORDS 어느 것도 포함 안 된 기사 (순수 제품명만)
        {
            "title": "New pelican benchmark dataset released",
            "link": "https://example/a",
            "summary": "A fresh benchmark for evaluating reasoning on pelicans.",
            "published": "Tue, 21 Apr 2026 00:00:00 GMT",
        },
    ]

    monkeypatch.setattr(collect_mod, "_fetch_feed_once", lambda _f: _make_parsed(entries))
    result = collect_mod.process_feed(feed, now_kst=fixed_now)
    assert len(result.articles) == 1
    # 키워드 전혀 없어도 피드 category 가 ai_news 이므로 ai_news 분류.
    assert result.articles[0].keywords == []
    assert result.articles[0].category == "ai_news"


def test_parse_published_naive_string_uses_default_tz() -> None:
    """tz 없는 pubDate 문자열은 default_tz 로 localize 해야 한다 (v19).

    AI타임스 RSS 는 pubDate 에 '2026-04-21 16:53:12' 같이 tz 없는 문자열을
    주는데, feedparser 가 이를 UTC struct_time 으로 저장해서 우리 코드가
    +9h 시프트로 미래 시각을 만들어냈다. raw 문자열을 먼저 파싱하고 tz 가
    없으면 default_tz (한국 소스 = KST) 로 localize.
    """

    class _Entry:
        def get(self, key, default=None):
            if key == "published":
                return "2026-04-21 16:53:12"
            # published_parsed 는 일부러 제공 — feedparser 가 UTC 로 해석한 상태.
            if key == "published_parsed":
                return time.strptime("2026-04-21 16:53:12", "%Y-%m-%d %H:%M:%S")
            return default

    entry = _Entry()
    now_utc = datetime(2026, 4, 21, 0, 0, 0, tzinfo=pytz.utc)

    # default_tz 로 KST 를 명시하면 raw 문자열이 KST 로 해석되어야 한다.
    result = collect_mod.parse_published(entry, now_utc, default_tz=KST)
    assert result is not None
    # 2026-04-21 16:53:12 KST (= 07:53:12 UTC). +9h 미래(01:53 익일)가 아님.
    assert result.strftime("%Y-%m-%d %H:%M") == "2026-04-21 16:53"


def test_parse_published_respects_explicit_tz_in_raw() -> None:
    """raw pubDate 에 tz 가 명시돼 있으면 default_tz 는 무시하고 그걸 따른다."""

    class _Entry:
        def get(self, key, default=None):
            if key == "published":
                return "Mon, 21 Apr 2026 08:00:00 +0000"  # UTC 명시
            return default

    entry = _Entry()
    now_utc = datetime(2026, 4, 21, 0, 0, 0, tzinfo=pytz.utc)
    result = collect_mod.parse_published(entry, now_utc, default_tz=KST)
    assert result is not None
    # UTC 08:00 = KST 17:00
    assert result.strftime("%Y-%m-%d %H:%M") == "2026-04-21 17:00"


def test_rssfeed_has_default_tz_field() -> None:
    """RSSFeed 에 default_tz 필드가 있어 소스별 tz 힌트를 선언할 수 있다."""
    from pipeline.config import RSSFeed

    f = RSSFeed(
        name="test", url="https://example.com", category="ai_news",
        default_tz="UTC",
    )
    assert f.default_tz == "UTC"


def test_process_feed_uses_feed_default_tz_for_naive_times(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AI타임스 style (tz 없는 pubDate) 가 feed.default_tz=Asia/Seoul 로 정정된다."""
    from pipeline.config import RSSFeed

    feed = RSSFeed(
        name="AI타임스", url="https://ai.example/rss", category="ai_news",
        default_tz="Asia/Seoul",
    )
    fixed_now = KST.localize(datetime(2026, 4, 21, 20, 0, 0))

    entries = [
        {
            "title": "KST 의미인 기사",
            "link": "https://ai.example/1",
            "summary": "테스트.",
            # tz 없음 — KST 로 해석되어야 함
            "published": "2026-04-21 16:53:12",
            "published_parsed": time.strptime(
                "2026-04-21 16:53:12", "%Y-%m-%d %H:%M:%S"
            ),
        },
    ]

    monkeypatch.setattr(collect_mod, "_fetch_feed_once", lambda _f: _make_parsed(entries))
    result = collect_mod.process_feed(feed, now_kst=fixed_now)
    assert len(result.articles) == 1
    # +9h shift 가 있으면 "2026-04-22T01:53" 으로 나올 것. 정답은 KST 16:53.
    assert result.articles[0].published_at.startswith("2026-04-21T16:53")


def test_collect_source_stats_include_parse_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """source_stats 에 parse_failed 카운트가 노출된다."""
    feed = RSSFeed("한겨레", "https://www.hani.co.kr/rss/", "general_news")
    monkeypatch.setattr(collect_mod, "RSS_FEEDS", (feed,))
    fixed_now = KST.localize(datetime(2026, 4, 21, 17, 30, 0))

    entries = [
        {"title": "A", "link": "https://www.hani.co.kr/a", "summary": ""},
        {"title": "B", "link": "https://www.hani.co.kr/b", "summary": ""},
    ]

    monkeypatch.setattr(
        collect_mod, "_fetch_feed_once", lambda _f: _make_parsed(entries)
    )
    monkeypatch.setattr(
        collect_mod, "_fetch_article_meta", lambda _url, timeout=5.0: {}
    )
    monkeypatch.setattr(collect_mod.time, "sleep", lambda _s: None)

    summary = collect_mod.collect(
        output_path=tmp_path / "candidates.json", now_kst=fixed_now
    )
    assert summary["source_stats"]["한겨레"]["parse_failed"] == 2
    assert summary["source_stats"]["한겨레"]["kept"] == 0


# ---------------------------------------------------------------------------
# v20 — 피드별 rolling window_hours
# ---------------------------------------------------------------------------


def test_window_for_with_hours_rolls_back_that_amount() -> None:
    """window_hours 지정 시 now 로부터 해당 시간만큼 rolling 윈도우."""
    now = KST.localize(datetime(2026, 4, 22, 10, 0, 0))
    start, end = collect_mod.window_for(now, window_hours=72)
    assert end == now
    assert (end - start).total_seconds() == 72 * 3600
    assert start == KST.localize(datetime(2026, 4, 19, 10, 0, 0))


def test_window_for_without_hours_uses_default() -> None:
    """window_hours=None 이면 기존 오전/오후 고정 윈도우 유지."""
    morning = KST.localize(datetime(2026, 4, 22, 8, 15, 0))
    start, end = collect_mod.window_for(morning, window_hours=None)
    assert start == KST.localize(datetime(2026, 4, 21, 17, 25, 0))
    assert end == KST.localize(datetime(2026, 4, 22, 8, 25, 0))


def test_process_feed_uses_feed_window_hours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """feed.window_hours 가 설정되면 해당 rolling 윈도우 적용."""
    feed = RSSFeed(
        name="OfficialAI", url="https://ai.example/rss",
        category="official_ai", default_tz="UTC", window_hours=72,
    )
    fixed_now = KST.localize(datetime(2026, 4, 22, 10, 0, 0))

    # 48시간 전 기사 — 기본 윈도우엔 탈락이지만 72h 윈도우엔 통과
    entries = [
        {
            "title": "Old but within 72h",
            "link": "https://ai.example/1",
            "summary": "Some AI news.",
            "published": "Mon, 20 Apr 2026 10:00:00 +0000",
        },
    ]

    def fake_parse(_f: RSSFeed) -> Any:
        return _make_parsed(entries)

    monkeypatch.setattr(collect_mod, "_fetch_feed_once", fake_parse)
    result = collect_mod.process_feed(feed, now_kst=fixed_now)
    assert len(result.articles) == 1
    assert result.articles[0].title == "Old but within 72h"
