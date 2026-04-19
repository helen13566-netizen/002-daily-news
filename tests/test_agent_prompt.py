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
