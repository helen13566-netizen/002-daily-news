"""pipeline.run 단위 테스트 (in-process main(argv) 호출)."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import pytz

from pipeline import collect as collect_mod
from pipeline import render as render_mod
from pipeline import run as run_mod
from pipeline import state as state_mod
from pipeline.config import KST_TZ_NAME
from pipeline.state import default_state, load_state, save_state

KST = pytz.timezone(KST_TZ_NAME)

FIXTURE_ANALYZED = Path(__file__).parent / "fixtures" / "analyzed_sample.json"


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def _kst(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return KST.localize(datetime(year, month, day, hour, minute))


def _write_state(path: Path, **overrides) -> None:
    st = default_state()
    for k, v in overrides.items():
        setattr(st, k, v)
    save_state(st, str(path))


def _state_path(tmp_path: Path) -> Path:
    return tmp_path / "state.json"


def _call(argv: list[str]) -> int:
    """in-process 로 pipeline.run.main 실행, exit code 반환."""
    return run_mod.main(argv)


def _analyzed_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_ANALYZED.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1) collect 성공 경로
# ---------------------------------------------------------------------------


def test_run_collect_marks_stage_and_invokes_collect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    state_path = _state_path(tmp_path)
    _write_state(state_path)

    fake_summary = {
        "collection_timestamp": "2026-04-19T07:00:00+09:00",
        "source_stats": {
            "AI타임스": {"fetched": 10, "ai_matched": 3, "kept": 3},
            "연합뉴스": {"fetched": 20, "ai_matched": 0, "kept": 20},
        },
        "articles": [{"article_id": "a1"}, {"article_id": "a2"}],
    }
    called: dict[str, Any] = {}

    def fake_collect(output_path: str | Path = "ignored") -> dict[str, Any]:
        called["output_path"] = str(output_path)
        return fake_summary

    monkeypatch.setattr(collect_mod, "collect", fake_collect)

    candidates = tmp_path / "candidates.json"
    rc = _call(
        [
            "--state-path",
            str(state_path),
            "collect",
            "--candidates-path",
            str(candidates),
        ]
    )
    assert rc == 0

    # collect 가 정확한 path 로 호출되었는지.
    assert called["output_path"] == str(candidates)

    # state 검증.
    st = load_state(str(state_path))
    assert st.pipeline_status == "collecting"
    assert st.failed_stage is None
    assert st.error_reason is None
    assert st.last_attempt_at is not None

    # stdout 은 source_stats JSON.
    captured = capsys.readouterr()
    stdout_json = json.loads(captured.out)
    assert stdout_json == fake_summary["source_stats"]


# ---------------------------------------------------------------------------
# 2) collect 예외 → mark_failure + exit 1
# ---------------------------------------------------------------------------


def test_run_collect_on_exception_marks_failure_and_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = _state_path(tmp_path)
    _write_state(state_path)

    def boom(output_path: str | Path = "ignored") -> dict[str, Any]:
        raise RuntimeError("RSS timeout")

    monkeypatch.setattr(collect_mod, "collect", boom)

    rc = _call(
        [
            "--state-path",
            str(state_path),
            "collect",
            "--candidates-path",
            str(tmp_path / "c.json"),
        ]
    )
    assert rc == 1

    st = load_state(str(state_path))
    assert st.pipeline_status == "failed"
    assert st.failed_stage == "collecting"
    assert "RSS timeout" in (st.error_reason or "")
    assert st.retry_count == 1


# ---------------------------------------------------------------------------
# 3) render 예외 → mark_failure
# ---------------------------------------------------------------------------


def test_run_render_on_exception_marks_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = _state_path(tmp_path)
    _write_state(state_path, retry_count=0)

    def boom(**kwargs: Any) -> dict[str, Any]:
        raise ValueError("analyzed.json 에 generation_timestamp 가 없습니다.")

    monkeypatch.setattr(render_mod, "render", boom)

    rc = _call(
        [
            "--state-path",
            str(state_path),
            "render",
            "--analyzed-path",
            str(tmp_path / "analyzed.json"),
            "--output-path",
            str(tmp_path / "docs" / "index.html"),
        ]
    )
    assert rc == 1

    st = load_state(str(state_path))
    assert st.pipeline_status == "failed"
    assert st.failed_stage == "generating"
    assert "generation_timestamp" in (st.error_reason or "")
    assert st.retry_count == 1


# ---------------------------------------------------------------------------
# 4) prepare-run: issue_number++, retry_count=0, 실패 필드 clear
# ---------------------------------------------------------------------------


def test_run_prepare_run_increments_issue_and_resets_retry(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    state_path = _state_path(tmp_path)
    _write_state(
        state_path,
        issue_number=5,
        retry_count=2,
        failed_stage="x",
        error_reason="prev error",
        pipeline_status="failed",
    )

    rc = _call(
        [
            "--state-path",
            str(state_path),
            "prepare-run",
            "--period",
            "오전",
        ]
    )
    assert rc == 0

    st = load_state(str(state_path))
    assert st.issue_number == 6
    assert st.retry_count == 0
    assert st.failed_stage is None
    assert st.error_reason is None
    assert st.current_period == "오전"
    assert st.next_run_time is not None
    assert st.current_generation_timestamp is not None

    captured = capsys.readouterr()
    stdout_data = json.loads(captured.out)
    assert stdout_data["issue_number"] == 6
    assert stdout_data["period"] == "오전"
    assert "generation_timestamp" in stdout_data


# ---------------------------------------------------------------------------
# 5) mark-success 가 error 필드 clear + last_success_at 세팅
# ---------------------------------------------------------------------------


def test_run_mark_success_clears_errors_and_sets_timestamp(
    tmp_path: Path,
) -> None:
    state_path = _state_path(tmp_path)
    _write_state(
        state_path,
        issue_number=10,
        retry_count=2,
        failed_stage="generating",
        error_reason="template missing",
        pipeline_status="failed",
    )

    rc = _call(["--state-path", str(state_path), "mark-success"])
    assert rc == 0

    st = load_state(str(state_path))
    assert st.pipeline_status == "completed"
    assert st.failed_stage is None
    assert st.error_reason is None
    assert st.retry_count == 0
    assert st.last_success_at is not None
    # issue_number 는 건드리지 않는다.
    assert st.issue_number == 10


# ---------------------------------------------------------------------------
# 6) mark-failure 를 2회 호출하면 retry_count 가 2회 증가
# ---------------------------------------------------------------------------


def test_run_mark_failure_subcommand_increments_retry(tmp_path: Path) -> None:
    state_path = _state_path(tmp_path)
    _write_state(state_path, retry_count=0)

    rc = _call(
        [
            "--state-path",
            str(state_path),
            "mark-failure",
            "--stage",
            "collecting",
            "--reason",
            "first",
        ]
    )
    assert rc == 0
    st1 = load_state(str(state_path))
    assert st1.retry_count == 1
    assert st1.failed_stage == "collecting"

    rc2 = _call(
        [
            "--state-path",
            str(state_path),
            "mark-failure",
            "--stage",
            "generating",
            "--reason",
            "second",
        ]
    )
    assert rc2 == 0
    st2 = load_state(str(state_path))
    assert st2.retry_count == 2
    assert st2.failed_stage == "generating"
    assert st2.error_reason == "second"


# ---------------------------------------------------------------------------
# 7) notify-success 가 analyzed.json 과 state 를 읽어 Seed 템플릿 메시지 생성
# ---------------------------------------------------------------------------


def test_run_notify_success_reads_analyzed_and_state_and_prints_message(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    state_path = _state_path(tmp_path)
    _write_state(
        state_path,
        issue_number=112,
        current_period="오전",
        current_generation_timestamp="2026-04-19T07:02:00+09:00",
    )

    analyzed_path = tmp_path / "analyzed.json"
    shutil.copyfile(FIXTURE_ANALYZED, analyzed_path)

    rc = _call(
        [
            "--state-path",
            str(state_path),
            "notify-success",
            "--analyzed-path",
            str(analyzed_path),
        ]
    )
    assert rc == 0

    captured = capsys.readouterr()
    # 절취선으로 감싼 헤더 안에 Seed 템플릿 문구가 있어야 한다.
    assert "📰 데일리 뉴스" in captured.out
    # 날짜 + 오전 표기 포함.
    assert "2026.04.19" in captured.out
    assert "오전" in captured.out
    # 총 기사수 6건 (fixture).
    assert "총 6건" in captured.out


# ---------------------------------------------------------------------------
# 8) notify-failure 가 ⚠️ 헤더로 시작하는 메시지 출력
# ---------------------------------------------------------------------------


def test_run_notify_failure_prints_warning_header(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    state_path = _state_path(tmp_path)
    _write_state(
        state_path,
        pipeline_status="failed",
        failed_stage="collecting",
        error_reason="RSS timeout",
        retry_count=3,
        next_run_time="2026-04-19T18:00:00+09:00",
    )

    rc = _call(["--state-path", str(state_path), "notify-failure"])
    assert rc == 0

    captured = capsys.readouterr()
    assert "⚠️ 뉴스 생성 실패" in captured.out
    assert "단계: collecting" in captured.out
    assert "사유: RSS timeout" in captured.out
    assert "재시도: 3/3" in captured.out


# ---------------------------------------------------------------------------
# 9) stdout / stderr 분리: JSON 은 stdout, 로그는 stderr
# ---------------------------------------------------------------------------


def test_run_validate_analyzed_passes_when_all_ids_match(
    tmp_path: Path,
) -> None:
    """analyzed 의 모든 article_id 가 candidates 에 있으면 exit 0."""
    state_path = _state_path(tmp_path)
    _write_state(state_path, retry_count=0)

    candidates = tmp_path / "candidates.json"
    candidates.write_text(
        json.dumps(
            {
                "collection_timestamp": "2026-04-21T08:30:00+09:00",
                "articles": [
                    {"article_id": "aaa111", "title": "A", "published_at": "2026-04-20T18:00:00+09:00"},
                    {"article_id": "bbb222", "title": "B", "published_at": "2026-04-21T06:00:00+09:00"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    analyzed = tmp_path / "analyzed.json"
    analyzed.write_text(
        json.dumps(
            {
                "issue_number": 17,
                "generation_timestamp": "2026-04-21T08:30:00+09:00",
                "articles": [
                    {"article_id": "aaa111", "title": "A"},
                    {"article_id": "bbb222", "title": "B"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc = _call(
        [
            "--state-path",
            str(state_path),
            "validate-analyzed",
            "--candidates-path",
            str(candidates),
            "--analyzed-path",
            str(analyzed),
        ]
    )
    assert rc == 0
    st = load_state(str(state_path))
    assert st.failed_stage is None


def test_run_validate_analyzed_fails_when_foreign_article(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """analyzed 에 candidates 밖 article_id 가 있으면 exit 1, FAILED_STAGE=analyzing."""
    state_path = _state_path(tmp_path)
    _write_state(state_path, retry_count=0)

    candidates = tmp_path / "candidates.json"
    candidates.write_text(
        json.dumps(
            {
                "collection_timestamp": "2026-04-21T08:30:00+09:00",
                "articles": [
                    {"article_id": "aaa111", "title": "A"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    analyzed = tmp_path / "analyzed.json"
    analyzed.write_text(
        json.dumps(
            {
                "issue_number": 17,
                "generation_timestamp": "2026-04-21T08:30:00+09:00",
                "articles": [
                    {"article_id": "aaa111", "title": "A"},
                    # ↓ candidates 에 없는 외부 유입 기사
                    {"article_id": "xxx999", "title": "외부 기사 (윈도우 밖)"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc = _call(
        [
            "--state-path",
            str(state_path),
            "validate-analyzed",
            "--candidates-path",
            str(candidates),
            "--analyzed-path",
            str(analyzed),
        ]
    )
    assert rc == 1
    st = load_state(str(state_path))
    assert st.failed_stage == "analyzing"
    assert st.pipeline_status == "failed"
    assert "xxx999" in (st.error_reason or "")


def test_run_validate_analyzed_fails_when_category_downgraded(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """candidates 의 category=official_ai 인 기사를 analyzed 가 ai_news 로 바꾸면 실패한다.

    이 버그는 2026-04-23 오후 브리핑에서 실제 발생: agent 가 OpenAI Blog /
    Simon Willison 기사의 category 를 ai_news 로 덮어써 공식 AI 섹션이 사라졌다.
    validate-analyzed 가 defense-in-depth 로 이 diff 를 잡아 실패 처리해야 한다.
    """
    state_path = _state_path(tmp_path)
    _write_state(state_path, retry_count=0)

    candidates = tmp_path / "candidates.json"
    candidates.write_text(
        json.dumps(
            {
                "collection_timestamp": "2026-04-23T17:30:00+09:00",
                "articles": [
                    {"article_id": "ai001", "title": "AI 뉴스", "category": "ai_news"},
                    {
                        "article_id": "off001",
                        "title": "Scaling Codex to enterprises",
                        "category": "official_ai",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    analyzed = tmp_path / "analyzed.json"
    analyzed.write_text(
        json.dumps(
            {
                "issue_number": 26,
                "generation_timestamp": "2026-04-23T17:30:00+09:00",
                "articles": [
                    {"article_id": "ai001", "title": "AI 뉴스", "category": "ai_news"},
                    # ↓ 원래 official_ai 였던 기사를 ai_news 로 다운그레이드
                    {
                        "article_id": "off001",
                        "title": "Scaling Codex to enterprises",
                        "category": "ai_news",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc = _call(
        [
            "--state-path",
            str(state_path),
            "validate-analyzed",
            "--candidates-path",
            str(candidates),
            "--analyzed-path",
            str(analyzed),
        ]
    )
    assert rc == 1
    st = load_state(str(state_path))
    assert st.failed_stage == "analyzing"
    assert st.pipeline_status == "failed"
    assert "off001" in (st.error_reason or "") or "category" in (st.error_reason or "")


def test_run_validate_analyzed_fails_when_file_missing(
    tmp_path: Path,
) -> None:
    """candidates 또는 analyzed 파일이 없으면 exit 1."""
    state_path = _state_path(tmp_path)
    _write_state(state_path)

    rc = _call(
        [
            "--state-path",
            str(state_path),
            "validate-analyzed",
            "--candidates-path",
            str(tmp_path / "missing-cand.json"),
            "--analyzed-path",
            str(tmp_path / "missing-ana.json"),
        ]
    )
    assert rc == 1


def test_run_stdout_vs_stderr_separation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    state_path = _state_path(tmp_path)
    _write_state(state_path)

    fake_summary = {
        "collection_timestamp": "2026-04-19T07:00:00+09:00",
        "source_stats": {"AI타임스": {"fetched": 1, "ai_matched": 1, "kept": 1}},
        "articles": [{"article_id": "a1"}],
    }
    monkeypatch.setattr(collect_mod, "collect", lambda output_path="x": fake_summary)

    rc = _call(
        [
            "--state-path",
            str(state_path),
            "collect",
            "--candidates-path",
            str(tmp_path / "c.json"),
        ]
    )
    assert rc == 0

    captured = capsys.readouterr()
    # stdout: 순수 JSON 파싱 가능.
    parsed = json.loads(captured.out)
    assert parsed == fake_summary["source_stats"]

    # stderr: 사람이 읽는 로그 (접두사 [pipeline.run]).
    assert "[pipeline.run]" in captured.err
    assert "stage=collecting" in captured.err
    assert "collected 1 articles" in captured.err

    # stderr 내용이 stdout 에 섞여 있으면 안 된다.
    assert "[pipeline.run]" not in captured.out
