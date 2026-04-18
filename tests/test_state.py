"""pipeline.state 단위 테스트."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
import pytz

from pipeline import state as state_mod
from pipeline.config import DEPLOY_URL, KST_TZ_NAME
from pipeline.state import (
    PipelineState,
    compute_next_run_time,
    current_period,
    default_state,
    increment_issue_number,
    load_state,
    mark_failure,
    mark_stage,
    mark_success,
    save_state,
)

KST = pytz.timezone(KST_TZ_NAME)


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def _kst(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return KST.localize(datetime(year, month, day, hour, minute))


# ---------------------------------------------------------------------------
# 테스트
# ---------------------------------------------------------------------------


def test_default_state_shape() -> None:
    st = default_state()
    assert st.issue_number == 1
    assert st.pipeline_status == "pending"
    assert st.last_success_at is None
    assert st.last_attempt_at is None
    assert st.failed_stage is None
    assert st.error_reason is None
    assert st.retry_count == 0
    assert st.next_run_time is None
    assert st.deploy_url == DEPLOY_URL
    assert st.current_period is None
    assert st.current_generation_timestamp is None


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    original = default_state()
    original.issue_number = 42
    original.pipeline_status = "completed"
    original.last_success_at = "2026-04-19T07:02:00+09:00"
    original.last_attempt_at = "2026-04-19T07:01:05+09:00"
    original.retry_count = 0
    original.next_run_time = "2026-04-19T18:00:00+09:00"
    original.current_period = "오전"
    original.current_generation_timestamp = "2026-04-19T07:02:00+09:00"

    save_state(original, str(path))
    assert path.exists()

    loaded = load_state(str(path))
    assert loaded == original

    # 파일에 실제로 들어간 JSON 도 검증.
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["issue_number"] == 42
    assert data["pipeline_status"] == "completed"
    assert data["current_period"] == "오전"


def test_load_missing_file_returns_default(tmp_path: Path) -> None:
    path = tmp_path / "nope.json"
    assert not path.exists()
    loaded = load_state(str(path))
    assert loaded == default_state()


def test_mark_stage_updates_status_and_clears_error(monkeypatch) -> None:
    fake_now = _kst(2026, 4, 19, 7, 1)
    monkeypatch.setattr(state_mod, "_now_kst", lambda: fake_now)

    st = default_state()
    st.failed_stage = "collecting"
    st.error_reason = "timeout"

    mark_stage(st, "analyzing")

    assert st.pipeline_status == "analyzing"
    assert st.failed_stage is None
    assert st.error_reason is None
    assert st.last_attempt_at == "2026-04-19T07:01:00+09:00"


def test_mark_failure_sets_fields_and_increments_retry(monkeypatch) -> None:
    fake_now = _kst(2026, 4, 19, 7, 5)
    monkeypatch.setattr(state_mod, "_now_kst", lambda: fake_now)

    st = default_state()
    assert st.retry_count == 0

    mark_failure(st, "collecting", "RSS timeout")
    assert st.pipeline_status == "failed"
    assert st.failed_stage == "collecting"
    assert st.error_reason == "RSS timeout"
    assert st.retry_count == 1
    assert st.last_attempt_at == "2026-04-19T07:05:00+09:00"

    mark_failure(st, "collecting", "RSS timeout")
    assert st.retry_count == 2


def test_mark_success_resets_error_fields_and_sets_timestamp(monkeypatch) -> None:
    fake_now = _kst(2026, 4, 19, 7, 2)
    monkeypatch.setattr(state_mod, "_now_kst", lambda: fake_now)

    st = default_state()
    st.pipeline_status = "failed"
    st.failed_stage = "collecting"
    st.error_reason = "timeout"
    st.retry_count = 2

    mark_success(st)

    assert st.pipeline_status == "completed"
    assert st.failed_stage is None
    assert st.error_reason is None
    assert st.retry_count == 0
    assert st.last_success_at == "2026-04-19T07:02:00+09:00"
    # last_attempt_at 도 같이 갱신된다.
    assert st.last_attempt_at == "2026-04-19T07:02:00+09:00"


def test_increment_issue_number_returns_next(tmp_path: Path) -> None:
    st = default_state()
    st.issue_number = 41

    new_value = increment_issue_number(st)
    assert new_value == 42
    assert st.issue_number == 42

    # 저장/로드 해도 값이 유지된다.
    path = tmp_path / "s.json"
    save_state(st, str(path))
    loaded = load_state(str(path))
    assert loaded.issue_number == 42


def test_compute_next_run_time_morning() -> None:
    now = _kst(2026, 4, 19, 6, 30)
    result = compute_next_run_time(now)
    assert result == "2026-04-19T07:00:00+09:00"


def test_compute_next_run_time_midday() -> None:
    now = _kst(2026, 4, 19, 12, 0)
    result = compute_next_run_time(now)
    assert result == "2026-04-19T18:00:00+09:00"


def test_compute_next_run_time_evening() -> None:
    now = _kst(2026, 4, 19, 19, 0)
    result = compute_next_run_time(now)
    assert result == "2026-04-20T07:00:00+09:00"


def test_current_period_morning_vs_afternoon() -> None:
    assert current_period(_kst(2026, 4, 19, 11, 59)) == "오전"
    assert current_period(_kst(2026, 4, 19, 12, 0)) == "오후"
    assert current_period(_kst(2026, 4, 19, 0, 0)) == "오전"
    assert current_period(_kst(2026, 4, 19, 23, 59)) == "오후"
