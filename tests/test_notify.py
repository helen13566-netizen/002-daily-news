"""pipeline.notify 단위 테스트."""

from __future__ import annotations

from datetime import datetime

import pytest
import pytz

from pipeline.config import DEPLOY_URL, KST_TZ_NAME
from pipeline.notify import (
    build_failure_message,
    build_success_message,
    top3_from_analyzed,
)
from pipeline.state import PipelineState, default_state

KST = pytz.timezone(KST_TZ_NAME)


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------


def _kst(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return KST.localize(datetime(year, month, day, hour, minute))


def _failure_state(**overrides) -> PipelineState:
    state = default_state()
    state.pipeline_status = "failed"
    state.failed_stage = "collecting"
    state.error_reason = "RSS 수집 실패: 연결 시간 초과"
    state.retry_count = 2
    state.next_run_time = "2026-04-19T18:00:00+09:00"
    for k, v in overrides.items():
        setattr(state, k, v)
    return state


# ---------------------------------------------------------------------------
# 성공 메시지
# ---------------------------------------------------------------------------


def test_success_message_has_exact_header_format() -> None:
    msg = build_success_message(
        generation_timestamp="2026-04-19T07:02:00+09:00",
        period_label="오전",
        top_titles=["알파", "베타", "감마"],
        total_count=5,
    )
    first_line = msg.split("\n", 1)[0]
    assert first_line == "📰 데일리 뉴스 · 2026.04.19 · 오전"


def test_success_message_lists_top3_numbered() -> None:
    msg = build_success_message(
        generation_timestamp="2026-04-19T07:02:00+09:00",
        period_label="오전",
        top_titles=["첫번째 제목", "두번째 제목", "세번째 제목"],
        total_count=10,
    )
    lines = msg.split("\n")
    assert "1. 첫번째 제목" in lines
    assert "2. 두번째 제목" in lines
    assert "3. 세번째 제목" in lines


def test_success_message_pads_when_fewer_titles() -> None:
    msg = build_success_message(
        generation_timestamp="2026-04-19T07:02:00+09:00",
        period_label="오전",
        top_titles=["알파", "베타"],
        total_count=2,
    )
    # "None" 이 등장해서는 안 된다.
    assert "None" not in msg
    # 존재하는 2건만 번호가 붙고, "3. " 시작 라인이 없어야 한다.
    lines = [ln for ln in msg.split("\n") if ln]
    numbered = [ln for ln in lines if ln[:3] in {"1. ", "2. ", "3. "}]
    assert numbered == ["1. 알파", "2. 베타"]


def test_success_message_total_count_and_url() -> None:
    deploy_url = "https://example.com/daily-news/"
    msg = build_success_message(
        generation_timestamp="2026-04-19T18:10:00+09:00",
        period_label="오후",
        top_titles=["t1", "t2", "t3"],
        total_count=5,
        deploy_url=deploy_url,
    )
    assert "총 5건 · 전체 보기" in msg
    # URL 은 다음 라인에 위치.
    lines = msg.split("\n")
    idx = lines.index("총 5건 · 전체 보기")
    assert lines[idx + 1] == deploy_url

    # 기본 URL 사용 시에도 DEPLOY_URL 이 들어간다.
    default_msg = build_success_message(
        generation_timestamp="2026-04-19T18:10:00+09:00",
        period_label="오후",
        top_titles=["t1", "t2", "t3"],
        total_count=5,
    )
    assert DEPLOY_URL in default_msg


# ---------------------------------------------------------------------------
# 실패 메시지
# ---------------------------------------------------------------------------


def test_failure_message_exact_header() -> None:
    state = _failure_state()
    msg = build_failure_message(state, now_kst=_kst(2026, 4, 19, 7, 10))
    assert msg.split("\n", 1)[0] == "⚠️ 뉴스 생성 실패"


def test_failure_message_fields() -> None:
    state = _failure_state()
    msg = build_failure_message(state, now_kst=_kst(2026, 4, 19, 7, 10))
    assert "시각: 2026.04.19 07:10 KST" in msg
    assert "단계: collecting" in msg
    assert "사유: RSS 수집 실패: 연결 시간 초과" in msg
    assert "재시도: 2/3" in msg
    assert "다음 스케줄: 2026.04.19 18:00 KST" in msg


def test_failure_message_truncates_error_reason() -> None:
    long_reason = "실" * 500
    state = _failure_state(error_reason=long_reason)
    msg = build_failure_message(state, now_kst=_kst(2026, 4, 19, 7, 10))

    # 사유 라인만 추출.
    reason_line = next(ln for ln in msg.split("\n") if ln.startswith("사유: "))
    reason_value = reason_line[len("사유: ") :]

    # 200자 이내 + 말줄임표.
    assert len(reason_value) == 200
    assert reason_value.endswith("…")
    # 길이 포함한 본문은 199 글자 + 말줄임표 1 글자.
    assert reason_value[:-1] == "실" * 199


def test_failure_message_next_run_display_format() -> None:
    state = _failure_state(next_run_time="2026-04-19T18:00:00+09:00")
    msg = build_failure_message(state, now_kst=_kst(2026, 4, 19, 7, 10))
    assert "다음 스케줄: 2026.04.19 18:00 KST" in msg


# ---------------------------------------------------------------------------
# top3 추출
# ---------------------------------------------------------------------------


def _art(
    *,
    idx: int,
    score: float,
    is_must_know: bool,
    title: str | None = None,
) -> dict:
    return {
        "article_id": f"art-{idx:04d}",
        "title": title or f"샘플 제목 {idx}",
        "relevance_score": score,
        "is_must_know": is_must_know,
    }


def test_top3_from_analyzed_prefers_must_know() -> None:
    articles = [
        _art(idx=1, score=9.5, is_must_know=True, title="M1"),
        _art(idx=2, score=9.0, is_must_know=True, title="M2"),
        _art(idx=3, score=8.5, is_must_know=True, title="M3"),
        _art(idx=4, score=8.2, is_must_know=True, title="M4"),
        _art(idx=5, score=8.0, is_must_know=True, title="M5"),
        _art(idx=6, score=7.9, is_must_know=False, title="R1"),
        _art(idx=7, score=7.5, is_must_know=False, title="R2"),
        _art(idx=8, score=7.0, is_must_know=False, title="R3"),
        _art(idx=9, score=6.5, is_must_know=False, title="R4"),
        _art(idx=10, score=6.0, is_must_know=False, title="R5"),
    ]
    analyzed = {"articles": articles}
    top = top3_from_analyzed(analyzed)
    assert top == ["M1", "M2", "M3"]


def test_top3_from_analyzed_fills_from_regular_if_needed() -> None:
    articles = [
        _art(idx=1, score=9.5, is_must_know=True, title="M1"),
        _art(idx=2, score=8.5, is_must_know=False, title="R_TOP"),
        _art(idx=3, score=7.0, is_must_know=False, title="R_MID"),
        _art(idx=4, score=5.0, is_must_know=False, title="R_LOW"),
    ]
    analyzed = {"articles": articles}
    top = top3_from_analyzed(analyzed)
    assert top == ["M1", "R_TOP", "R_MID"]


def test_top3_from_analyzed_handles_empty() -> None:
    assert top3_from_analyzed({}) == []
    assert top3_from_analyzed({"articles": []}) == []
    # 비정상 입력도 예외 없이 []
    assert top3_from_analyzed({"articles": None}) == []  # type: ignore[arg-type]
    assert top3_from_analyzed("not a dict") == []  # type: ignore[arg-type]
