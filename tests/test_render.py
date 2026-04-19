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
    # must-read section 내부만 추출.
    section = re.search(
        r'<section class="must-read"[^>]*>(.*?)</section>',
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
    analyzed = _write_analyzed(tmp_path, analyzed_sample)
    out = tmp_path / "index.html"
    render(
        analyzed_path=str(analyzed),
        template_path=TEMPLATE_PATH,
        output_path=str(out),
        archive_dir=str(tmp_path / "archive"),
    )
    html = out.read_text(encoding="utf-8")

    # footer 태그 안에서만 확인.
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
# 9. FX D+E 양쪽 활성, FX 스위처 제거
# ---------------------------------------------------------------------------


def test_fx_d_and_e_both_active(tmp_path, analyzed_sample):
    analyzed = _write_analyzed(tmp_path, analyzed_sample)
    out = tmp_path / "index.html"
    render(
        analyzed_path=str(analyzed),
        template_path=TEMPLATE_PATH,
        output_path=str(out),
        archive_dir=str(tmp_path / "archive"),
    )
    html = out.read_text(encoding="utf-8")

    # D+E 결합 선택자 사용 확인.
    assert 'body[data-fx="de"]' in html
    assert '<body data-fx="de">' in html

    # D 고유: 문자 스플래시 + 슬라이드 진입 + 섹션 줌인.
    assert "fxDE-char" in html
    assert "translateX(-60px)" in html  # D 기사 슬라이드 진입
    assert "scale(0.94)" in html  # D 섹션 줌인

    # E 고유: 엠버 블록 만스트레드 + 대각선 스트라이프 악센트 바 + 지그재그 회전.
    assert "repeating-linear-gradient" in html  # E 대각선 스트라이프
    assert "rotate(-0.25deg)" in html or "rotate(-0.8deg)" in html  # E 지그재그
    assert "background: var(--accent)" in html  # E must-read 엠버 블록

    # E 호버 invert 효과.
    assert 'body[data-fx="de"] .article:hover' in html

    # FX 스위처 UI 및 다른 FX 블록 제거 확인.
    assert ".fx-switcher" not in html
    assert ".fx-label" not in html
    assert 'data-fx-btn=' not in html
    # FX A/B/C/F keyframes 제거 확인.
    assert "fxA-title" not in html
    assert "fxA-item" not in html
    assert "fxA-bar" not in html
    assert "fxB-" not in html
    assert "fxC-" not in html
    assert "fxF-" not in html
    # data-fx="a"/"b"/"c"/"f" 같은 대체 FX 선택자가 없어야 함.
    assert 'data-fx="a"' not in html
    assert 'data-fx="b"' not in html
    assert 'data-fx="c"' not in html
    assert 'data-fx="f"' not in html

    # IntersectionObserver JS (D에 필요) 유지 확인.
    assert "IntersectionObserver" in html
    assert "fx-in" in html


# ---------------------------------------------------------------------------
# 보너스: must_read 블록이 amber-on-black 타이포 배너인지 스냅샷 체크
# ---------------------------------------------------------------------------


def test_must_read_is_full_amber_banner(tmp_path, analyzed_sample):
    analyzed = _write_analyzed(tmp_path, analyzed_sample)
    out = tmp_path / "index.html"
    render(
        analyzed_path=str(analyzed),
        template_path=TEMPLATE_PATH,
        output_path=str(out),
        archive_dir=str(tmp_path / "archive"),
    )
    html = out.read_text(encoding="utf-8")
    # .must-read 베이스 CSS: background: var(--accent); color: var(--bg).
    # CSS 블록 안의 속성 순서를 유연하게 정규식으로 검증.
    must_read_block = re.search(
        r"\.must-read\s*\{[^}]*\}", html, flags=re.DOTALL
    )
    assert must_read_block is not None
    block = must_read_block.group(0)
    assert "background: var(--accent)" in block
    assert "color: var(--bg)" in block

    # 900 weight + 0.18em spacing.
    h2_block = re.search(
        r"\.must-read h2\s*\{[^}]*\}", html, flags=re.DOTALL
    )
    assert h2_block is not None
    assert "font-weight: 900" in h2_block.group(0)
    assert "letter-spacing: 0.18em" in h2_block.group(0)


def test_section_has_two_pixel_amber_border_and_12_radius(tmp_path, analyzed_sample):
    analyzed = _write_analyzed(tmp_path, analyzed_sample)
    out = tmp_path / "index.html"
    render(
        analyzed_path=str(analyzed),
        template_path=TEMPLATE_PATH,
        output_path=str(out),
        archive_dir=str(tmp_path / "archive"),
    )
    html = out.read_text(encoding="utf-8")

    section_block = re.search(r"\.section\s*\{[^}]*\}", html, flags=re.DOTALL)
    assert section_block is not None
    block = section_block.group(0)
    assert "border-radius: 12px" in block
    assert "border: 2px solid var(--accent)" in block


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


def test_insights_absent_falls_back_to_simple_why(tmp_path: Path) -> None:
    """insights 필드가 없으면 기존 .why 박스만 렌더 (하위호환)."""
    art = _minimal_article(extraction_reason="이유")  # insights 없음
    html = _render_to_html(tmp_path, _wrap_analyzed(art))
    assert '<details class="why-insights"' not in html
    assert '<div class="why">' in html
    assert "추출 이유</strong>이유" in html


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
