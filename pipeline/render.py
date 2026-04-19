"""HTML 렌더러 — ``state/analyzed.json`` → ``docs/index.html`` + archive 복사.

- Jinja2(autoescape=True, trim_blocks=True, lstrip_blocks=True) 로 ``templates/report.html.j2`` 를 렌더.
- KST 생성시각 기준으로 오전/오후 · 굿모닝/굿이브닝 분기.
- 기사 ``published_at`` 이 같은 날이면 ``HH:MM``, 다른 날이면 ``MM.DD HH:MM``.
- 카테고리(ai_news / general_news) 기준으로 섹션 그룹핑, ``relevance_score`` desc 정렬.
- ``is_must_know`` 기사 상위 5건을 "꼭 알아야 할 뉴스" 블록에 노출.
- 생성시각(``YYYY.MM.DD HH:MM KST``) 기반 파일명으로 ``archive/YYYY-MM-DD-HHMM.html`` 도 기록.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pytz
from dateutil import parser as dtparser
from jinja2 import Environment, FileSystemLoader, select_autoescape

from pipeline.config import (
    ANALYZED_JSON_PATH,
    ARCHIVE_DIR,
    KST_TZ_NAME,
    OUTPUT_HTML_PATH,
    RSS_FEEDS,
)

logger = logging.getLogger(__name__)

KST = pytz.timezone(KST_TZ_NAME)

DEFAULT_TEMPLATE_PATH: str = "templates/report.html.j2"

# 시간대 분기 기준 (KST hour): ≤ 12 → 오전/굿모닝, 그 외 → 오후/굿이브닝.
MORNING_HOUR_CUTOFF: int = 12


# ---------------------------------------------------------------------------
# 유틸
# ---------------------------------------------------------------------------


def _parse_kst(iso_str: str) -> datetime:
    """ISO-8601 문자열을 KST-aware ``datetime`` 으로 파싱.

    tz 정보가 없으면 KST 로 간주한다.
    """
    dt = dtparser.parse(iso_str)
    if dt.tzinfo is None:
        dt = KST.localize(dt)
    return dt.astimezone(KST)


def period_and_hero(gen_dt: datetime) -> tuple[str, str]:
    """생성시각(KST) 에서 (period_label, hero_title_line1) 을 계산.

    12시 이전이면 오전/굿모닝, 그 이후면 오후/굿이브닝.
    """
    hour = gen_dt.astimezone(KST).hour
    if hour <= MORNING_HOUR_CUTOFF:
        return "오전", "굿모닝"
    return "오후", "굿이브닝"


def format_generation_timestamp(gen_dt: datetime) -> str:
    """``YYYY.MM.DD HH:MM KST`` 포맷으로 렌더링."""
    return gen_dt.astimezone(KST).strftime("%Y.%m.%d %H:%M KST")


def format_published_display(published_dt: datetime, reference_dt: datetime) -> str:
    """기사 게시 시각을 렌더링용 문자열로.

    - 기준(생성시각) 과 같은 날짜면 ``HH:MM``.
    - 다른 날짜면 ``MM.DD HH:MM``.
    """
    p = published_dt.astimezone(KST)
    r = reference_dt.astimezone(KST)
    if p.year == r.year and p.month == r.month and p.day == r.day:
        return p.strftime("%H:%M")
    return p.strftime("%m.%d %H:%M")


def format_archive_name(gen_dt: datetime) -> str:
    """생성시각 기반 ``YYYY-MM-DD-HHMM.html`` 아카이브 파일명."""
    return gen_dt.astimezone(KST).strftime("%Y-%m-%d-%H%M") + ".html"


# ---------------------------------------------------------------------------
# 섹션 그룹핑 + must_know 추리기
# ---------------------------------------------------------------------------


_CATEGORY_TITLES: dict[str, str] = {
    "ai_news": "AI 뉴스",
    "general_news": "종합 뉴스",
}

# 섹션 순서: AI → 종합.
_CATEGORY_ORDER: tuple[str, ...] = ("ai_news", "general_news")


def _article_sort_key(article: dict[str, Any]) -> tuple[float, float]:
    """relevance_score desc, published_at desc (정렬 시 부호 반전)."""
    score = float(article.get("relevance_score") or 0.0)
    pub_raw = article.get("published_at") or ""
    pub_ts: float
    if pub_raw:
        try:
            pub_ts = _parse_kst(pub_raw).timestamp()
        except (ValueError, TypeError):
            pub_ts = 0.0
    else:
        pub_ts = 0.0
    return (-score, -pub_ts)


def build_sections(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """기사 리스트를 카테고리별 섹션으로 그룹핑.

    섹션 순서: AI 뉴스 → 종합 뉴스. 섹션 내부는 score desc, published_at desc.
    """
    by_cat: dict[str, list[dict[str, Any]]] = {cat: [] for cat in _CATEGORY_ORDER}
    for art in articles:
        cat = art.get("category")
        if cat in by_cat:
            by_cat[cat].append(art)
        else:
            # 미지 카테고리는 종합 뉴스에 담는다 (안전한 기본값).
            by_cat["general_news"].append(art)

    sections: list[dict[str, Any]] = []
    for cat in _CATEGORY_ORDER:
        arts = sorted(by_cat[cat], key=_article_sort_key)
        sections.append({"title": _CATEGORY_TITLES[cat], "articles": arts})
    return sections


def pick_must_know(articles: list[dict[str, Any]], *, top_n: int = 5) -> list[dict[str, Any]]:
    """``is_must_know==True`` 기사 중 score desc 상위 ``top_n`` 건."""
    filtered = [a for a in articles if a.get("is_must_know")]
    return sorted(filtered, key=_article_sort_key)[:top_n]


# ---------------------------------------------------------------------------
# Jinja 렌더링
# ---------------------------------------------------------------------------


def _build_env(template_path: str) -> Environment:
    template_file = Path(template_path)
    loader = FileSystemLoader(str(template_file.parent) or ".")
    env = Environment(
        loader=loader,
        autoescape=select_autoescape(enabled_extensions=("html", "j2", "html.j2"), default=True),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env


def _prepare_articles(
    articles: list[dict[str, Any]], reference_dt: datetime
) -> list[dict[str, Any]]:
    """렌더링용 사본에 ``published_at_display`` 와 안전한 기본값을 주입."""
    prepared: list[dict[str, Any]] = []
    for art in articles:
        copy = dict(art)
        pub_raw = copy.get("published_at") or ""
        if pub_raw:
            try:
                pub_dt = _parse_kst(pub_raw)
                copy["published_at_display"] = format_published_display(
                    pub_dt, reference_dt
                )
            except (ValueError, TypeError):
                copy["published_at_display"] = pub_raw
        else:
            copy["published_at_display"] = ""
        copy.setdefault("keywords", [])
        copy.setdefault("extraction_reason", "")
        copy.setdefault("ai_summary", "")
        copy.setdefault("relevance_score", 0.0)
        prepared.append(copy)
    return prepared


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------


def render(
    analyzed_path: str = ANALYZED_JSON_PATH,
    template_path: str = DEFAULT_TEMPLATE_PATH,
    output_path: str = OUTPUT_HTML_PATH,
    archive_dir: str = ARCHIVE_DIR,
) -> dict[str, Any]:
    """analyzed.json 을 읽어 HTML 템플릿을 렌더, 출력과 아카이브 사본을 기록.

    Returns:
        dict: ``html_path``, ``archive_path``, ``issue_number``, ``article_count``.
    """
    analyzed = json.loads(Path(analyzed_path).read_text(encoding="utf-8"))

    issue_number = int(analyzed.get("issue_number") or 0)
    gen_ts_raw = analyzed.get("generation_timestamp")
    if not gen_ts_raw:
        raise ValueError("analyzed.json 에 generation_timestamp 가 없습니다.")
    gen_dt = _parse_kst(gen_ts_raw)

    articles: list[dict[str, Any]] = list(analyzed.get("articles") or [])
    trend_hashtags: list[str] = list(analyzed.get("trend_hashtags") or [])

    # 명시적 period 가 analyzed.json 에 있으면 그걸 우선. 없으면 시각으로 판단.
    # 수동 실행이 오후 시각에 '오전' 브리핑을 트리거해도 헤더가 올바르게 나오도록.
    explicit_period = analyzed.get("period")
    if explicit_period in ("오전", "오후"):
        period_label = explicit_period
        hero_line1 = "굿모닝" if explicit_period == "오전" else "굿이브닝"
    else:
        period_label, hero_line1 = period_and_hero(gen_dt)

    must_know_raw = pick_must_know(articles)
    sections_raw = build_sections(articles)

    # 각 기사에 published_at_display 주입.
    must_know = _prepare_articles(must_know_raw, reference_dt=gen_dt)
    sections = [
        {
            "title": s["title"],
            "articles": _prepare_articles(s["articles"], reference_dt=gen_dt),
        }
        for s in sections_raw
    ]

    env = _build_env(template_path)
    template = env.get_template(Path(template_path).name)
    html = template.render(
        issue_number=issue_number,
        generation_timestamp=format_generation_timestamp(gen_dt),
        period_label=period_label,
        hero_title_line1=hero_line1,
        hero_title_line2="데일리 뉴스",
        trend_hashtags=trend_hashtags[:8],
        must_know=must_know,
        sections=sections,
        rss_sources=[feed.name for feed in RSS_FEEDS],
    )

    # 출력 경로.
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    # 아카이브.
    archive_path = Path(archive_dir) / format_archive_name(gen_dt)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(out_path, archive_path)

    total_articles = sum(len(s["articles"]) for s in sections)

    logger.info(
        "rendered %s (articles=%d, must_know=%d, issue=%d), archived to %s",
        out_path,
        total_articles,
        len(must_know),
        issue_number,
        archive_path,
    )

    return {
        "html_path": str(out_path),
        "archive_path": str(archive_path),
        "issue_number": issue_number,
        "article_count": total_articles,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    result = render()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
