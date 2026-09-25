from production.auto_production_adapter import (
    VALID_VIDEO_GENRES,
    adapt_auto_production_to_modal_contract,
)
from production.channel_profile import channel_profile_registry
from production.contracts import AutoVideoRequest, ProductionRun
from production.orchestrator import ProductionOrchestrator


def _snapshot(profile_id: str, overrides=None):
    return {
        "id": "run_contract_audit",
        "channel_profile_id": profile_id,
        "request": {
            "channel_profile_id": profile_id,
            "instruction": "Bí ẩn khảo cổ từ một chiếc răng cổ",
            "overrides": overrides or {},
        },
        "script_plan": {
            "title": "Dấu vết trên chiếc răng cổ",
            "full_script": "Một chiếc răng giữ lại dấu vết bất thường từ quá khứ.",
            "scenes": [
                {
                    "scene_index": 1,
                    "narration": "Một chiếc răng giữ lại dấu vết bất thường từ quá khứ.",
                    "visual_cue": "Ancient tooth macro",
                }
            ],
        },
        "retention_lint": {"first_10s_viability": 9},
        "editorial_learning_record": {"information_gain_count": 4},
    }


def _yuubin_genre(title: str, script: str):
    snapshot = _snapshot("goc_chiem_nghiem_yuubin")
    snapshot["script_plan"]["title"] = title
    snapshot["script_plan"]["full_script"] = script
    snapshot["script_plan"]["scenes"][0]["narration"] = script
    return adapt_auto_production_to_modal_contract(snapshot)["video_genre"]


def test_yuubin_renderer_contract_uses_supported_genre_and_locked_voice():
    payload = adapt_auto_production_to_modal_contract(
        _snapshot(
            "goc_chiem_nghiem_yuubin",
            {
                "video_genre": "documentary",
                "voice_code": "vi-VN-HoaiMyNeural",
                "voice_rate": 0.75,
            },
        )
    )

    assert payload["video_genre"] in VALID_VIDEO_GENRES
    assert payload["video_genre"] != "documentary"
    assert payload["voice"] == "vi-VN-NamMinhNeural"
    assert payload["voice_code"] == "vi-VN-NamMinhNeural"
    assert payload["voice_rate"] == 1.12
    assert channel_profile_registry.get_profile("goc_chiem_nghiem_yuubin").voice_rate == 1.12

    run = ProductionRun(
        id="run_yuubin_voice",
        request=AutoVideoRequest(
            request_id="req_yuubin_voice",
            instruction="Contract audit",
            channel_profile_id="goc_chiem_nghiem_yuubin",
        ),
    )
    assert ProductionOrchestrator._voice_rate_for_run(run) == 1.12


def test_other_channel_voice_behavior_is_unchanged():
    payload = adapt_auto_production_to_modal_contract(
        _snapshot(
            "asinmochii_boni",
            {"voice_code": "en-US-ChristopherNeural", "voice_rate": 0.85},
        )
    )

    assert payload["voice"] == "en-US-ChristopherNeural"
    assert payload["voice_code"] == "en-US-ChristopherNeural"
    assert "voice_rate" not in payload
    assert "video_genre" not in payload

    run = ProductionRun(
        id="run_other_voice",
        request=AutoVideoRequest(
            request_id="req_other_voice",
            instruction="Contract audit",
            channel_profile_id="asinmochii_boni",
        ),
    )
    assert ProductionOrchestrator._voice_rate_for_run(run) == 1.0


def test_editorial_diagnostics_are_isolated_from_renderer_payload():
    payload = adapt_auto_production_to_modal_contract(
        _snapshot("goc_chiem_nghiem_yuubin")
    )

    forbidden = {
        "retention_lint",
        "first_10s_viability",
        "background_tax",
        "information_gain_count",
        "editorial_learning_record",
    }
    assert forbidden.isdisjoint(payload)


def test_yuubin_archaeological_tomb_maps_to_mystery_history():
    assert _yuubin_genre("Ngôi mộ bị lãng quên", "Các nhà khảo cổ mở một lăng mộ cổ.") == "MYSTERY_PARANORMAL_HISTORY"


def test_yuubin_ancient_artifact_maps_to_mystery_history():
    assert _yuubin_genre("Cổ vật dưới nền đá", "Hiện vật này là bằng chứng lịch sử.") == "MYSTERY_PARANORMAL_HISTORY"


def test_yuubin_fossil_discovery_maps_to_science():
    assert _yuubin_genre("Phát hiện hóa thạch", "Mẫu hóa thạch hé lộ một loài cổ sinh.") == "SCIENCE_TECH_FUTURE"


def test_yuubin_dna_evidence_maps_to_science():
    assert _yuubin_genre("Bằng chứng DNA", "Phép đo DNA xác định quan hệ di truyền.") == "SCIENCE_TECH_FUTURE"


def test_yuubin_explicit_life_lesson_maps_to_philosophy():
    assert _yuubin_genre("Bài học cuộc sống", "Một bài học nhân sinh về lòng kiên nhẫn.") == "PHILOSOPHY_LIFE_LESSON"


def test_yuubin_unknown_topic_falls_back_to_mystery_history():
    assert _yuubin_genre("Một phát hiện chưa rõ", "Chi tiết này chưa thể được phân loại.") == "MYSTERY_PARANORMAL_HISTORY"


def test_human_payoff_does_not_override_archaeology_genre():
    assert _yuubin_genre(
        "Bí ẩn khảo cổ trong lăng mộ",
        "Hiện vật trong ngôi mộ là bằng chứng lịch sử. Cuối cùng, nó kể về cuộc sống của một người vô danh.",
    ) == "MYSTERY_PARANORMAL_HISTORY"
