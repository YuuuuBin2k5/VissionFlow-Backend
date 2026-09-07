"""
Unit Tests for Phase 3 - Script Engine & Canonical Narration Service
Tests:
- SceneNarration & ScriptPlan schema validation.
- Canonical narration rule: scenes[].narration is single timing authority.
- Derivation of full_script strictly through scene concatenation.
- Hook length constraints (< 16 words).
- Word counting and Vietnamese speech pacing calibration.
- ScriptEngine fallback mechanism from Gemini to Local.
"""

from unittest.mock import MagicMock
import pytest

from production.contracts import ClaimItem, FactPack, NarrativeBeat, SceneNarration, ScriptPlan, StoryPlan
from production.script_service import (
    GeminiScriptProvider,
    LocalScriptProvider,
    ScriptEngine,
    count_words,
    estimate_duration_sec,
)


@pytest.fixture
def sample_fact_and_story():
    fact_pack = FactPack(
        topic="Mộng gỗ Kigumi",
        claims=[
            ClaimItem(
                claim="Kỹ thuật Kigumi khớp các thanh gỗ khít khao mà không dùng đến một chiếc đinh nào.",
                evidence="Truyền thống kiến trúc mộc Nhật Bản.",
                confidence=0.99,
                is_critical=True,
                allowed_wording="Nghệ thuật Kigumi ghép các khối gỗ hoàn mỹ mà không cần bất kỳ chiếc đinh nào.",
            ),
        ],
        confidence_score=0.98,
        entities=["Kigumi", "gỗ", "đục"],
        suggested_angles=["Kỳ công mộng gỗ nghìn năm"],
        contradictions=[],
    )

    beats = [
        NarrativeBeat(
            beat_id="beat_01_hook",
            beat_type="hook",
            summary="Mở đầu tò mò về mộng gỗ không đinh",
            visual_opportunity="Macro mộng gỗ trượt vào nhau",
            estimated_duration_sec=4.0,
        ),
        NarrativeBeat(
            beat_id="beat_02_setup",
            beat_type="setup",
            summary="Chuẩn bị nguyên liệu gỗ chất lượng cao",
            visual_opportunity="Gỗ nguyên khối được xẻ thẳng",
            estimated_duration_sec=10.0,
        ),
        NarrativeBeat(
            beat_id="beat_03_dev",
            beat_type="development",
            summary="Đục đẽo tỉ mỉ từng rãnh mộng",
            visual_opportunity="Lưỡi đục bén ngọt trên thớ gỗ",
            estimated_duration_sec=18.0,
        ),
        NarrativeBeat(
            beat_id="beat_04_climax",
            beat_type="climax",
            summary="Ghép nối hoàn hảo không một kẽ hở",
            visual_opportunity="Hai khối gỗ khóa chặt",
            estimated_duration_sec=13.0,
        ),
        NarrativeBeat(
            beat_id="beat_05_cta",
            beat_type="payoff_cta",
            summary="Thông điệp giá trị và câu hỏi kết",
            visual_opportunity="Tác phẩm hoàn chỉnh đứng vững",
            estimated_duration_sec=5.0,
        ),
    ]

    story_plan = StoryPlan(
        angle="Kỳ công mộng gỗ nghìn năm",
        audience_promise="Khám phá tuyệt kỹ mộng gỗ không đinh",
        hook_mechanism="Nghịch lý công trình nghìn năm không một cây đinh",
        beats=beats,
        excluded_interpretations=["Không giải thích lan man lịch sử phong kiến"],
        target_duration_sec=50.0,
        tone="curiosity",
    )

    return fact_pack, story_plan


def test_script_plan_and_scene_narration_schema():
    scn = SceneNarration(
        scene_index=1,
        narration="Bạn có tin một ngôi chùa gỗ nghìn năm tuổi không cần đến một chiếc đinh nào?",
        beat_ref="beat_01_hook",
        estimated_speech_duration_sec=4.5,
        visual_cue="Cận cảnh mái chùa cổ",
    )
    assert scn.scene_index == 1
    assert scn.estimated_speech_duration_sec == 4.5

    script = ScriptPlan(
        title="Bí Mật Mộng Gỗ",
        full_script=scn.narration,
        scenes=[scn],
        total_word_count=18,
        estimated_total_duration_sec=4.5,
        hook_word_count=18,
    )
    assert script.title == "Bí Mật Mộng Gỗ"
    assert len(script.scenes) == 1


def test_canonical_script_derivation_and_pacing(sample_fact_and_story):
    fact_pack, story_plan = sample_fact_and_story
    provider = LocalScriptProvider()

    script_plan = provider.generate_script(
        story_plan=story_plan,
        fact_pack=fact_pack,
        language="vi",
        target_wps=2.8,
    )

    assert isinstance(script_plan, ScriptPlan)
    assert len(script_plan.scenes) == len(story_plan.beats)

    # CANONICAL RULE: full_script MUST be identical to concatenated scenes[].narration
    expected_full_script = " ".join(s.narration for s in script_plan.scenes)
    assert script_plan.full_script == expected_full_script

    # Word count correctness
    assert script_plan.total_word_count == count_words(expected_full_script)
    assert script_plan.hook_word_count == count_words(script_plan.scenes[0].narration)

    # Hook brevity check: Scene 1 must be concise (< 16 words)
    assert script_plan.hook_word_count <= 16

    # Verify each scene has duration estimation
    for s in script_plan.scenes:
        assert s.estimated_speech_duration_sec > 0.0
        assert s.beat_ref is not None


def test_script_engine_fallback_on_gemini_error(sample_fact_and_story):
    fact_pack, story_plan = sample_fact_and_story
    mock_gemini = MagicMock(spec=GeminiScriptProvider)
    mock_gemini.generate_script.side_effect = RuntimeError("Gemini quota exhausted")

    engine = ScriptEngine(provider=mock_gemini)
    script = engine.generate_script_plan(
        story_plan=story_plan,
        fact_pack=fact_pack,
        language="vi",
    )

    assert isinstance(script, ScriptPlan)
    assert len(script.scenes) == 5
    assert script.full_script == " ".join(s.narration for s in script.scenes)
