"""파이프라인 상태 JSON 관리.

``state/state.json`` 를 읽고/쓰고 단계 전이를 기록한다.
- 시각은 전부 timezone-aware ``datetime`` (Asia/Seoul) 이며, JSON 에는 ISO-8601
  오프셋 포함 형식으로 저장한다.
- ``issue_number`` 는 렌더 성공 시 ``increment_issue_number`` 를 통해서만 증가.
- ``default_state`` 는 파일이 존재하지 않을 때(최초 실행) 반환하는 초기값.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pytz

from pipeline.config import DEPLOY_URL, KST_TZ_NAME, STATE_JSON_PATH

logger = logging.getLogger(__name__)

KST = pytz.timezone(KST_TZ_NAME)

# 스케줄 트리거 KST 시각 (hour, minute).
SCHEDULE_HOURS: tuple[tuple[int, int], ...] = ((7, 0), (18, 0))


# ---------------------------------------------------------------------------
# 데이터 클래스
# ---------------------------------------------------------------------------


@dataclass
class PipelineState:
    issue_number: int
    pipeline_status: str
    last_success_at: str | None
    last_attempt_at: str | None
    failed_stage: str | None
    error_reason: str | None
    retry_count: int
    next_run_time: str | None
    deploy_url: str
    current_period: str | None
    current_generation_timestamp: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


# ---------------------------------------------------------------------------
# 순수 시간 유틸
# ---------------------------------------------------------------------------


def _now_kst() -> datetime:
    """현재 시각(KST, tz-aware)."""
    return datetime.now(KST)


def _iso(dt: datetime) -> str:
    """KST tz-aware ``datetime`` 을 초 단위 ISO-8601 (오프셋 포함) 으로."""
    return dt.astimezone(KST).isoformat(timespec="seconds")


def current_period(now_kst: datetime) -> str:
    """오전/오후 라벨. 12시 이후는 오후."""
    hour = now_kst.astimezone(KST).hour
    return "오전" if hour < 12 else "오후"


def compute_next_run_time(now_kst: datetime) -> str:
    """다음 스케줄(07:00 / 18:00 KST) 을 ISO-8601 문자열로.

    - ``now < 07:00`` → 오늘 07:00
    - ``07:00 <= now < 18:00`` → 오늘 18:00
    - ``18:00 <= now`` → 내일 07:00
    """
    now = now_kst.astimezone(KST)
    today = now.date()
    # 당일 07:00, 18:00 후보 생성.
    candidates = [
        KST.localize(datetime(today.year, today.month, today.day, h, m))
        for (h, m) in SCHEDULE_HOURS
    ]
    for candidate in candidates:
        if candidate > now:
            return _iso(candidate)
    # 오늘 남은 후보가 없으면 다음 날 첫 번째 스케줄.
    tomorrow = today + timedelta(days=1)
    next_h, next_m = SCHEDULE_HOURS[0]
    next_dt = KST.localize(
        datetime(tomorrow.year, tomorrow.month, tomorrow.day, next_h, next_m)
    )
    return _iso(next_dt)


# ---------------------------------------------------------------------------
# 상태 생성 / 로드 / 저장
# ---------------------------------------------------------------------------


def default_state() -> PipelineState:
    """첫 실행용 기본 상태."""
    return PipelineState(
        issue_number=1,
        pipeline_status="pending",
        last_success_at=None,
        last_attempt_at=None,
        failed_stage=None,
        error_reason=None,
        retry_count=0,
        next_run_time=None,
        deploy_url=DEPLOY_URL,
        current_period=None,
        current_generation_timestamp=None,
    )


_ALLOWED_FIELDS: frozenset[str] = frozenset(
    {
        "issue_number",
        "pipeline_status",
        "last_success_at",
        "last_attempt_at",
        "failed_stage",
        "error_reason",
        "retry_count",
        "next_run_time",
        "deploy_url",
        "current_period",
        "current_generation_timestamp",
    }
)


def load_state(path: str = STATE_JSON_PATH) -> PipelineState:
    """상태 JSON 을 로드. 파일이 없으면 ``default_state()`` 반환."""
    p = Path(path)
    if not p.exists():
        logger.info("상태 파일 없음 → default_state 사용: %s", p)
        return default_state()

    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("상태 파일 파싱 실패 (%s) → default_state 사용: %s", p, exc)
        return default_state()

    base = default_state()
    data: dict[str, object] = base.to_dict()
    if isinstance(raw, dict):
        for key, value in raw.items():
            if key in _ALLOWED_FIELDS:
                data[key] = value
    return PipelineState(**data)  # type: ignore[arg-type]


def save_state(state: PipelineState, path: str = STATE_JSON_PATH) -> None:
    """상태 JSON 을 저장 (UTF-8, 들여쓰기 2칸)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(state.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# 단계 전이
# ---------------------------------------------------------------------------


_VALID_STAGES: frozenset[str] = frozenset(
    {"collecting", "analyzing", "generating", "deploying", "notifying"}
)


def mark_stage(state: PipelineState, stage: str) -> None:
    """단계 진입 기록.

    - ``pipeline_status`` 를 단계명으로 설정.
    - ``last_attempt_at`` 을 현재 KST 로 갱신.
    - 이전 실패 흔적(``failed_stage``, ``error_reason``) 초기화.
    """
    state.pipeline_status = stage
    state.last_attempt_at = _iso(_now_kst())
    state.failed_stage = None
    state.error_reason = None


def mark_failure(state: PipelineState, stage: str, reason: str) -> None:
    """단계 실패 기록.

    - ``pipeline_status='failed'``, ``failed_stage=stage``, ``error_reason=reason``.
    - ``retry_count`` 1 증가.
    - ``last_attempt_at`` 도 갱신.
    """
    state.pipeline_status = "failed"
    state.failed_stage = stage
    state.error_reason = reason
    state.retry_count += 1
    state.last_attempt_at = _iso(_now_kst())


def mark_success(state: PipelineState) -> None:
    """파이프라인 성공 기록.

    - ``pipeline_status='completed'``
    - ``last_success_at`` = 현재 KST.
    - ``retry_count=0``, 실패 필드 clear.
    - ``last_attempt_at`` 도 갱신.
    """
    now = _iso(_now_kst())
    state.pipeline_status = "completed"
    state.last_success_at = now
    state.last_attempt_at = now
    state.retry_count = 0
    state.failed_stage = None
    state.error_reason = None


def increment_issue_number(state: PipelineState) -> int:
    """``issue_number`` 를 1 증가시키고 새 값을 반환."""
    state.issue_number += 1
    return state.issue_number


# ---------------------------------------------------------------------------
# CLI (``python -m pipeline.state show``)
# ---------------------------------------------------------------------------


def _cmd_show(path: str) -> int:
    state = load_state(path)
    print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = list(argv if argv is not None else sys.argv[1:])
    cmd = args[0] if args else "show"
    path = args[1] if len(args) > 1 else STATE_JSON_PATH
    if cmd == "show":
        return _cmd_show(path)
    print(f"unknown command: {cmd}", file=sys.stderr)
    print("usage: python -m pipeline.state show [path]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
