"""
Unit and Integration Tests for Phase 3.5 Hardening:
1. Research Provenance (InputOnly vs WebGrounded, EvidenceItem).
2. Claim-to-evidence Traceability (stable fact_xxx IDs, criticality, fact_refs).
3. Unsupported script claim detection (RULE_08 dangling fact_refs and ungrounded claims).
4. Story Archetype Flexibility (8 archetypes, dynamic beat ratios, inference).
5. Vietnamese Cross-Language Scene Retrieval Bridge & Telemetry.
6. AUTO / SCRIPT / JSON Input Modes, Security Guardrails, Stage Skipping, and Clean JSON Export.
"""

from __future__ import annotations

import pytest
from datetime import datetime

from production.contracts import (
    AutoVideoRequest,
    ClaimItem,
    EvidenceItem,
    FactPack,
    InputMode,
    QualityStatus,
    ProductionFormat,
    ProductionRun,
    ProductionRunStatus,
    ProductionStageRun,
    SceneNarration,
    ScriptPlan,
    StoryArchetype,
    StoryPlan,
    StageStatus,
)
from production.input_normalizer import (
    InputNormalizer,
    JSONNormalizer,
    ScriptParser,
    MAX_JSON_PAYLOAD_BYTES,
)
from production.research_service import (
    InputOnlyResearchProvider,
    LocalResearchProvider,
    WebGroundedResearchProvider,
)
from production.story_planner import ARCHETYPE_BEAT_RATIOS, infer_archetype, story_planner
from production.script_service import script_engine
from production.script_quality_gate import script_quality_gate
from production.embedding_service import VietnameseQueryTranslationBridge, embedding_service
from production.orchestrator import orchestrator, STAGE_REALITY_MAP
from production.repositories.run_repository import run_repository
from production.production_controller import _handle_export_run


# ===========================================================================
# 1. Research Provenance Tests
# ===========================================================================

def test_research_provenance_input_only():
    provider = InputOnlyResearchProvider()
    pack = provider.extract_fact_pack(
        instruction="Chế tác gốm sứ truyền thống Bát Tràng",
        source_transcripts=["Nghệ nhân chuốt đất sét trên bàn xoay thủ công."],
    )

    assert pack.research_mode == "SOURCE_EXTRACTION"
    assert pack.external_verification_performed is False
    assert pack.provider == "local_input_only"
    assert pack.source_count == 2
    assert len(pack.evidence_items) >= 2

    # Check stable IDs on evidence and claims
    for ev in pack.evidence_items:
        assert ev.id.startswith("ev_")
        assert ev.source_kind in ("USER_PROMPT", "SOURCE_DOCUMENT")

    for cl in pack.claims:
        assert cl.id.startswith("fact_")
        assert cl.criticality in ("HIGH", "MEDIUM", "LOW")
        assert len(cl.evidence_refs) >= 1
        assert cl.evidence_refs[0].startswith("ev_")


def test_research_provenance_web_grounded():
    provider = WebGroundedResearchProvider()
    pack = provider.extract_fact_pack("Tìm hiểu về kiến trúc nhà rông Tây Nguyên")

    assert pack.research_mode == "WEB_SEARCH"
    assert pack.external_verification_performed is True
    assert pack.provider == "web_grounded"
    for ev in pack.evidence_items:
        assert ev.source_kind == "WEB_SCRAPE"


# ===========================================================================
# 2. Contradiction & Claim-to-Evidence Traceability Tests
# ===========================================================================

def test_contradiction_detection_across_sources():
    provider = LocalResearchProvider()
    transcripts = [
        "Quy trình thủ công truyền thống an toàn tuyệt đối và bảo tồn giá trị xưa.",
        "Quy trình công nghiệp hiện đại nguy hiểm hơn nhưng sản lượng cao gấp nhiều lần.",
    ]
    pack = provider.extract_fact_pack(
        instruction="So sánh hai phương pháp chế tác",
        source_transcripts=transcripts,
    )

    assert len(pack.contradictions) >= 1
    assert any("an toàn" in c or "nguy hiểm" in c for c in pack.contradictions)

    # Script engine qualification
    story = story_planner.generate_story_plan(pack)
    script = script_engine.generate_script_plan(story, pack)
    # Check that development scene exists and has fact_refs
    assert len(script.scenes) >= 3
    for s in script.scenes:
        assert isinstance(s.fact_refs, list)


# ===========================================================================
# 3. Unsupported Script Claim Detection (RULE_08) Tests
# ===========================================================================

def test_rule_08_dangling_fact_ref():
    fact_pack = FactPack(
        topic="Mộng gỗ",
        claims=[
            ClaimItem(id="fact_001", claim="Khớp nối mộng gỗ không cần đinh", evidence="Truyền thống", is_critical=True),
        ],
    )
    scenes = [
        SceneNarration(
            scene_index=1,
            narration="Khám phá mộng gỗ không cần đinh.",
            fact_refs=["fact_999"],  # Does not exist in fact_pack!
        ),
    ]
    script = ScriptPlan(
        title="Test",
        full_script="Khám phá mộng gỗ không cần đinh.",
        scenes=scenes,
        total_word_count=7,
        estimated_total_duration_sec=2.5,
    )

    report = script_quality_gate.evaluate(script, fact_pack, target_duration_sec=10.0)
    assert report.status == QualityStatus.FAIL
    assert any(v.rule_id == "RULE_08_DANGLING_FACT_REF" and v.severity == "BLOCKER" for v in report.violations)


def test_rule_08_unsupported_numbers_and_absolutes():
    fact_pack = FactPack(
        topic="Tập luyện sức khỏe",
        claims=[
            ClaimItem(id="fact_001", claim="Đi bộ hàng ngày giúp cải thiện tuần hoàn máu.", evidence="Y khoa", is_critical=True),
        ],
    )

    # Extreme absolute hallucination
    scenes = [
        SceneNarration(
            scene_index=1,
            narration="Phương pháp này là độc nhất vô nhị và cam kết 100% chữa khỏi hoàn toàn mọi bệnh.",
            fact_refs=["fact_001"],
        ),
    ]
    script = ScriptPlan(
        title="Phương pháp",
        full_script=scenes[0].narration,
        scenes=scenes,
        total_word_count=len(scenes[0].narration.split()),
        estimated_total_duration_sec=4.0,
    )

    report = script_quality_gate.evaluate(script, fact_pack, target_duration_sec=10.0)
    assert report.status == QualityStatus.FAIL
    assert report.blocker_count >= 1
    assert any(v.rule_id == "RULE_08_SCRIPT_UNSUPPORTED_CLAIM" for v in report.violations)


# ===========================================================================
# 4. Story Archetype Flexibility Tests
# ===========================================================================

def test_story_archetype_inference():
    assert infer_archetype("Quy trình chế tạo gốm sứ") == StoryArchetype.PROCESS_EXPLAINER
    assert infer_archetype("Bí ẩn chưa có lời giải của hồ Loch Ness") == StoryArchetype.MYSTERY
    assert infer_archetype("Hành trình biến đổi trước và sau của căn nhà hoang") == StoryArchetype.TRANSFORMATION
    assert infer_archetype("Lịch sử phát triển và dòng thời gian của vi mạch") == StoryArchetype.TIMELINE
    assert infer_archetype("Nguyên nhân sâu xa và hậu quả của biến đổi khí hậu") == StoryArchetype.CAUSE_EFFECT
    assert infer_archetype("So sánh sự khác biệt giữa hai phương pháp") == StoryArchetype.COMPARISON
    assert infer_archetype("Điều tra vén màn sự thật về vụ mất tích") == StoryArchetype.INVESTIGATION
    assert infer_archetype("Khám phá vùng đất mới chưa từng được tiết lộ") == StoryArchetype.DISCOVERY


def test_archetype_dynamic_beat_ratios():
    fact_pack = FactPack(topic="Bí mật động cơ phản lực")
    # Force MYSTERY archetype
    plan = story_planner.generate_story_plan(fact_pack, target_duration_sec=60.0, archetype=StoryArchetype.MYSTERY)

    assert plan.archetype == StoryArchetype.MYSTERY
    assert plan.beat_ratios == ARCHETYPE_BEAT_RATIOS[StoryArchetype.MYSTERY]
    # Mystery has longer hook ratio (20%)
    assert plan.beat_ratios["hook"] == 0.20
    assert len(plan.beats) == 5


# ===========================================================================
# 5. Vietnamese Cross-Language Retrieval Bridge Tests
# ===========================================================================

def test_vietnamese_query_translation_bridge():
    enriched, used, translated = VietnameseQueryTranslationBridge.translate_and_enrich("thợ mộc đục mộng gỗ")
    assert used is True
    assert translated is not None
    assert "carpenter" in translated
    assert "chisel" in translated
    assert "joinery" in translated
    assert "thợ mộc" in enriched

    # Non-Vietnamese English query should remain unmodified
    en_query = "cleanroom silicon wafer"
    enriched_en, used_en, trans_en = VietnameseQueryTranslationBridge.translate_and_enrich(en_query)
    assert used_en is False
    assert enriched_en == en_query


# ===========================================================================
# 6. AUTO / SCRIPT / JSON Input Modes & Security Tests
# ===========================================================================

def test_script_parser_and_input_mode():
    raw_script = (
        "Đây là câu mở đầu thu hút sự chú ý của mọi người.\n\n"
        "Đoạn văn tiếp theo đi sâu vào chi tiết kỹ thuật tinh xảo.\n\n"
        "Và đây là đoạn kết thúc truyền cảm hứng mạnh mẽ."
    )
    req = InputNormalizer.normalize(raw_script=raw_script, input_mode="SCRIPT")
    assert req.input_mode == InputMode.SCRIPT
    assert req.raw_script == raw_script

    parsed = ScriptParser.parse(raw_script)
    assert len(parsed.scenes) == 3
    assert parsed.scenes[0].scene_index == 1
    assert parsed.scenes[0].narration == "Đây là câu mở đầu thu hút sự chú ý của mọi người."
    assert parsed.scenes[0].estimated_speech_duration_sec > 0.0


def test_json_mode_security_path_traversal():
    bad_payload = {
        "title": "Malicious JSON",
        "file_ref": "../../etc/passwd",
        "scenes": [],
    }
    with pytest.raises(ValueError, match="Path traversal"):
        JSONNormalizer.validate_security(bad_payload)


def test_json_mode_security_system_paths():
    bad_payload = {
        "title": "System Access",
        "storage_ref": "C:\\Windows\\system32\\cmd.exe",
    }
    with pytest.raises(ValueError, match="Access to internal system paths"):
        JSONNormalizer.validate_security(bad_payload)


def test_json_mode_security_file_scheme():
    bad_payload = {
        "uri": "file:///var/log/syslog",
    }
    with pytest.raises(ValueError, match="file:// URI scheme is forbidden"):
        JSONNormalizer.validate_security(bad_payload)


def test_json_mode_security_payload_size_limit():
    large_payload = {"data": "x" * (MAX_JSON_PAYLOAD_BYTES + 100)}
    with pytest.raises(ValueError, match="exceeds maximum allowed size"):
        JSONNormalizer.validate_security(large_payload)


# ===========================================================================
# 7. Orchestrator Stage Skipping & Clean JSON Export Integration Tests
# ===========================================================================

@pytest.mark.anyio
async def test_orchestrator_script_mode_stage_skipping():
    raw_script = (
        "Bạn có biết công nghệ đúc vi mạch silicon đạt độ chính xác tới nanômét?\n\n"
        "Mỗi bóng bán dẫn được khắc bằng tia cực tím sâu trong phòng sạch chuẩn quốc tế.\n\n"
        "Đó là nền tảng của toàn bộ thế giới số ngày nay."
    )
    req = InputNormalizer.normalize(raw_script=raw_script, input_mode=InputMode.SCRIPT)
    run = orchestrator.create_run(req)

    await orchestrator._execute_pipeline(run.id)

    updated_run = run_repository.get(run.id)
    assert updated_run is not None

    # Check stage skipping semantics
    research_stage = next((s for s in updated_run.stages if s.stage_name == "research_story"), None)
    assert research_stage is not None
    assert research_stage.status == StageStatus.SKIPPED
    assert research_stage.error_code == "SKIPPED_BY_INPUT_MODE"

    # Check script generation and quality gate executed
    script_stage = next((s for s in updated_run.stages if s.stage_name == "script_generation"), None)
    assert script_stage is not None
    assert script_stage.status == StageStatus.COMPLETED

    gate_stage = next((s for s in updated_run.stages if s.stage_name == "script_quality_gate"), None)
    assert gate_stage is not None
    assert gate_stage.status == StageStatus.COMPLETED

    # Canonical timing check: actual_duration_sec must NOT be populated with estimates
    if updated_run.editor_plan:
        for scn in updated_run.editor_plan.scenes:
            if STAGE_REALITY_MAP.get("tts_timing") == "REAL":
                assert scn.actual_duration_sec is not None and scn.actual_duration_sec > 0, "actual_duration_sec must be populated when measured via ffprobe TTS"
            else:
                assert scn.actual_duration_sec is None, "actual_duration_sec must remain None until measured via ffprobe TTS"


def test_clean_json_export_endpoint():
    req = InputNormalizer.normalize(raw_instruction="Kiểm thử xuất JSON sạch", requested_format="short")
    run = orchestrator.create_run(req)

    # Attach sample script and editor plan
    run.script_plan = ScriptPlan(
        title="Xuất JSON",
        full_script="Lời thoại kịch bản mẫu.",
        scenes=[
            SceneNarration(scene_index=1, narration="Lời thoại kịch bản mẫu.", estimated_speech_duration_sec=2.5, fact_refs=["fact_001"])
        ],
        total_word_count=5,
        estimated_total_duration_sec=2.5,
    )
    run_repository.update(run)

    exported = _handle_export_run(run.id)
    assert exported["export_version"] == "1.0"
    assert "script_plan" in exported
    assert exported["script_plan"]["title"] == "Xuất JSON"
    # Ensure no internal DB paths or server filesystem references are leaked
    exported_str = str(exported)
    assert "C:\\" not in exported_str
    assert "storage_ref" not in exported_str
