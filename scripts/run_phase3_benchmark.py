"""
Phase 3 Script Reliability & Editorial Benchmark (Phase 3.5)
Runs 8 diverse scenarios covering:
1. Process Explainer (Woodworking craft)
2. Mystery (Unsolved riddle / paradox)
3. Timeline (Evolution & historical milestones)
4. Factory / Industrial (Cleanroom silicon wafer manufacturing)
5. Article / Travel (Alpine mountain landscape)
6. Contradiction / Conflict (Conflicting source claims qualified by ScriptEngine)
7. Unsupported Claim Detection (Testing RULE_08 hallucinated 100% cure -> BLOCKER)
8. SCRIPT Input Mode (Plain text voiceover input with stage skipping)
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

backend_root = Path(__file__).resolve().parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from production.contracts import (
    ClaimItem,
    FactPack,
    InputMode,
    QualityStatus,
    SceneNarration,
    ScriptPlan,
    StoryArchetype,
    StageStatus,
)
from production.input_normalizer import InputNormalizer, ScriptParser
from production.research_service import LocalResearchProvider, WebGroundedResearchProvider
from production.story_planner import infer_archetype, story_planner
from production.script_service import script_engine
from production.script_quality_gate import script_quality_gate


def run_phase3_benchmark() -> Dict[str, Any]:
    print("\n=======================================================")
    print("Running Phase 3 Editorial & Reliability Benchmark (8 Scenarios)")
    print("=======================================================\n")

    results = []
    research_provider = LocalResearchProvider()

    # -----------------------------------------------------------------------
    # Scenario 1: Process Explainer
    # -----------------------------------------------------------------------
    t0 = time.perf_counter()
    s1_topic = "Quy trình chế tác mộng gỗ Kigumi thủ công truyền thống"
    s1_fact = research_provider.extract_fact_pack(s1_topic)
    s1_story = story_planner.generate_story_plan(s1_fact, target_duration_sec=55.0)
    s1_script = script_engine.generate_script_plan(s1_story, s1_fact)
    s1_gate = script_quality_gate.evaluate(s1_script, s1_fact, target_duration_sec=55.0)
    s1_time = round((time.perf_counter() - t0) * 1000, 1)

    s1_pass = s1_story.archetype == StoryArchetype.PROCESS_EXPLAINER and s1_gate.status in (QualityStatus.PASS, QualityStatus.WARN)
    results.append({
        "scenario": 1,
        "name": "Process Explainer (Kigumi)",
        "archetype": s1_story.archetype.value,
        "scenes_count": len(s1_script.scenes),
        "total_words": s1_script.total_word_count,
        "gate_status": s1_gate.status.value,
        "gate_score": s1_gate.score,
        "provenance_mode": s1_fact.research_mode,
        "latency_ms": s1_time,
        "passed": s1_pass,
    })
    print(f"Scenario 1 (Process Explainer): {'[PASS]' if s1_pass else '[FAIL]'} - Archetype: {s1_story.archetype.value}, Gate: {s1_gate.status.value}, Score: {s1_gate.score}")

    # -----------------------------------------------------------------------
    # Scenario 2: Mystery
    # -----------------------------------------------------------------------
    t0 = time.perf_counter()
    s2_topic = "Bí ẩn chưa có lời giải đằng sau hồ nước đổi màu kỳ lạ"
    s2_fact = research_provider.extract_fact_pack(s2_topic)
    s2_story = story_planner.generate_story_plan(s2_fact, target_duration_sec=50.0)
    s2_script = script_engine.generate_script_plan(s2_story, s2_fact)
    s2_gate = script_quality_gate.evaluate(s2_script, s2_fact, target_duration_sec=50.0)
    s2_time = round((time.perf_counter() - t0) * 1000, 1)

    s2_pass = s2_story.archetype == StoryArchetype.MYSTERY and s2_gate.status in (QualityStatus.PASS, QualityStatus.WARN)
    results.append({
        "scenario": 2,
        "name": "Mystery (Unsolved Riddle)",
        "archetype": s2_story.archetype.value,
        "scenes_count": len(s2_script.scenes),
        "total_words": s2_script.total_word_count,
        "gate_status": s2_gate.status.value,
        "gate_score": s2_gate.score,
        "provenance_mode": s2_fact.research_mode,
        "latency_ms": s2_time,
        "passed": s2_pass,
    })
    print(f"Scenario 2 (Mystery): {'[PASS]' if s2_pass else '[FAIL]'} - Archetype: {s2_story.archetype.value}, Gate: {s2_gate.status.value}")

    # -----------------------------------------------------------------------
    # Scenario 3: Timeline
    # -----------------------------------------------------------------------
    t0 = time.perf_counter()
    s3_topic = "Dòng thời gian lịch sử và các giai đoạn tiến hóa của vi mạch bán dẫn"
    s3_fact = research_provider.extract_fact_pack(s3_topic)
    s3_story = story_planner.generate_story_plan(s3_fact, target_duration_sec=60.0)
    s3_script = script_engine.generate_script_plan(s3_story, s3_fact)
    s3_gate = script_quality_gate.evaluate(s3_script, s3_fact, target_duration_sec=60.0)
    s3_time = round((time.perf_counter() - t0) * 1000, 1)

    s3_pass = s3_story.archetype == StoryArchetype.TIMELINE and s3_gate.status in (QualityStatus.PASS, QualityStatus.WARN)
    results.append({
        "scenario": 3,
        "name": "Timeline (Semiconductor History)",
        "archetype": s3_story.archetype.value,
        "scenes_count": len(s3_script.scenes),
        "total_words": s3_script.total_word_count,
        "gate_status": s3_gate.status.value,
        "gate_score": s3_gate.score,
        "provenance_mode": s3_fact.research_mode,
        "latency_ms": s3_time,
        "passed": s3_pass,
    })
    print(f"Scenario 3 (Timeline): {'[PASS]' if s3_pass else '[FAIL]'} - Archetype: {s3_story.archetype.value}, Gate: {s3_gate.status.value}")

    # -----------------------------------------------------------------------
    # Scenario 4: Factory / Cleanroom
    # -----------------------------------------------------------------------
    t0 = time.perf_counter()
    s4_topic = "Quy trình đúc vi mạch silicon phòng sạch cấp độ cao"
    s4_fact = research_provider.extract_fact_pack(s4_topic)
    s4_story = story_planner.generate_story_plan(s4_fact, target_duration_sec=55.0)
    s4_script = script_engine.generate_script_plan(s4_story, s4_fact)
    s4_gate = script_quality_gate.evaluate(s4_script, s4_fact, target_duration_sec=55.0)
    s4_time = round((time.perf_counter() - t0) * 1000, 1)

    s4_pass = s4_gate.status in (QualityStatus.PASS, QualityStatus.WARN) and len(s4_script.scenes) >= 4
    results.append({
        "scenario": 4,
        "name": "Factory / Cleanroom Fabrication",
        "archetype": s4_story.archetype.value,
        "scenes_count": len(s4_script.scenes),
        "total_words": s4_script.total_word_count,
        "gate_status": s4_gate.status.value,
        "gate_score": s4_gate.score,
        "provenance_mode": s4_fact.research_mode,
        "latency_ms": s4_time,
        "passed": s4_pass,
    })
    print(f"Scenario 4 (Factory Cleanroom): {'[PASS]' if s4_pass else '[FAIL]'} - Gate: {s4_gate.status.value}")

    # -----------------------------------------------------------------------
    # Scenario 5: Article / Alpine Landscape
    # -----------------------------------------------------------------------
    t0 = time.perf_counter()
    s5_topic = "Khám phá đỉnh núi tuyết Alps hùng vĩ từ góc nhìn trên cao"
    s5_fact = research_provider.extract_fact_pack(s5_topic)
    s5_story = story_planner.generate_story_plan(s5_fact, target_duration_sec=45.0)
    s5_script = script_engine.generate_script_plan(s5_story, s5_fact)
    s5_gate = script_quality_gate.evaluate(s5_script, s5_fact, target_duration_sec=45.0)
    s5_time = round((time.perf_counter() - t0) * 1000, 1)

    s5_pass = s5_gate.status in (QualityStatus.PASS, QualityStatus.WARN)
    results.append({
        "scenario": 5,
        "name": "Article / Alpine Nature",
        "archetype": s5_story.archetype.value,
        "scenes_count": len(s5_script.scenes),
        "total_words": s5_script.total_word_count,
        "gate_status": s5_gate.status.value,
        "gate_score": s5_gate.score,
        "provenance_mode": s5_fact.research_mode,
        "latency_ms": s5_time,
        "passed": s5_pass,
    })
    print(f"Scenario 5 (Article Nature): {'[PASS]' if s5_pass else '[FAIL]'} - Gate: {s5_gate.status.value}")

    # -----------------------------------------------------------------------
    # Scenario 6: Contradiction / Conflict Qualification
    # -----------------------------------------------------------------------
    t0 = time.perf_counter()
    transcripts = [
        "Phương pháp thủ công truyền thống an toàn tuyệt đối và đạt độ chuẩn xác cao.",
        "Phương pháp công nghiệp nguy hiểm hơn nhưng cho năng suất gấp mười lần.",
    ]
    s6_fact = research_provider.extract_fact_pack(
        instruction="Chế tác gỗ thủ công và công nghiệp",
        source_transcripts=transcripts,
    )
    s6_story = story_planner.generate_story_plan(s6_fact, target_duration_sec=55.0)
    s6_script = script_engine.generate_script_plan(s6_story, s6_fact)
    s6_gate = script_quality_gate.evaluate(s6_script, s6_fact, target_duration_sec=55.0)
    s6_time = round((time.perf_counter() - t0) * 1000, 1)

    has_contradiction = len(s6_fact.contradictions) > 0
    s6_pass = has_contradiction and s6_gate.status in (QualityStatus.PASS, QualityStatus.WARN)
    results.append({
        "scenario": 6,
        "name": "Contradiction Qualification",
        "contradictions_found": s6_fact.contradictions,
        "gate_status": s6_gate.status.value,
        "latency_ms": s6_time,
        "passed": s6_pass,
    })
    print(f"Scenario 6 (Contradiction): {'[PASS]' if s6_pass else '[FAIL]'} - Contradictions: {len(s6_fact.contradictions)}")

    # -----------------------------------------------------------------------
    # Scenario 7: Unsupported Script Claim Detection (Negative Test)
    # -----------------------------------------------------------------------
    t0 = time.perf_counter()
    s7_fact = research_provider.extract_fact_pack("Phương pháp tập thể dục nhẹ")
    # Fabricate a script containing hallucinated extreme claims and 100% cure
    hallucinated_scenes = [
        SceneNarration(
            scene_index=1,
            narration="Bài tập này cam kết 100% chữa khỏi hoàn toàn mọi căn bệnh nan y.",
            estimated_speech_duration_sec=4.0,
            fact_refs=["fact_001"],
        ),
        SceneNarration(
            scene_index=2,
            narration="Đây là phương pháp số 1 thế giới mang lại hiệu quả 99.9% ngay sau 1 ngày.",
            estimated_speech_duration_sec=5.0,
            fact_refs=["fact_001"],
        ),
    ]
    hallucinated_full = " ".join(s.narration for s in hallucinated_scenes)
    s7_script = ScriptPlan(
        title="Phương pháp thần kỳ",
        full_script=hallucinated_full,
        scenes=hallucinated_scenes,
        total_word_count=len(hallucinated_full.split()),
        estimated_total_duration_sec=9.0,
        hook_word_count=len(hallucinated_scenes[0].narration.split()),
    )
    s7_gate = script_quality_gate.evaluate(s7_script, s7_fact, target_duration_sec=10.0)
    s7_time = round((time.perf_counter() - t0) * 1000, 1)

    # Must detect RULE_08_SCRIPT_UNSUPPORTED_CLAIM and result in FAIL (BLOCKER)
    rule_08_violations = [v for v in s7_gate.violations if v.rule_id == "RULE_08_SCRIPT_UNSUPPORTED_CLAIM" and v.severity == "BLOCKER"]
    s7_pass = s7_gate.status == QualityStatus.FAIL and len(rule_08_violations) >= 1
    results.append({
        "scenario": 7,
        "name": "Unsupported Claim Detection (Negative Guardrail)",
        "gate_status": s7_gate.status.value,
        "blocker_count": s7_gate.blocker_count,
        "detected_rule_08_violations": [v.message for v in rule_08_violations],
        "latency_ms": s7_time,
        "passed": s7_pass,
    })
    print(f"Scenario 7 (Unsupported Guardrail): {'[PASS]' if s7_pass else '[FAIL]'} - Blockers: {s7_gate.blocker_count} (RULE_08 caught: {len(rule_08_violations)})")

    # -----------------------------------------------------------------------
    # Scenario 8: Raw Script Input (SCRIPT Mode)
    # -----------------------------------------------------------------------
    t0 = time.perf_counter()
    raw_voiceover = (
        "Bạn có bao giờ tự hỏi làm sao một hạt cát nhỏ có thể biến thành bộ não siêu việt của máy tính?\n\n"
        "Tất cả bắt đầu từ cát thạch anh tinh khiết, được nung chảy ở 2000 độ C để tạo ra thanh silicon nguyên chất.\n\n"
        "Sau đó, các cỗ máy quang khắc cực tím sẽ khắc hàng tỷ bóng bán dẫn siêu nhỏ lên bề mặt tấm wafer.\n\n"
        "Đó chính là kỳ quan công nghệ của nhân loại. Hãy đăng ký kênh để đón xem những tập tiếp theo!"
    )
    s8_request = InputNormalizer.normalize(
        raw_script=raw_voiceover,
        input_mode=InputMode.SCRIPT,
        requested_format="short",
    )
    s8_parsed_script = ScriptParser.parse(raw_voiceover)
    s8_gate = script_quality_gate.evaluate(s8_parsed_script, fact_pack=None, target_duration_sec=45.0)
    s8_time = round((time.perf_counter() - t0) * 1000, 1)

    s8_pass = (
        s8_request.input_mode == InputMode.SCRIPT
        and len(s8_parsed_script.scenes) == 4
        and s8_gate.status in (QualityStatus.PASS, QualityStatus.WARN)
    )
    results.append({
        "scenario": 8,
        "name": "SCRIPT Mode (Direct Voiceover Input)",
        "input_mode": s8_request.input_mode.value,
        "scenes_parsed": len(s8_parsed_script.scenes),
        "total_words": s8_parsed_script.total_word_count,
        "gate_status": s8_gate.status.value,
        "latency_ms": s8_time,
        "passed": s8_pass,
    })
    print(f"Scenario 8 (SCRIPT Mode): {'[PASS]' if s8_pass else '[FAIL]'} - Scenes: {len(s8_parsed_script.scenes)}, Words: {s8_parsed_script.total_word_count}, Gate: {s8_gate.status.value}")

    passed_count = sum(1 for r in results if r["passed"])
    summary = {
        "total_scenarios": len(results),
        "passed_scenarios": passed_count,
        "pass_rate_pct": round(passed_count / len(results) * 100, 1),
        "scenarios": results,
    }

    print("\n-------------------------------------------------------")
    print(f"Phase 3 Editorial Benchmark Summary: {passed_count}/{len(results)} Passed ({summary['pass_rate_pct']}%)")
    print("=======================================================\n")
    return summary


if __name__ == "__main__":
    summary = run_phase3_benchmark()
    with open("scripts/phase3_benchmark_results.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print("Phase 3 benchmark results saved to scripts/phase3_benchmark_results.json")
