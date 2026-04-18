"""카카오톡 메시지 빌더 (순수 텍스트 생성기).

- ``build_success_message`` / ``build_failure_message`` 는 Seed 의 템플릿과
  정확히 일치하는 문자열을 반환한다. 네트워크 호출/ MCP 호출은 하지 않는다.
- ``top3_from_analyzed`` 는 ``analyzed.json`` 의 ``articles`` 에서 top3 제목을
  추출한다 (must_know 우선, 부족하면 regular 에서 score desc 로 보충).
- CLI: ``python -m pipeline.notify success`` | ``failure`` 는 ``state/*.json``
  을 읽어 메시지를 stdout 으로 출력.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytz
from dateutil import parser as dtparser

from pipeline.config import (
    ANALYZED_JSON_PATH,
    DEPLOY_URL,
    KST_TZ_NAME,
    MAX_RETRY,
    STATE_JSON_PATH,
)
from pipeline.state import PipelineState, load_state

logger = logging.getLogger(__name__)

KST = pytz.timezone(KST_TZ_NAME)

# 실패 메시지 사유 최대 길이.
ERROR_REASON_MAX_CHARS: int = 200
ERROR_REASON_ELLIPSIS: str = "…"


# ---------------------------------------------------------------------------
# 유틸
# ---------------------------------------------------------------------------


def _parse_kst(iso_str: str) -> datetime:
    """ISO-8601 문자열을 KST-aware ``datetime`` 으로 파싱."""
    dt = dtparser.parse(iso_str)
    if dt.tzinfo is None:
        dt = KST.localize(dt)
    return dt.astimezone(KST)


def _format_date(dt: datetime) -> str:
    """``YYYY.MM.DD`` 로 포맷."""
    return dt.astimezone(KST).strftime("%Y.%m.%d")


def _format_datetime(dt: datetime) -> str:
    """``YYYY.MM.DD HH:MM KST`` 로 포맷."""
    return dt.astimezone(KST).strftime("%Y.%m.%d %H:%M KST")


def _truncate_reason(reason: str, limit: int = ERROR_REASON_MAX_CHARS) -> str:
    """사유 길이가 ``limit`` 초과면 말줄임표를 붙여 자른다.

    - ``limit`` 글자까지 허용, 초과 시 ``limit - 1`` 글자 + ``…``.
    - None/빈 문자열은 빈 문자열로.
    """
    if not reason:
        return ""
    if len(reason) <= limit:
        return reason
    return reason[: max(0, limit - 1)] + ERROR_REASON_ELLIPSIS


# ---------------------------------------------------------------------------
# top3 추출
# ---------------------------------------------------------------------------


def _score_desc_key(article: dict[str, Any]) -> float:
    """정렬용 키 (score desc)."""
    try:
        return -float(article.get("relevance_score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def top3_from_analyzed(analyzed: dict[str, Any]) -> list[str]:
    """top3 기사 제목 리스트 반환.

    - 우선 ``is_must_know=True`` 기사에서 ``relevance_score`` desc 상위.
    - 3건 미만이면 나머지 기사에서 score desc 로 보충.
    - 기사가 3건 미만이면 실제 개수만 반환 (최대 3).
    - 잘못된 입력에도 예외를 던지지 않는다.
    """
    if not isinstance(analyzed, dict):
        return []
    articles_raw = analyzed.get("articles")
    if not isinstance(articles_raw, list):
        return []

    articles: list[dict[str, Any]] = [
        a for a in articles_raw if isinstance(a, dict) and a.get("title")
    ]

    must_know = sorted(
        (a for a in articles if a.get("is_must_know")), key=_score_desc_key
    )
    regular = sorted(
        (a for a in articles if not a.get("is_must_know")), key=_score_desc_key
    )

    picked: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for art in must_know + regular:
        art_id = str(art.get("article_id") or art.get("title") or id(art))
        if art_id in seen_ids:
            continue
        seen_ids.add(art_id)
        picked.append(art)
        if len(picked) >= 3:
            break

    return [str(a.get("title") or "") for a in picked]


# ---------------------------------------------------------------------------
# 메시지 빌더
# ---------------------------------------------------------------------------


def build_success_message(
    generation_timestamp: str,
    period_label: str,
    top_titles: list[str],
    total_count: int,
    deploy_url: str = DEPLOY_URL,
) -> str:
    """카카오톡 성공 메시지를 Seed 템플릿 그대로 생성.

    템플릿::

        📰 데일리 뉴스 · {YYYY.MM.DD} · {오전|오후}

        1. {top1}
        2. {top2}
        3. {top3}

        총 {N}건 · 전체 보기
        {deploy_url}

    top_titles 가 3건 미만이면 있는 만큼만 번호를 매긴다 (``3. None`` 금지).
    """
    gen_dt = _parse_kst(generation_timestamp)
    date_str = _format_date(gen_dt)
    header = f"📰 데일리 뉴스 · {date_str} · {period_label}"

    numbered_lines = [
        f"{idx}. {title}" for idx, title in enumerate(top_titles[:3], start=1) if title
    ]

    footer_line1 = f"총 {int(total_count)}건 · 전체 보기"
    footer_line2 = str(deploy_url).rstrip()

    blocks: list[str] = [header]
    if numbered_lines:
        blocks.append("\n".join(numbered_lines))
    blocks.append("\n".join([footer_line1, footer_line2]))

    message = "\n\n".join(blocks)
    # 줄 뒤 공백 제거 (LF 기준).
    cleaned = "\n".join(line.rstrip() for line in message.split("\n"))
    return cleaned


def build_failure_message(
    state: PipelineState,
    now_kst: datetime | None = None,
) -> str:
    """카카오톡 실패 메시지를 Seed 템플릿 그대로 생성.

    템플릿::

        ⚠️ 뉴스 생성 실패

        시각: {YYYY.MM.DD HH:MM KST}
        단계: {failed_stage}
        사유: {error_reason_truncated}
        재시도: {retry_count}/{MAX_RETRY}
        다음 스케줄: {next_run_display}
    """
    now = now_kst if now_kst is not None else datetime.now(KST)
    now_str = _format_datetime(now)
    failed_stage = state.failed_stage or "-"
    reason_str = _truncate_reason(state.error_reason or "")
    if not reason_str:
        reason_str = "-"

    if state.next_run_time:
        try:
            next_dt = _parse_kst(state.next_run_time)
            next_run_display = _format_datetime(next_dt)
        except (ValueError, TypeError):
            next_run_display = state.next_run_time
    else:
        next_run_display = "-"

    lines = [
        "⚠️ 뉴스 생성 실패",
        "",
        f"시각: {now_str}",
        f"단계: {failed_stage}",
        f"사유: {reason_str}",
        f"재시도: {int(state.retry_count)}/{MAX_RETRY}",
        f"다음 스케줄: {next_run_display}",
    ]
    cleaned = "\n".join(line.rstrip() for line in lines)
    return cleaned


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_success(
    state_path: str = STATE_JSON_PATH,
    analyzed_path: str = ANALYZED_JSON_PATH,
) -> int:
    state = load_state(state_path)
    analyzed_file = Path(analyzed_path)
    if not analyzed_file.exists():
        print(
            f"analyzed.json 을 찾을 수 없습니다: {analyzed_file}",
            file=sys.stderr,
        )
        return 1
    analyzed = json.loads(analyzed_file.read_text(encoding="utf-8"))

    gen_ts = (
        state.current_generation_timestamp
        or analyzed.get("generation_timestamp")
        or datetime.now(KST).isoformat(timespec="seconds")
    )
    period = state.current_period
    if not period:
        try:
            gen_dt = _parse_kst(gen_ts)
            period = "오전" if gen_dt.hour < 12 else "오후"
        except (ValueError, TypeError):
            period = "오전"

    articles = analyzed.get("articles") or []
    total_count = len(articles)
    top_titles = top3_from_analyzed(analyzed)

    message = build_success_message(
        generation_timestamp=gen_ts,
        period_label=period,
        top_titles=top_titles,
        total_count=total_count,
        deploy_url=state.deploy_url or DEPLOY_URL,
    )
    print(message)
    return 0


def _cmd_failure(state_path: str = STATE_JSON_PATH) -> int:
    state = load_state(state_path)
    message = build_failure_message(state)
    print(message)
    return 0


def _main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print(
            "usage: python -m pipeline.notify {success|failure}",
            file=sys.stderr,
        )
        return 2
    cmd = args[0]
    if cmd == "success":
        return _cmd_success()
    if cmd == "failure":
        return _cmd_failure()
    print(f"unknown command: {cmd}", file=sys.stderr)
    print(
        "usage: python -m pipeline.notify {success|failure}", file=sys.stderr
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
