"""
Unit Tests for Phase 3 - Story Planner Engine
Tests:
- StoryPlan & NarrativeBeat schema validation.
- LocalStoryPlannerProvider beat partitioning & duration calibration.
- Visual opportunity mapping per beat.
- Excluded interpretations protection.
- StoryPlanner fallback mechanism from Gemini to Local.
"""

from unittest.mock import MagicMock
import pytest

from production.contracts import ClaimItem, FactPack, NarrativeBeat, StoryPlan
from production.story_planner import (
    GeminiStoryPlannerProvider,
    LocalStoryPlannerProvider,
    StoryPlanner,
)


@pytest.fixture
def sample_fact_pack() -> FactPack:
    return FactPack(
        topic="Quy trình đúc vi mạch silicon",
        claims=[
            ClaimItem(
                claim="Tấm wafer silicon được xử lý qua hàng trăm bước quang khắc trong phòng sạch.",
                evidence="Quy trình sản xuất vi mạch hiện đại.",
                confidence=0.99,
                is_critical=True,
                allowed_wording="Tấm wafer silicon được tôi luyện qua hàng trăm bước quang khắc tỉ mỉ.",
            ),
            ClaimItem(
                claim="Một hạt bụi siêu vi cũng có thể làm hỏng toàn bộ tấm wafer trị giá hàng ngàn đô la.",
                evidence="Tiêu chuẩn phòng sạch cấp độ ISO 1.",
                confidence=0.95,
                is_critical=True,
            ),
        ],
        confidence_score=0.98,
        entities=["wafer", "silicon", "phòng sạch", "quang khắc", "transistor"],
        suggested_angles=[
            "Thế giới vi mô bên trong phòng sạch chế tác vi mạch",
            "Tại sao một hạt bụi có thể phá hủy chip hàng ngàn đô?",
        ],
        contradictions=[],
    )


def test_story_plan_and_narrative_beat_schema():
    beat = NarrativeBeat(
        beat_id="beat_01_hook",
        beat_type="hook",
        summary="Cận cảnh wafer silicon phản chiếu ánh vàng.",
        evidence_ref="wafer_cleanroom",
        visual_opportunity="Macro zoom vào bề mặt vi mạch",
        estimated_duration_sec=4.5,
    )
    assert beat.beat_type == "hook"
    assert beat.estimated_duration_sec == 4.5

    story_plan = StoryPlan(
        angle="Bí mật phòng sạch triệu đô",
        audience_promise="Hiểu rõ cách loài người chế tạo thứ tinh vi nhất hành tinh",
        hook_mechanism="Nghịch lý về một hạt bụi nhỏ có thể phá hủy hàng triệu đô la",
        beats=[beat],
        excluded_interpretations=["Không giải thích lan man công thức hóa học phức tạp"],
        target_duration_sec=45.0,
        tone="curiosity",
    )
    assert story_plan.target_duration_sec == 45.0
    assert len(story_plan.beats) == 1
    assert len(story_plan.excluded_interpretations) == 1


def test_local_story_planner_beats_calibration(sample_fact_pack):
    planner = LocalStoryPlannerProvider()
    target_duration = 60.0

    plan = planner.plan_story(
        fact_pack=sample_fact_pack,
        target_duration_sec=target_duration,
        tone="curiosity",
        format_type="short",
    )

    assert isinstance(plan, StoryPlan)
    assert plan.target_duration_sec == target_duration
    assert len(plan.beats) == 5

    # Check beat types sequence
    beat_types = [b.beat_type for b in plan.beats]
    assert beat_types == ["hook", "setup", "development", "climax", "payoff_cta"]

    # Verify visual opportunity exists for every beat
    for b in plan.beats:
        assert len(b.visual_opportunity) > 10, f"Beat {b.beat_id} missing visual opportunity"

    # Verify duration sum approximately matches target
    total_beats_duration = sum(b.estimated_duration_sec for b in plan.beats)
    assert abs(total_beats_duration - target_duration) <= 1.0

    # Verify excluded interpretations exist
    assert len(plan.excluded_interpretations) >= 2


def test_story_planner_fallback_on_gemini_error(sample_fact_pack):
    mock_gemini = MagicMock(spec=GeminiStoryPlannerProvider)
    mock_gemini.plan_story.side_effect = RuntimeError("Gemini API connection error")

    planner = StoryPlanner(provider=mock_gemini)
    plan = planner.generate_story_plan(
        fact_pack=sample_fact_pack,
        target_duration_sec=50.0,
        tone="curiosity",
        format_type="short",
    )

    assert isinstance(plan, StoryPlan)
    assert plan.target_duration_sec == 50.0
    assert len(plan.beats) >= 4
