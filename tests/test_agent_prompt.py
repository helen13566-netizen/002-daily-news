"""agent-prompt.md 문서 구조 검증.

이 파일은 인간이 편집하는 프롬프트지만, 배포 시 필수 블록이 실수로
누락되면 agent 의 분석 품질이 떨어진다. 아래 테스트가 regression 을 잡는다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATH = REPO_ROOT / "scripts" / "agent-prompt.md"


@pytest.fixture(scope="module")
def prompt_text() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


# v13: 페르소나에 공신력 있는 프레임워크 10종 이름이 포함
REQUIRED_FRAMEWORK_MENTIONS = [
    "Stanford",        # Civic Online Reasoning
    "IMVAIN",          # Stony Brook
    "Tetlock",         # Superforecasting
    "Meadows",         # Systems / Iceberg
    "Entman",          # Framing
    "Reference Class", # Kahneman
    "IFCN",            # Fact-checking code
]


def test_v13_persona_names_frameworks(prompt_text: str) -> None:
    """v13 페르소나에는 신뢰할 수 있는 분석 프레임워크 이름이 명시된다."""
    missing = [name for name in REQUIRED_FRAMEWORK_MENTIONS if name not in prompt_text]
    assert not missing, (
        f"agent-prompt.md 에서 다음 프레임워크 언급이 빠졌습니다: {missing}"
    )


# v13: 각 축별 체크리스트가 문서에 존재
AXIS_CHECKLIST_MARKERS = [
    # 마커 문구는 체크리스트 블록 안에 등장하는 고유 텍스트
    ("ripple", "Iceberg"),           # Events/Patterns/Structures 중 적어도 이것
    ("history", "reference class"),  # reference class 정의 지시
    ("scenario", "갈림길"),           # 다음 이벤트가 결정
    ("personal", "피해야 할 행동"),    # 반사 행동 경계
    ("frame", "lateral reading"),    # COR 핵심
    ("perspective", "stakeholder"),  # 매핑 지시
]


@pytest.mark.parametrize("axis, marker", AXIS_CHECKLIST_MARKERS)
def test_v13_axis_checklist_present(prompt_text: str, axis: str, marker: str) -> None:
    """6축 각각의 체크리스트가 agent-prompt.md 에 존재한다."""
    lowered = prompt_text.lower()
    assert marker.lower() in lowered, (
        f"축 '{axis}' 의 체크리스트 마커 '{marker}' 가 agent-prompt.md 에 없습니다"
    )


def test_v13_probability_grading_instruction(prompt_text: str) -> None:
    """scenario 와 전체 톤에서 확률 등급 표현 지시가 있어야 한다."""
    # 높다/중간/낮다 또는 높음/중간/낮음 중 하나의 세트가 존재해야 함
    has_high_mid_low = (
        ("높다" in prompt_text and "중간" in prompt_text and "낮다" in prompt_text)
        or ("높음" in prompt_text and "중간" in prompt_text and "낮음" in prompt_text)
    )
    assert has_high_mid_low, "확률 등급(높음/중간/낮음) 지시가 agent-prompt.md 에 없습니다"


def test_v13_checklist_is_internal_not_leaked_to_text(prompt_text: str) -> None:
    """체크리스트는 내부에서 수행되고 최종 text 에 나열하지 말라는 지시 포함."""
    # 유연한 매칭: "속으로" 또는 "내부" 또는 "inner" 중 하나
    has_internal_instruction = any(
        kw in prompt_text for kw in ["속으로", "내부에서", "내면", "나열하지"]
    )
    assert has_internal_instruction, (
        "체크리스트를 속으로 수행하고 text 에 나열하지 말라는 지시가 없습니다"
    )


# v14 — 분량 확대 · 구조 드러내기 · 구체성 강제 · chunk 2건

def test_v14_text_length_expanded(prompt_text: str) -> None:
    """insight text 분량 하한이 200 이상, 상한이 350 이하로 상향됐는지."""
    assert "200" in prompt_text and "350" in prompt_text, (
        "insight text 분량 가이드에 200~350자 범위가 명시돼야 합니다"
    )


def test_v14_concrete_evidence_required(prompt_text: str) -> None:
    """구체 수치·회사·연도를 최소 N개 포함하도록 강제."""
    has_concrete_instruction = (
        ("구체" in prompt_text or "수치" in prompt_text)
        and ("연도" in prompt_text or "회사" in prompt_text or "숫자" in prompt_text)
    )
    assert has_concrete_instruction, (
        "구체 수치·회사명·연도를 최소 2개 포함하도록 하는 지시가 있어야 합니다"
    )


def test_v14_structure_visible_in_text(prompt_text: str) -> None:
    """분석 단계·구조를 text 에 드러내도록 지시. '1차/2차/3차' 같은 라벨 권장."""
    has_visible_structure = any(
        kw in prompt_text
        for kw in ["1차 효과", "구조를 드러", "단계를 명시", "분석 흐름"]
    )
    assert has_visible_structure, (
        "분석 구조(1차·2차·3차 등)를 text 에 드러내라는 지시가 있어야 합니다"
    )


def test_v14_chunk_size_two_articles(prompt_text: str) -> None:
    """chunk 크기가 2건 단위로 축소됐는지 (v12/v13: 3건)."""
    has_two_chunk = (
        "2건 단위" in prompt_text
        or "2건씩" in prompt_text
        or "2건 chunk" in prompt_text
    )
    assert has_two_chunk, (
        "chunk 크기가 2건 단위로 축소됐다는 표시가 있어야 합니다 (v14)"
    )


def test_v15_hard_floor_20_not_10(prompt_text: str) -> None:
    """v15: 하한이 20건으로 상향됐고 10건 조항은 제거."""
    # 각 섹션 하한 20 건 명시
    assert "하한 20건" in prompt_text or "최소 20건" in prompt_text, (
        "각 섹션 하한을 20건으로 명시해야 합니다 (v15)"
    )
    # 10건 완화 조항 제거 검증
    assert "하한 10건" not in prompt_text, (
        "v14 의 '하한 10건' 완화 조항은 v15 에서 제거되어야 합니다"
    )


def test_v15_floor_is_last_resort(prompt_text: str) -> None:
    """v15: 하한 완화는 최후 수단 (stream idle timeout 직전에만)."""
    has_last_resort = any(
        kw in prompt_text
        for kw in ["최후 수단", "정말 촉박", "timeout 직전"]
    )
    assert has_last_resort, (
        "하한을 최후 수단으로만 허용한다는 문구가 있어야 합니다 (v15)"
    )


# v16 — sandbox 안에서 직접 collect 금지 + Actions workflow_dispatch 폴백


def test_v16_forbids_direct_collect_in_sandbox(prompt_text: str) -> None:
    """sandbox 안에서 pipeline.collect 직접 호출 금지가 명시돼야 한다."""
    has_forbid = (
        "pipeline.collect" in prompt_text
        and any(
            kw in prompt_text
            for kw in ["직접 호출하지", "직접 실행하지", "절대 호출", "금지"]
        )
    )
    assert has_forbid, (
        "agent 가 sandbox 안에서 pipeline.collect 를 직접 실행하지 못하도록 "
        "명시적 금지 문구가 있어야 합니다 (v16)"
    )


def test_v16_workflow_dispatch_fallback(prompt_text: str) -> None:
    """candidates.json 신선도 부족 시 collect.yml workflow_dispatch 폴백 명시."""
    has_dispatch = (
        "workflows/collect.yml/dispatches" in prompt_text
        or "workflow_dispatch" in prompt_text
        or ("collect.yml" in prompt_text and "dispatches" in prompt_text)
    )
    assert has_dispatch, (
        "candidates 가 오래되면 GitHub Actions collect.yml 을 workflow_dispatch 로 "
        "트리거하는 폴백 절차가 명시돼야 합니다 (v16)"
    )


def test_v16_polling_after_dispatch(prompt_text: str) -> None:
    """workflow 트리거 후 git pull 폴링 절차가 명시돼야 한다."""
    has_polling = (
        ("폴링" in prompt_text or "polling" in prompt_text.lower())
        and any(kw in prompt_text for kw in ["git fetch", "git pull", "git reset"])
    )
    assert has_polling, (
        "workflow_dispatch 트리거 후 git fetch/pull 로 폴링하는 절차가 "
        "명시돼야 합니다 (v16)"
    )


def test_v20_official_ai_section_quota(prompt_text: str) -> None:
    """공식 AI 업데이트 섹션 쿼터(3~5건) 지시 + official_ai 카테고리 명시."""
    has_official_ai = "official_ai" in prompt_text or "공식 AI" in prompt_text
    has_quota = any(kw in prompt_text for kw in ["3~5건", "3-5건", "3~5 건"])
    assert has_official_ai, "agent-prompt.md 에 공식 AI 카테고리 언급이 있어야 합니다"
    assert has_quota, "agent-prompt.md 에 공식 AI 3~5건 쿼터 지시가 있어야 합니다"
