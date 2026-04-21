"""pipeline.render 단위 테스트."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from pipeline import render as render_mod
from pipeline.render import (
    build_sections,
    format_published_display,
    period_and_hero,
    pick_must_know,
    render,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = str(REPO_ROOT / "templates" / "report.html.j2")


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------


def make_article(
    *,
    idx: int,
    category: str = "ai_news",
    source: str = "AI타임스",
    score: float = 7.0,
    is_must_know: bool = False,
    published_at: str = "2026-04-19T07:00:00+09:00",
    title: str | None = None,
    keywords: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "article_id": f"art-{idx:04d}",
        "title": title or f"샘플 제목 {idx}",
        "source": source,
        "published_at": published_at,
        "original_url": f"https://example.com/{idx}",
        "content_text": f"원문 본문 {idx}",
        "ai_summary": f"AI 요약 {idx}",
        "extraction_reason": f"추출 이유 {idx}",
        "relevance_score": score,
        "keywords": list(keywords or []),
        "category": category,
        "is_must_know": is_must_know,
    }


def make_analyzed(
    *,
    issue_number: int = 123,
    generation_timestamp: str = "2026-04-19T07:02:00+09:00",
    trend_hashtags: list[str] | None = None,
    articles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "issue_number": issue_number,
        "generation_timestamp": generation_timestamp,
        "trend_hashtags": list(trend_hashtags or ["생성형AI", "반도체", "금리"]),
        "articles": list(articles or []),
    }


@pytest.fixture()
def analyzed_sample() -> dict[str, Any]:
    articles = [
        make_article(
            idx=1,
            category="ai_news",
            source="AI타임스",
            score=9.2,
            is_must_know=True,
            title="OpenAI, GPT-5 공식 출시",
            keywords=["GPT", "LLM"],
        ),
        make_article(
            idx=2,
            category="ai_news",
            source="ZDNet Korea",
            score=8.1,
            is_must_know=True,
            title="Claude 4.8 1M 컨텍스트 확대",
            keywords=["Claude"],
        ),
        make_article(
            idx=3,
            category="general_news",
            source="연합뉴스",
            score=9.5,
            is_must_know=True,
            title="한은 기준금리 0.5%p 인하",
            keywords=[],
        ),
        make_article(
            idx=4,
            category="general_news",
            source="매일경제",
            score=7.5,
            is_must_know=False,
            title="부동산 양도세 개편",
            keywords=[],
        ),
    ]
    return make_analyzed(
        issue_number=112,
        generation_timestamp="2026-04-19T07:00:00+09:00",
        trend_hashtags=["GPT-5", "HBM4", "금리인하"],
        articles=articles,
    )


def _write_analyzed(tmp_path: Path, payload: dict[str, Any]) -> Path:
    p = tmp_path / "analyzed.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 1. 기본 렌더
# ---------------------------------------------------------------------------


def test_render_produces_html_file(tmp_path, analyzed_sample):
    analyzed = _write_analyzed(tmp_path, analyzed_sample)
    out_html = tmp_path / "index.html"
    archive_dir = tmp_path / "archive"

    result = render(
        analyzed_path=str(analyzed),
        template_path=TEMPLATE_PATH,
        output_path=str(out_html),
        archive_dir=str(archive_dir),
    )

    assert out_html.exists()
    content = out_html.read_text(encoding="utf-8")
    assert content.startswith("<!DOCTYPE html>")
    assert result["html_path"] == str(out_html)
    assert result["issue_number"] == 112
    assert result["article_count"] == 4


# ---------------------------------------------------------------------------
# 2. 아카이브 스냅샷
# ---------------------------------------------------------------------------


def test_render_archives_snapshot(tmp_path, analyzed_sample):
    analyzed = _write_analyzed(tmp_path, analyzed_sample)
    out_html = tmp_path / "index.html"
    archive_dir = tmp_path / "archive"

    result = render(
        analyzed_path=str(analyzed),
        template_path=TEMPLATE_PATH,
        output_path=str(out_html),
        archive_dir=str(archive_dir),
    )

    archive_path = Path(result["archive_path"])
    assert archive_path.exists()
    # 파일명 = YYYY-MM-DD-HHMM.html, 생성시각 07:00 → 2026-04-19-0700.html
    assert archive_path.name == "2026-04-19-0700.html"
    assert archive_path.read_text(encoding="utf-8") == out_html.read_text(
        encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# 3. 섹션 그룹핑
# ---------------------------------------------------------------------------


def test_section_grouping(tmp_path, analyzed_sample):
    analyzed = _write_analyzed(tmp_path, analyzed_sample)
    out_html = tmp_path / "index.html"
    render(
        analyzed_path=str(analyzed),
        template_path=TEMPLATE_PATH,
        output_path=str(out_html),
        archive_dir=str(tmp_path / "archive"),
    )

    html = out_html.read_text(encoding="utf-8")
    assert "AI 뉴스" in html
    assert "종합 뉴스" in html


def test_section_grouping_unit():
    articles = [
        make_article(idx=1, category="ai_news", score=8.0),
        make_article(idx=2, category="general_news", score=9.0),
        make_article(idx=3, category="ai_news", score=9.5),
    ]
    sections = build_sections(articles)
    assert [s["title"] for s in sections] == ["AI 뉴스", "종합 뉴스"]
    # AI 뉴스 섹션은 score desc 정렬: 9.5 먼저.
    assert sections[0]["articles"][0]["article_id"] == "art-0003"
    assert sections[0]["articles"][1]["article_id"] == "art-0001"
    assert sections[1]["articles"][0]["article_id"] == "art-0002"


# ---------------------------------------------------------------------------
# 4. must_know top5
# ---------------------------------------------------------------------------


def test_must_know_is_top5_by_score(tmp_path):
    # 10건의 must_know 기사를 score 1.0~10.0 로 생성.
    articles = [
        make_article(
            idx=i,
            category="ai_news" if i % 2 == 0 else "general_news",
            score=float(i),
            is_must_know=True,
            title=f"MustKnow Title {i:02d}",
        )
        for i in range(1, 11)
    ]
    analyzed = make_analyzed(
        issue_number=999,
        generation_timestamp="2026-04-19T07:00:00+09:00",
        articles=articles,
    )

    path = _write_analyzed(tmp_path, analyzed)
    out_html = tmp_path / "index.html"
    render(
        analyzed_path=str(path),
        template_path=TEMPLATE_PATH,
        output_path=str(out_html),
        archive_dir=str(tmp_path / "archive"),
    )

    html = out_html.read_text(encoding="utf-8")
    # must-read section 내부만 추출 (class 값에 must-read 토큰 포함 여부로 매치).
    section = re.search(
        r'<section[^>]*class="[^"]*must-read[^"]*"[^>]*>(.*?)</section>',
        html,
        flags=re.DOTALL,
    )
    assert section is not None, "must-read 섹션이 렌더되지 않음"
    section_html = section.group(1)
    # 총 10건 중 상위 5건만 (10~6) 노출.
    for i in (10, 9, 8, 7, 6):
        assert f"MustKnow Title {i:02d}" in section_html
    # 6 미만은 must-read 에 없어야 함.
    for i in (5, 4, 3, 2, 1):
        assert f"MustKnow Title {i:02d}" not in section_html


def test_pick_must_know_limits_top_five():
    articles = [
        make_article(idx=i, score=float(i), is_must_know=True) for i in range(1, 11)
    ]
    picked = pick_must_know(articles)
    assert len(picked) == 5
    scores = [a["relevance_score"] for a in picked]
    assert scores == [10.0, 9.0, 8.0, 7.0, 6.0]


# ---------------------------------------------------------------------------
# 5. 시간대 분기
# ---------------------------------------------------------------------------


def test_period_label_morning_vs_evening(tmp_path, analyzed_sample):
    # 오전 (07:00 KST).
    morning_dir = tmp_path / "m"
    morning_dir.mkdir()
    analyzed_m = _write_analyzed(morning_dir, analyzed_sample)
    out_m = morning_dir / "index.html"
    render(
        analyzed_path=str(analyzed_m),
        template_path=TEMPLATE_PATH,
        output_path=str(out_m),
        archive_dir=str(morning_dir / "archive"),
    )
    html_m = out_m.read_text(encoding="utf-8")
    assert "오전" in html_m
    assert "굿모닝" in html_m

    # 오후 (18:00 KST).
    evening = dict(analyzed_sample)
    evening["generation_timestamp"] = "2026-04-19T18:00:00+09:00"
    evening_dir = tmp_path / "e"
    evening_dir.mkdir()
    analyzed_e = _write_analyzed(evening_dir, evening)
    out_e = evening_dir / "index.html"
    render(
        analyzed_path=str(analyzed_e),
        template_path=TEMPLATE_PATH,
        output_path=str(out_e),
        archive_dir=str(evening_dir / "archive"),
    )
    html_e = out_e.read_text(encoding="utf-8")
    assert "오후" in html_e
    assert "굿이브닝" in html_e


def test_period_and_hero_unit():
    import pytz

    kst = pytz.timezone("Asia/Seoul")
    morning = kst.localize(__import__("datetime").datetime(2026, 4, 19, 7, 0))
    evening = kst.localize(__import__("datetime").datetime(2026, 4, 19, 18, 0))
    noon = kst.localize(__import__("datetime").datetime(2026, 4, 19, 12, 0))

    assert period_and_hero(morning) == ("오전", "굿모닝")
    assert period_and_hero(evening) == ("오후", "굿이브닝")
    # 경계값: 12 시 이하 → 오전 (seed 에 따라).
    assert period_and_hero(noon) == ("오전", "굿모닝")


# ---------------------------------------------------------------------------
# 6. published_at 포맷
# ---------------------------------------------------------------------------


def test_published_display_same_day_vs_other():
    import pytz

    kst = pytz.timezone("Asia/Seoul")
    reference = kst.localize(__import__("datetime").datetime(2026, 4, 19, 7, 0))

    same_day = kst.localize(__import__("datetime").datetime(2026, 4, 19, 6, 48))
    other_day = kst.localize(__import__("datetime").datetime(2026, 4, 17, 23, 30))

    assert format_published_display(same_day, reference) == "06:48"
    assert format_published_display(other_day, reference) == "04.17 23:30"


def test_published_display_renders_in_html(tmp_path):
    articles = [
        make_article(
            idx=1,
            category="ai_news",
            published_at="2026-04-19T06:48:00+09:00",
            title="SameDayArticle",
        ),
        make_article(
            idx=2,
            category="general_news",
            published_at="2026-04-17T23:30:00+09:00",
            title="OtherDayArticle",
        ),
    ]
    analyzed = make_analyzed(
        generation_timestamp="2026-04-19T07:00:00+09:00", articles=articles
    )
    path = _write_analyzed(tmp_path, analyzed)
    out = tmp_path / "index.html"
    render(
        analyzed_path=str(path),
        template_path=TEMPLATE_PATH,
        output_path=str(out),
        archive_dir=str(tmp_path / "archive"),
    )
    html = out.read_text(encoding="utf-8")
    assert "06:48" in html
    assert "04.17 23:30" in html


# ---------------------------------------------------------------------------
# 7. 푸터 RSS 소스 6개
# ---------------------------------------------------------------------------


def test_footer_contains_all_six_sources(tmp_path, analyzed_sample):
    """footer 에 config.RSS_FEEDS 의 모든 소스 이름이 표시된다 (Medium Reader)."""
    analyzed = _write_analyzed(tmp_path, analyzed_sample)
    out = tmp_path / "index.html"
    render(
        analyzed_path=str(analyzed),
        template_path=TEMPLATE_PATH,
        output_path=str(out),
        archive_dir=str(tmp_path / "archive"),
    )
    html = out.read_text(encoding="utf-8")

    footer_match = re.search(r"<footer[^>]*>(.*?)</footer>", html, flags=re.DOTALL)
    assert footer_match is not None
    footer = footer_match.group(1)
    for name in (
        "AI타임스",
        "ZDNet Korea",
        "전자신문",
        "연합뉴스",
        "매일경제",
        "한겨레",
    ):
        assert name in footer, f"footer 에 {name} 이 없음"


def test_footer_contains_ai_disclosure(tmp_path, analyzed_sample):
    analyzed = _write_analyzed(tmp_path, analyzed_sample)
    out = tmp_path / "index.html"
    render(
        analyzed_path=str(analyzed),
        template_path=TEMPLATE_PATH,
        output_path=str(out),
        archive_dir=str(tmp_path / "archive"),
    )
    html = out.read_text(encoding="utf-8")
    assert (
        "본 리포트는 Claude Opus 4.7이 RSS 원문을 분석해 생성합니다. "
        "사실관계는 각 원문에서 확인하세요." in html
    )
    assert "ISSUE #112" in html


# ---------------------------------------------------------------------------
# 8. 키워드 해시태그
# ---------------------------------------------------------------------------


def test_keywords_rendered_as_hashtags(tmp_path):
    articles = [
        make_article(
            idx=1,
            category="ai_news",
            keywords=["GPT", "LLM"],
            title="KeywordArticle",
        )
    ]
    analyzed = make_analyzed(articles=articles)
    path = _write_analyzed(tmp_path, analyzed)
    out = tmp_path / "index.html"
    render(
        analyzed_path=str(path),
        template_path=TEMPLATE_PATH,
        output_path=str(out),
        archive_dir=str(tmp_path / "archive"),
    )
    html = out.read_text(encoding="utf-8")
    # "# GPT"와 "# LLM"이 모두 렌더되어야 함.
    assert "# GPT" in html
    assert "# LLM" in html


# ---------------------------------------------------------------------------
# 9. Medium Reader 고유 마커 (v19) — 플로팅 네비 + 점수 색상 6단계
# ---------------------------------------------------------------------------


def test_floating_nav_rendered(tmp_path, analyzed_sample):
    """하단 고정 섹션 네비게이션이 렌더된다 (꼭알아야 / AI / 종합 anchor)."""
    analyzed = _write_analyzed(tmp_path, analyzed_sample)
    out = tmp_path / "index.html"
    render(
        analyzed_path=str(analyzed),
        template_path=TEMPLATE_PATH,
        output_path=str(out),
        archive_dir=str(tmp_path / "archive"),
    )
    html = out.read_text(encoding="utf-8")
    assert 'class="floating-nav"' in html
    assert 'href="#sec-mustknow"' in html
    assert 'href="#sec-ai"' in html
    assert 'href="#sec-general"' in html


def test_section_anchor_ids_present(tmp_path, analyzed_sample):
    """3개 섹션 anchor id 가 HTML 에 존재해 플로팅 네비가 유효한 target 을 가진다."""
    analyzed = _write_analyzed(tmp_path, analyzed_sample)
    out = tmp_path / "index.html"
    render(
        analyzed_path=str(analyzed),
        template_path=TEMPLATE_PATH,
        output_path=str(out),
        archive_dir=str(tmp_path / "archive"),
    )
    html = out.read_text(encoding="utf-8")
    assert 'id="sec-mustknow"' in html
    assert 'id="sec-ai"' in html
    assert 'id="sec-general"' in html


def test_score_color_class_mapping(tmp_path):
    """점수 → 색상 클래스 매핑이 의도대로 (9.0+ vhigh, 8.5+ superhigh, ...)."""
    articles = [
        make_article(idx=1, category="ai_news", score=9.3, is_must_know=True),
        make_article(idx=2, category="ai_news", score=8.6, is_must_know=True),
        make_article(idx=3, category="ai_news", score=8.1, is_must_know=True),
        make_article(idx=4, category="general_news", score=7.5, is_must_know=True),
        make_article(idx=5, category="general_news", score=5.5, is_must_know=True),
        make_article(idx=6, category="general_news", score=3.2, is_must_know=True),
    ]
    analyzed = make_analyzed(issue_number=1, articles=articles)
    path = _write_analyzed(tmp_path, analyzed)
    out = tmp_path / "index.html"
    render(
        analyzed_path=str(path),
        template_path=TEMPLATE_PATH,
        output_path=str(out),
        archive_dir=str(tmp_path / "archive"),
    )
    html = out.read_text(encoding="utf-8")
    # 각 등급 클래스가 최소 1회 나타나야 한다.
    assert "score-vhigh" in html
    assert "score-superhigh" in html
    assert "score-high" in html
    assert "score-midhigh" in html
    assert "score-mid" in html
    assert "score-low" in html


# ---------------------------------------------------------------------------
# 인사이트 레이어 (v9)
# ---------------------------------------------------------------------------


def _minimal_article(**overrides: Any) -> dict[str, Any]:
    base = {
        "article_id": "a1",
        "title": "샘플 기사",
        "source": "테스트",
        "published_at": "2026-04-19T06:00:00+09:00",
        "original_url": "https://example.com/a1",
        "content_text": "본문",
        "category": "ai_news",
        "keywords": ["AI"],
        "ai_summary": "요약입니다.",
        "extraction_reason": "주목해야 할 이유",
        "relevance_score": 9.0,
        "is_must_know": True,
    }
    base.update(overrides)
    return base


def _wrap_analyzed(article: dict[str, Any]) -> dict[str, Any]:
    return {
        "issue_number": 1,
        "generation_timestamp": "2026-04-19T07:00:00+09:00",
        "trend_hashtags": ["AI"],
        "articles": [article],
    }


def _render_to_html(tmp_path: Path, analyzed: dict[str, Any]) -> str:
    path = tmp_path / "analyzed.json"
    path.write_text(json.dumps(analyzed, ensure_ascii=False), encoding="utf-8")
    out_path = tmp_path / "index.html"
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    render(
        analyzed_path=str(path),
        template_path=TEMPLATE_PATH,
        output_path=str(out_path),
        archive_dir=str(archive_dir),
    )
    return out_path.read_text(encoding="utf-8")


def test_insights_block_rendered_when_present(tmp_path: Path) -> None:
    """insights 필드가 있으면 details 토글 블록이 렌더된다."""
    art = _minimal_article(insights={
        "ripple": {
            "title": "이게 우리한테 어떻게 영향을 줄까?",
            "icon": "📡",
            "text": "파급 효과 설명 문단입니다.",
        },
        "history": {
            "title": "예전에도 이런 일이 있었을까?",
            "icon": "🗂",
            "text": "역사 비교 설명 문단입니다.",
        },
        "bonus": [],
    })
    html = _render_to_html(tmp_path, _wrap_analyzed(art))
    assert '<details class="why-insights"' in html
    assert "이게 우리한테 어떻게 영향을 줄까?" in html
    assert "예전에도 이런 일이 있었을까?" in html
    assert "파급 효과 설명 문단입니다." in html
    assert "역사 비교 설명 문단입니다." in html


def test_insights_absent_omits_details_block(tmp_path: Path) -> None:
    """insights 가 없으면 why-insights details 블록은 렌더되지 않는다 (Medium Reader).

    이전 다크엠버 디자인은 extraction_reason 전용 fallback 블록이 있었지만
    Medium Reader 디자인에서는 insights 가 없으면 간결하게 생략한다.
    """
    art = _minimal_article(extraction_reason="이유")  # insights 없음
    html = _render_to_html(tmp_path, _wrap_analyzed(art))
    assert '<details class="why-insights"' not in html


def test_period_respects_explicit_period_field_over_clock(tmp_path: Path) -> None:
    """analyzed.json 에 'period' 가 명시되면 시각이 아닌 그 값을 우선해 hero 결정.

    21시(저녁)에 오전 수동 실행 시 generation_timestamp 만 봐서
    '굿이브닝' 으로 잘못 렌더되던 버그 재현·수정.
    """
    analyzed = {
        "issue_number": 10,
        "generation_timestamp": "2026-04-19T21:16:00+09:00",  # 저녁 시각
        "period": "오전",  # 하지만 명시적으로 오전 브리핑
        "trend_hashtags": [],
        "articles": [{
            "article_id": "a1",
            "title": "샘플",
            "source": "테스트",
            "published_at": "2026-04-19T20:00:00+09:00",
            "original_url": "https://example.com/a1",
            "content_text": "",
            "category": "ai_news",
            "keywords": [],
            "ai_summary": "요약",
            "extraction_reason": "이유",
            "relevance_score": 9.0,
            "is_must_know": True,
        }],
    }
    html = _render_to_html(tmp_path, analyzed)
    assert "굿모닝" in html, "period='오전' 이면 시각이 저녁이어도 '굿모닝'이 나와야 한다"
    assert "굿이브닝" not in html


def test_period_falls_back_to_clock_when_not_specified(tmp_path: Path) -> None:
    """analyzed.json 에 period 없으면 기존처럼 generation_timestamp 시각으로 판단."""
    analyzed = {
        "issue_number": 11,
        "generation_timestamp": "2026-04-19T07:02:00+09:00",  # 오전 시각
        # period 필드 없음
        "trend_hashtags": [],
        "articles": [{
            "article_id": "a1",
            "title": "샘플",
            "source": "테스트",
            "published_at": "2026-04-19T06:00:00+09:00",
            "original_url": "https://example.com/a1",
            "content_text": "",
            "category": "ai_news",
            "keywords": [],
            "ai_summary": "요약",
            "extraction_reason": "이유",
            "relevance_score": 9.0,
            "is_must_know": True,
        }],
    }
    html = _render_to_html(tmp_path, analyzed)
    assert "굿모닝" in html  # 07시 → 오전


def test_insights_bonus_axes_rendered(tmp_path: Path) -> None:
    """insights.bonus 리스트 각 항목이 독립 블록으로 렌더된다."""
    art = _minimal_article(insights={
        "ripple": {"title": "RT", "icon": "📡", "text": "R text"},
        "history": {"title": "HT", "icon": "🗂", "text": "H text"},
        "bonus": [
            {"type": "personal", "title": "나는 뭘 해야 할까?",
             "icon": "💡", "text": "P text"},
            {"type": "scenario", "title": "앞으로 어떻게 될까?",
             "icon": "🔮", "text": "S text"},
        ],
    })
    html = _render_to_html(tmp_path, _wrap_analyzed(art))
    assert "나는 뭘 해야 할까?" in html
    assert "P text" in html
    assert "앞으로 어떻게 될까?" in html
    assert "S text" in html
    assert 'data-axis="personal"' in html
    assert 'data-axis="scenario"' in html
