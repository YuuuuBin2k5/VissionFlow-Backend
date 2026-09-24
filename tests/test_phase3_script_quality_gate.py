"""
Unit Tests for Phase 3 - Script Quality Gate Engine
Tests all 7 multi-axis editorial validation rules:
- Rule 1: Canonical Narration Consistency (scenes <-> full_script) -> BLOCKER
- Rule 2: Hook Latency (< 16 words / < 4.5s in Scene 1) -> WARNING / BLOCKER
- Rule 3: Pacing / Speech Density (2.0 <= WpS <= 3.8) -> WARNING
- Rule 4: Repetition & Lexical Echo (3-gram duplicates >= 3) -> WARNING
- Rule 5: Sentence Integrity & Broken Clauses (trailing punctuation / dangling conjunctions) -> BLOCKER
- Rule 6: Critical Fact Support (grounding in FactPack) -> WARNING
- Rule 7: Breathability & Run-on Sentences (> 35 words without punctuation) -> WARNING
"""

import pytest

from production.contracts import (
    ClaimItem,
    FactPack,
    QualityStatus,
    SceneNarration,
    ScriptPlan,
)
from production.script_quality_gate import ScriptQualityGate


@pytest.fixture
def base_valid_script_and_fact_pack():
    fact_pack = FactPack(
        topic="Mộng gỗ Kigumi",
        claims=[
            ClaimItem(
                claim="Kỹ thuật Kigumi khớp các thanh gỗ khít khao mà không dùng đinh.",
                evidence="Truyền thống Nhật Bản",
                is_critical=True,
            )
        ],
        confidence_score=0.95,
        entities=["Kigumi", "gỗ"],
        suggested_angles=["Kỳ công mộng gỗ"],
        contradictions=[],
    )

    scenes = [
        SceneNarration(
            scene_index=1,
            narration="Điều gì tạo nên sự tinh xảo khó tin của mộng gỗ Kigumi?",
            estimated_speech_duration_sec=4.0,
        ),
        SceneNarration(
            scene_index=2,
            narration="Từng thớ gỗ được gọt giũa tỉ mỉ để ghép khít khao mà không cần đến một chiếc đinh nào.",
            estimated_speech_duration_sec=6.0,
        ),
    ]
    full_script = " ".join(s.narration for s in scenes)
    script_plan = ScriptPlan(
        title="Kỳ Công Mộng Gỗ",
        full_script=full_script,
        scenes=scenes,
        total_word_count=len(full_script.split()),
        estimated_total_duration_sec=10.0,
        hook_word_count=len(scenes[0].narration.split()),
    )
    return script_plan, fact_pack


def test_rule_01_canonical_consistency(base_valid_script_and_fact_pack):
    script_plan, fact_pack = base_valid_script_and_fact_pack
    gate = ScriptQualityGate()

    # Valid scenario
    report = gate.evaluate(script_plan, fact_pack, target_duration_sec=10.0)
    assert report.status in (QualityStatus.PASS, QualityStatus.WARN)
    assert not any(v.rule_id == "RULE_01_CANONICAL_CONSISTENCY" for v in report.violations)

    # Inconsistent scenario: full_script was modified without updating scenes
    script_plan.full_script = "Nội dung này đã bị sửa lệch và không còn khớp với scenes."
    report_inconsistent = gate.evaluate(script_plan, fact_pack, target_duration_sec=10.0)
    assert report_inconsistent.status == QualityStatus.FAIL
    assert report_inconsistent.blocker_count >= 1
    assert any(v.rule_id == "RULE_01_CANONICAL_CONSISTENCY" and v.severity == "BLOCKER" for v in report_inconsistent.violations)


def test_rule_02_hook_latency():
    gate = ScriptQualityGate(max_hook_words=16)

    # Overly verbose hook (> 16 words)
    long_hook = "Chào mừng tất cả các bạn đã quay trở lại với kênh hôm nay chúng ta sẽ cùng nhau tìm hiểu một chủ đề vô cùng thú vị và bí ẩn."
    scenes = [
        SceneNarration(scene_index=1, narration=long_hook, estimated_speech_duration_sec=8.0),
    ]
    script_plan = ScriptPlan(
        title="Test",
        full_script=long_hook,
        scenes=scenes,
        total_word_count=len(long_hook.split()),
        estimated_total_duration_sec=8.0,
        hook_word_count=len(long_hook.split()),
    )

    report = gate.evaluate(script_plan, target_duration_sec=10.0)
    assert any(v.rule_id == "RULE_02_HOOK_LATENCY" and v.severity == "WARNING" for v in report.violations)


def test_rule_03_pacing():
    gate = ScriptQualityGate(min_wps=2.0, max_wps=3.8)

    # Script too fast: 80 words in 10 seconds -> 8.0 WpS
    fast_text = " ".join(["từ"] * 80) + "."
    scenes_fast = [SceneNarration(scene_index=1, narration=fast_text, estimated_speech_duration_sec=10.0)]
    script_fast = ScriptPlan(
        title="Fast",
        full_script=fast_text,
        scenes=scenes_fast,
        total_word_count=80,
        estimated_total_duration_sec=10.0,
        hook_word_count=80,
    )
    report_fast = gate.evaluate(script_fast, target_duration_sec=10.0)
    assert any(v.rule_id == "RULE_03_PACING_TOO_FAST" for v in report_fast.violations)

    # Script too slow: 10 words in 15 seconds -> 0.67 WpS
    slow_text = "Hôm nay chúng ta sẽ cùng khám phá một bí mật."
    scenes_slow = [SceneNarration(scene_index=1, narration=slow_text, estimated_speech_duration_sec=15.0)]
    script_slow = ScriptPlan(
        title="Slow",
        full_script=slow_text,
        scenes=scenes_slow,
        total_word_count=10,
        estimated_total_duration_sec=15.0,
        hook_word_count=10,
    )
    report_slow = gate.evaluate(script_slow, target_duration_sec=15.0)
    assert any(v.rule_id == "RULE_03_PACING_TOO_SLOW" for v in report_slow.violations)


def test_rule_04_repetition_echo():
    gate = ScriptQualityGate()
    # 3-gram "đặc biệt này" repeated 4 times
    text = "Quy trình đặc biệt này tạo ra kết quả đặc biệt này vì phương pháp đặc biệt này luôn mang lại giá trị đặc biệt này."
    scenes = [SceneNarration(scene_index=1, narration=text, estimated_speech_duration_sec=8.0)]
    script = ScriptPlan(
        title="Repetition",
        full_script=text,
        scenes=scenes,
        total_word_count=len(text.split()),
        estimated_total_duration_sec=8.0,
        hook_word_count=len(text.split()),
    )
    report = gate.evaluate(script, target_duration_sec=8.0)
    assert any(v.rule_id == "RULE_04_REPETITION_ECHO" for v in report.violations)


def test_rule_05_sentence_integrity_and_dangling_conjunctions():
    gate = ScriptQualityGate()

    # Broken punctuation: ends with comma
    s1 = SceneNarration(scene_index=1, narration="Kỹ thuật này rất độc đáo,", estimated_speech_duration_sec=3.0)
    script_broken = ScriptPlan(
        title="Broken",
        full_script=s1.narration,
        scenes=[s1],
        total_word_count=len(s1.narration.split()),
        estimated_total_duration_sec=3.0,
        hook_word_count=len(s1.narration.split()),
    )
    report_broken = gate.evaluate(script_broken, target_duration_sec=3.0)
    assert any(v.rule_id == "RULE_05_BROKEN_PUNCTUATION" and v.severity == "BLOCKER" for v in report_broken.violations)
    assert report_broken.status == QualityStatus.FAIL

    # Dangling conjunction: ends with "và"
    s2 = SceneNarration(scene_index=1, narration="Người thợ cẩn thận lấy thước đo và", estimated_speech_duration_sec=3.0)
    script_dangling = ScriptPlan(
        title="Dangling",
        full_script=s2.narration,
        scenes=[s2],
        total_word_count=len(s2.narration.split()),
        estimated_total_duration_sec=3.0,
        hook_word_count=len(s2.narration.split()),
    )
    report_dangling = gate.evaluate(script_dangling, target_duration_sec=3.0)
    assert any(v.rule_id == "RULE_05_DANGLING_CONJUNCTION" and v.severity == "BLOCKER" for v in report_dangling.violations)
    assert report_dangling.status == QualityStatus.FAIL


def test_rule_06_critical_fact_support():
    gate = ScriptQualityGate()
    fact_pack = FactPack(
        topic="Sản xuất Chip Silicon",
        claims=[
            ClaimItem(
                claim="Transistor bán dẫn có kích thước chỉ 3 nanomet siêu nhỏ.",
                evidence="Công nghệ quang khắc EUV hiện đại",
                is_critical=True,
            )
        ],
        confidence_score=0.98,
        entities=["chip", "transistor", "nanomet"],
    )

    # Script completely ignores the critical claim about 3 nanomet transistor
    narr = "Hôm nay chúng ta cùng đi dạo trong một nhà máy công nghệ cao để xem các cỗ máy hoạt động."
    scenes = [SceneNarration(scene_index=1, narration=narr, estimated_speech_duration_sec=6.0)]
    script = ScriptPlan(
        title="Chip",
        full_script=narr,
        scenes=scenes,
        total_word_count=len(narr.split()),
        estimated_total_duration_sec=6.0,
        hook_word_count=len(narr.split()),
    )
    report = gate.evaluate(script, fact_pack, target_duration_sec=6.0)
    assert any(v.rule_id == "RULE_06_UNSUPPORTED_FACT" and v.severity == "WARNING" for v in report.violations)


def test_rule_07_breathability_run_on_sentence():
    gate = ScriptQualityGate(max_sentence_words=35)
    # Sentence with 40 words and no punctuation
    run_on = " ".join(["từ"] * 40)
    scenes = [SceneNarration(scene_index=1, narration=run_on, estimated_speech_duration_sec=12.0)]
    script = ScriptPlan(
        title="RunOn",
        full_script=run_on,
        scenes=scenes,
        total_word_count=40,
        estimated_total_duration_sec=12.0,
        hook_word_count=40,
    )
    report = gate.evaluate(script, target_duration_sec=12.0)
    assert any(v.rule_id == "RULE_07_RUN_ON_SENTENCE" and v.severity == "WARNING" for v in report.violations)
