"""파이프라인 오케스트레이터 (subcommand CLI).

Remote Agent 는 ``python -m pipeline.run <subcommand>`` 형태로 각 단계를 호출한다.
재시도 로직은 Agent 의 bash 루프가 담당하므로 각 서브커맨드는 한 번만 실행하고
성공 시 exit 0, 실패 시 ``state`` 에 실패를 기록하고 exit 1 로 종료한다.

- ``stdout`` 는 Agent 가 파싱할 JSON/메시지 텍스트만 출력.
- ``stderr`` 에는 ``[pipeline.run] ...`` 형태의 사람이 읽을 로그를 출력.

Subcommands:
    collect            - RSS 수집 (state/candidates.json 기록)
    render             - HTML 렌더링 (docs/index.html + archive)
    notify-success     - 성공 카카오톡 메시지 텍스트 생성
    notify-failure     - 실패 카카오톡 메시지 텍스트 생성
    mark-stage         - state.pipeline_status 갱신
    mark-failure       - state 에 단계 실패 기록 (retry_count 증가)
    mark-success       - state.pipeline_status='completed', error 필드 clear
    prepare-run        - 새 스케줄 시작 (issue_number++, retry_count=0)
    state              - 현재 state JSON 출력
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytz

from pipeline import collect as collect_mod
from pipeline import notify as notify_mod
from pipeline import render as render_mod
from pipeline import state as state_mod
from pipeline.config import (
    ANALYZED_JSON_PATH,
    CANDIDATES_JSON_PATH,
    DEPLOY_URL,
    KST_TZ_NAME,
    MAX_RETRY,
    OUTPUT_HTML_PATH,
    STATE_JSON_PATH,
)

logger = logging.getLogger(__name__)

KST = pytz.timezone(KST_TZ_NAME)


# ---------------------------------------------------------------------------
# 유틸
# ---------------------------------------------------------------------------


def _log(msg: str) -> None:
    """사람이 읽을 로그를 stderr 로 출력 (stdout 은 JSON/메시지 전용)."""
    print(f"[pipeline.run] {msg}", file=sys.stderr, flush=True)


def _print_json(data: Any) -> None:
    """stdout 으로 JSON 출력 (UTF-8, 들여쓰기 2칸)."""
    print(json.dumps(data, ensure_ascii=False, indent=2), flush=True)


def _now_kst() -> datetime:
    return datetime.now(KST)


def _iso_kst(dt: datetime) -> str:
    return dt.astimezone(KST).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 각 서브커맨드 핸들러
# ---------------------------------------------------------------------------


def cmd_collect(args: argparse.Namespace) -> int:
    state = state_mod.load_state(args.state_path)
    state_mod.mark_stage(state, "collecting")
    state_mod.save_state(state, args.state_path)
    _log("stage=collecting 시작")
    try:
        summary = collect_mod.collect(args.candidates_path)
    except Exception as exc:  # noqa: BLE001 - 모든 예외를 실패로 기록
        state_mod.mark_failure(state, "collecting", repr(exc))
        state_mod.save_state(state, args.state_path)
        _log(f"collect 실패: {exc!r} (retry_count={state.retry_count})")
        return 1

    # 성공 시 status 는 'collecting' 유지 — 다음에 agent 가 mark-stage analyzing 호출.
    state_mod.save_state(state, args.state_path)

    articles = summary.get("articles") or []
    source_stats = summary.get("source_stats") or {}
    _log(f"collected {len(articles)} articles from {len(source_stats)} sources")
    _print_json(source_stats)
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    state = state_mod.load_state(args.state_path)
    state_mod.mark_stage(state, "generating")
    state_mod.save_state(state, args.state_path)
    _log("stage=generating 시작")
    try:
        result = render_mod.render(
            analyzed_path=args.analyzed_path,
            output_path=args.output_path,
        )
    except Exception as exc:  # noqa: BLE001
        state_mod.mark_failure(state, "generating", repr(exc))
        state_mod.save_state(state, args.state_path)
        _log(f"render 실패: {exc!r} (retry_count={state.retry_count})")
        return 1

    state_mod.save_state(state, args.state_path)
    _log(
        f"rendered {result.get('html_path')} "
        f"({result.get('article_count')} articles)"
    )
    _print_json(result)
    return 0


def cmd_notify_success(args: argparse.Namespace) -> int:
    state = state_mod.load_state(args.state_path)
    analyzed_file = Path(args.analyzed_path)
    if not analyzed_file.exists():
        _log(f"ERROR: analyzed.json 을 찾을 수 없습니다: {analyzed_file}")
        return 1
    try:
        analyzed = json.loads(analyzed_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _log(f"ERROR: analyzed.json 파싱 실패: {exc!r}")
        return 1

    top_titles = notify_mod.top3_from_analyzed(analyzed)
    total = len(analyzed.get("articles") or [])

    gen_ts = (
        state.current_generation_timestamp
        or analyzed.get("generation_timestamp")
        or _iso_kst(_now_kst())
    )
    period = state.current_period
    if not period:
        # current_period 가 비어있으면 생성시각 기준으로 유도.
        try:
            period = state_mod.current_period(
                datetime.fromisoformat(gen_ts) if gen_ts else _now_kst()
            )
        except (ValueError, TypeError):
            period = state_mod.current_period(_now_kst())

    message = notify_mod.build_success_message(
        generation_timestamp=gen_ts,
        period_label=period,
        top_titles=top_titles,
        total_count=total,
        deploy_url=state.deploy_url or DEPLOY_URL,
    )
    _log(f"notify-success: period={period} total={total} top={len(top_titles)}")
    print(message, flush=True)
    return 0


def cmd_notify_failure(args: argparse.Namespace) -> int:
    state = state_mod.load_state(args.state_path)
    message = notify_mod.build_failure_message(state)
    _log(
        f"notify-failure: stage={state.failed_stage} "
        f"retry={state.retry_count}/{MAX_RETRY}"
    )
    print(message, flush=True)
    return 0


def cmd_mark_stage(args: argparse.Namespace) -> int:
    state = state_mod.load_state(args.state_path)
    state_mod.mark_stage(state, args.stage)
    state_mod.save_state(state, args.state_path)
    _log(f"mark-stage: {args.stage}")
    return 0


def cmd_mark_failure(args: argparse.Namespace) -> int:
    state = state_mod.load_state(args.state_path)
    state_mod.mark_failure(state, args.stage, args.reason)
    state_mod.save_state(state, args.state_path)
    _log(
        f"mark-failure: stage={args.stage} "
        f"retry_count={state.retry_count}/{MAX_RETRY}"
    )
    return 0


def cmd_mark_success(args: argparse.Namespace) -> int:
    state = state_mod.load_state(args.state_path)
    state_mod.mark_success(state)
    state_mod.save_state(state, args.state_path)
    _log(
        f"mark-success: issue_number={state.issue_number} "
        f"last_success_at={state.last_success_at}"
    )
    return 0


def cmd_prepare_run(args: argparse.Namespace) -> int:
    """새 스케줄(07:00/18:00) 시작: issue_number++, retry_count=0, next_run_time 계산."""
    state = state_mod.load_state(args.state_path)

    in_progress = {"collecting", "analyzing", "generating", "deploying", "notifying"}
    if state.pipeline_status in in_progress:
        if state.retry_count >= MAX_RETRY:
            _log(
                f"ERROR: retry budget exhausted "
                f"(status={state.pipeline_status}, retry={state.retry_count})"
            )
            return 1
        _log(
            f"WARNING: overwriting in-progress state "
            f"(was {state.pipeline_status}, retry={state.retry_count})"
        )

    # 새 스케줄 시작 → retry 초기화, 실패 흔적 clear, issue_number 증가.
    new_issue = state_mod.increment_issue_number(state)
    state.retry_count = 0
    state.failed_stage = None
    state.error_reason = None
    state.current_period = args.period

    now = _now_kst()
    state.current_generation_timestamp = _iso_kst(now)
    # 다음 스케줄은 '이 run 이후' 의 것을 노려야 하므로 1분 뒤 기준으로 계산.
    state.next_run_time = state_mod.compute_next_run_time(now + timedelta(minutes=1))

    # 상태는 '아직 어느 단계도 시작 전' 이므로 'pending' 으로 명시.
    state.pipeline_status = "pending"

    state_mod.save_state(state, args.state_path)

    _log(
        f"prepare-run: issue={new_issue} period={args.period} "
        f"next_run={state.next_run_time}"
    )
    _print_json(
        {
            "issue_number": new_issue,
            "period": args.period,
            "generation_timestamp": state.current_generation_timestamp,
            "next_run_time": state.next_run_time,
        }
    )
    return 0


def cmd_validate_analyzed(args: argparse.Namespace) -> int:
    """analyzed.json 의 모든 기사가 candidates.json 에 있는지 검증.

    LLM 이 candidates 밖 기사(과거 커밋·외부 소스)를 analyzed 에 끌어오는 것을
    차단. 불일치 1건이라도 있으면 FAILED_STAGE=analyzing 으로 기록 후 exit 1.
    """
    state = state_mod.load_state(args.state_path)

    cand_path = Path(args.candidates_path)
    ana_path = Path(args.analyzed_path)
    if not cand_path.exists() or not ana_path.exists():
        reason = (
            f"validate-analyzed 대상 파일 누락: "
            f"candidates={cand_path.exists()}, analyzed={ana_path.exists()}"
        )
        state_mod.mark_failure(state, "analyzing", reason)
        state_mod.save_state(state, args.state_path)
        _log(f"ERROR: {reason}")
        return 1

    try:
        candidates = json.loads(cand_path.read_text(encoding="utf-8"))
        analyzed = json.loads(ana_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        reason = f"validate-analyzed 파싱 실패: {exc!r}"
        state_mod.mark_failure(state, "analyzing", reason)
        state_mod.save_state(state, args.state_path)
        _log(f"ERROR: {reason}")
        return 1

    cand_by_id: dict[str, dict[str, Any]] = {
        a["article_id"]: a
        for a in (candidates.get("articles") or [])
        if a.get("article_id")
    }
    cand_ids = set(cand_by_id)
    ana_articles = analyzed.get("articles") or []

    foreign: list[str] = []
    missing_id: list[str] = []
    category_mismatch: list[str] = []
    for art in ana_articles:
        aid = art.get("article_id")
        if not aid:
            missing_id.append(art.get("title") or "<no title>")
            continue
        if aid not in cand_ids:
            foreign.append(f"{aid}:{art.get('title') or '<no title>'}")
            continue
        # v21: candidates 의 category 를 agent 가 덮어쓰는 것을 차단.
        cand_cat = cand_by_id[aid].get("category")
        ana_cat = art.get("category")
        if cand_cat and ana_cat and cand_cat != ana_cat:
            category_mismatch.append(
                f"{aid}:{cand_cat}→{ana_cat}"
            )

    if foreign or missing_id or category_mismatch:
        details = []
        if foreign:
            details.append(
                f"candidates 밖 기사 {len(foreign)}건 (샘플: {foreign[:3]})"
            )
        if missing_id:
            details.append(
                f"article_id 누락 기사 {len(missing_id)}건 (샘플: {missing_id[:3]})"
            )
        if category_mismatch:
            details.append(
                f"category 변경된 기사 {len(category_mismatch)}건 "
                f"(샘플: {category_mismatch[:3]})"
            )
        reason = "validate-analyzed 실패 — " + " / ".join(details)
        state_mod.mark_failure(state, "analyzing", reason)
        state_mod.save_state(state, args.state_path)
        _log(f"ERROR: {reason}")
        _print_json(
            {
                "valid": False,
                "foreign_count": len(foreign),
                "missing_id_count": len(missing_id),
                "category_mismatch_count": len(category_mismatch),
                "foreign_samples": foreign[:5],
                "category_mismatch_samples": category_mismatch[:5],
            }
        )
        return 1

    _log(
        f"validate-analyzed OK: {len(ana_articles)} 건 모두 candidates 매칭"
    )
    _print_json(
        {
            "valid": True,
            "count": len(ana_articles),
        }
    )
    return 0


def cmd_state(args: argparse.Namespace) -> int:
    state = state_mod.load_state(args.state_path)
    _print_json(state.to_dict())
    return 0


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.run",
        description="데일리 뉴스 파이프라인 오케스트레이터 (서브커맨드 CLI)",
    )
    parser.add_argument(
        "--state-path",
        default=STATE_JSON_PATH,
        help="state.json 경로 (기본: state/state.json)",
    )

    sub = parser.add_subparsers(dest="command", required=True, metavar="<subcommand>")

    # collect
    sp_collect = sub.add_parser("collect", help="RSS 수집 → candidates.json")
    sp_collect.add_argument(
        "--candidates-path",
        default=CANDIDATES_JSON_PATH,
        help="candidates.json 출력 경로",
    )
    sp_collect.set_defaults(func=cmd_collect)

    # render
    sp_render = sub.add_parser("render", help="analyzed.json → docs/index.html")
    sp_render.add_argument(
        "--analyzed-path",
        default=ANALYZED_JSON_PATH,
        help="analyzed.json 입력 경로",
    )
    sp_render.add_argument(
        "--output-path",
        default=OUTPUT_HTML_PATH,
        help="HTML 출력 경로",
    )
    sp_render.set_defaults(func=cmd_render)

    # notify-success
    sp_ns = sub.add_parser(
        "notify-success", help="성공 카카오톡 메시지 텍스트 출력 (stdout)"
    )
    sp_ns.add_argument(
        "--analyzed-path",
        default=ANALYZED_JSON_PATH,
        help="analyzed.json 입력 경로",
    )
    sp_ns.set_defaults(func=cmd_notify_success)

    # notify-failure
    sp_nf = sub.add_parser(
        "notify-failure", help="실패 카카오톡 메시지 텍스트 출력 (stdout)"
    )
    sp_nf.set_defaults(func=cmd_notify_failure)

    # mark-stage
    sp_ms = sub.add_parser(
        "mark-stage", help="state.pipeline_status 갱신 (단계 진입 기록)"
    )
    sp_ms.add_argument(
        "--stage",
        required=True,
        choices=["collecting", "analyzing", "generating", "deploying", "notifying"],
        help="진입할 단계 이름",
    )
    sp_ms.set_defaults(func=cmd_mark_stage)

    # mark-failure
    sp_mf = sub.add_parser(
        "mark-failure", help="단계 실패 기록 (retry_count +1)"
    )
    sp_mf.add_argument(
        "--stage",
        required=True,
        help="실패한 단계 이름",
    )
    sp_mf.add_argument(
        "--reason",
        required=True,
        help="실패 사유 텍스트",
    )
    sp_mf.set_defaults(func=cmd_mark_failure)

    # mark-success
    sp_mk = sub.add_parser(
        "mark-success",
        help="파이프라인 성공 기록 (pipeline_status=completed, retry=0)",
    )
    sp_mk.set_defaults(func=cmd_mark_success)

    # prepare-run
    sp_pr = sub.add_parser(
        "prepare-run",
        help="새 스케줄 시작 (issue_number++, retry_count=0, next_run_time 계산)",
    )
    sp_pr.add_argument(
        "--period",
        required=True,
        choices=["오전", "오후"],
        help="현재 스케줄 라벨",
    )
    sp_pr.set_defaults(func=cmd_prepare_run)

    # validate-analyzed
    sp_va = sub.add_parser(
        "validate-analyzed",
        help="analyzed.json 이 candidates.json 밖 기사를 포함하는지 검증",
    )
    sp_va.add_argument(
        "--candidates-path",
        default=CANDIDATES_JSON_PATH,
        help="candidates.json 경로",
    )
    sp_va.add_argument(
        "--analyzed-path",
        default=ANALYZED_JSON_PATH,
        help="analyzed.json 경로",
    )
    sp_va.set_defaults(func=cmd_validate_analyzed)

    # state
    sp_st = sub.add_parser("state", help="현재 state JSON 을 stdout 으로 출력")
    sp_st.set_defaults(func=cmd_state)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
