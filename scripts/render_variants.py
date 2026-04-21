"""5가지 UI 디자인 시안을 state/analyzed.json 으로부터 렌더한다.

출력: docs/variants/{magazine, newspaper, brevity, terminal, reels, index}.html
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from pipeline.config import ANALYZED_JSON_PATH
from pipeline.render import (
    _parse_kst,
    _prepare_articles,
    build_sections,
    format_generation_timestamp,
    period_and_hero,
    pick_must_know,
)

TEMPLATE_DIR = Path("templates/variants")
OUT_DIR = Path("docs/variants")

VARIANTS: tuple[str, ...] = (
    "magazine",
    "newspaper",
    "brevity",
    "terminal",
    "reels",
)


def _build_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(
            enabled_extensions=("html", "j2", "html.j2"), default=True
        ),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _build_context(analyzed: dict[str, Any]) -> dict[str, Any]:
    issue_number = int(analyzed.get("issue_number") or 0)
    gen_ts_raw = analyzed.get("generation_timestamp") or ""
    if not gen_ts_raw:
        raise ValueError("analyzed.json 에 generation_timestamp 가 없습니다.")
    gen_dt = _parse_kst(gen_ts_raw)

    explicit_period = analyzed.get("period")
    if explicit_period in ("오전", "오후"):
        period_label = explicit_period
        hero_line1 = "굿모닝" if explicit_period == "오전" else "굿이브닝"
    else:
        period_label, hero_line1 = period_and_hero(gen_dt)

    articles = list(analyzed.get("articles") or [])
    trend = list(analyzed.get("trend_hashtags") or [])

    must_know_raw = pick_must_know(articles, top_n=13)
    sections_raw = build_sections(articles)

    must_know = _prepare_articles(must_know_raw, reference_dt=gen_dt)
    sections = [
        {
            "title": s["title"],
            "articles": _prepare_articles(s["articles"], reference_dt=gen_dt),
        }
        for s in sections_raw
    ]

    return {
        "issue_number": issue_number,
        "period_label": period_label,
        "hero_line1": hero_line1,
        "generation_timestamp": format_generation_timestamp(gen_dt),
        "trend_hashtags": trend,
        "must_know": must_know,
        "sections": sections,
        "all_count": sum(len(s["articles"]) for s in sections),
    }


def render_all() -> dict[str, str]:
    analyzed = json.loads(Path(ANALYZED_JSON_PATH).read_text(encoding="utf-8"))
    context = _build_context(analyzed)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    env = _build_env()

    written: dict[str, str] = {}
    for slug in VARIANTS:
        template = env.get_template(f"{slug}.html.j2")
        html = template.render(**context)
        out_path = OUT_DIR / f"{slug}.html"
        out_path.write_text(html, encoding="utf-8")
        written[slug] = str(out_path)

    # Gallery index
    index_template = env.get_template("index.html.j2")
    index_html = index_template.render(**context)
    index_path = OUT_DIR / "index.html"
    index_path.write_text(index_html, encoding="utf-8")
    written["index"] = str(index_path)

    return written


def _main() -> None:
    written = render_all()
    print(json.dumps(written, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()
