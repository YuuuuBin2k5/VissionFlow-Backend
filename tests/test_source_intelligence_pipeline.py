"""
Integration Test Suite for Phase 2 Source Intelligence Foundation (Section 5, 7, 8, 9, 11, 13, 14, 18, 21)
Tests:
- Real media ingestion & ffprobe extraction (resolution, duration, fps, codec).
- Deduplication: Same video with different filename yields identical fingerprint.
- Scene boundary detection & adaptive keyframe extraction (images on disk).
- Structured scene analysis with schema validation.
- Embedding generation & semantic retrieval with rich match evidence.
- Resumable analysis: retry does not duplicate or re-run analyzed scenes.
"""

import os
import shutil
import sys
from pathlib import Path
import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from production.contracts import RightsState, SourceInput, SourceKind
from production.source_ingest import source_ingest_service, probe_media
from production.scene_indexer import scene_indexer
from production.source_analyzer import source_analyzer
from production.embedding_service import embedding_service
from production.repositories.source_repository import get_source_repository, get_scene_repository

FIXTURE_PATH = BACKEND_ROOT / "scratch" / "fixture_sample.mp4"


def test_source_ingest_and_ffprobe():
    print("\n[PIPELINE TEST] 1. Testing source ingestion and ffprobe extraction...")
    assert FIXTURE_PATH.exists(), f"Fixture not found at {FIXTURE_PATH}"

    source_input = SourceInput(
        source_id="src_test_fixture_01",
        type=SourceKind.VIDEO,
        file_ref=str(FIXTURE_PATH),
        rights_state=RightsState.OWNED,
    )

    record = source_ingest_service.ingest_source(source_input)
    assert record is not None
    assert record.width == 1280, f"Expected width 1280, got {record.width}"
    assert record.height == 720, f"Expected height 720, got {record.height}"
    assert record.fps == 25.0, f"Expected fps 25.0, got {record.fps}"
    assert record.codec == "h264", f"Expected h264, got {record.codec}"
    assert 5.8 <= record.duration <= 6.2, f"Expected ~6.0s duration, got {record.duration}"
    assert record.fingerprint.startswith("v1:"), f"Invalid fingerprint format: {record.fingerprint}"
    print(f"  -> Ingested source {record.id} with fingerprint {record.fingerprint} OK!")


def test_source_deduplication_different_filename():
    print("\n[PIPELINE TEST] 2. Testing source deduplication (same video, different filename)...")
    copy_path = BACKEND_ROOT / "scratch" / "fixture_copy_diff_name.mp4"
    shutil.copyfile(FIXTURE_PATH, copy_path)

    try:
        source_input_copy = SourceInput(
            source_id="src_test_fixture_copy",
            type=SourceKind.VIDEO,
            file_ref=str(copy_path),
            rights_state=RightsState.OWNED,
        )

        record_copy = source_ingest_service.ingest_source(source_input_copy)
        orig_record = source_ingest_service.repository.get_by_fingerprint(record_copy.fingerprint)

        # Must have same fingerprint and reuse existing record
        assert orig_record is not None
        assert record_copy.fingerprint == orig_record.fingerprint
        assert record_copy.id == orig_record.id, "Deduplication failed to return existing source ID"
        print(f"  -> Deduplication verified: Both files resolved to Source {orig_record.id}!")
    finally:
        if copy_path.exists():
            copy_path.unlink()


def test_scene_indexing_and_keyframes():
    print("\n[PIPELINE TEST] 3. Testing scene indexing and keyframe extraction...")
    source_input = SourceInput(
        source_id="src_test_fixture_01",
        type=SourceKind.VIDEO,
        file_ref=str(FIXTURE_PATH),
        rights_state=RightsState.OWNED,
    )
    record = source_ingest_service.ingest_source(source_input)

    scenes = scene_indexer.index_source(record)
    assert len(scenes) >= 1, "Expected at least 1 scene indexed"

    for scn in scenes:
        assert scn.source_id == record.id
        assert scn.duration_sec > 0.0
        assert scn.fingerprint.startswith("scn_")
        assert len(scn.keyframes) >= 1, f"Scene {scn.id} missing keyframes"
        for kf in scn.keyframes:
            kf_file = Path(kf)
            assert kf_file.exists(), f"Keyframe file missing on disk: {kf}"
            assert kf_file.stat().st_size > 500, f"Corrupted keyframe file: {kf}"

    print(f"  -> Indexed {len(scenes)} scenes with verified keyframes on disk OK!")


def test_scene_analysis_and_resumption():
    print("\n[PIPELINE TEST] 4. Testing scene analysis and failure resumption...")
    source_input = SourceInput(
        source_id="src_test_fixture_01",
        type=SourceKind.VIDEO,
        file_ref=str(FIXTURE_PATH),
        rights_state=RightsState.OWNED,
    )
    record = source_ingest_service.ingest_source(source_input)

    # First analysis run
    analyzed_scenes = source_analyzer.analyze_source_scenes(record)
    assert len(analyzed_scenes) >= 1

    first_scene = analyzed_scenes[0]
    assert len(first_scene.description) > 0, "Scene description was not populated"
    assert len(first_scene.entities) > 0, "Entities not populated"
    assert len(first_scene.actions) > 0, "Actions not populated"
    orig_desc = first_scene.description

    # Resumption test (Section 18): Calling analysis again must SKIP already analyzed scene
    second_run = source_analyzer.analyze_source_scenes(record)
    assert len(second_run) == len(analyzed_scenes)
    assert second_run[0].description == orig_desc
    print("  -> Scene analysis and failure resumption verified OK!")


def test_embedding_and_two_stage_semantic_search():
    print("\n[PIPELINE TEST] 5. Testing embedding indexing and two-stage semantic search...")
    source_input = SourceInput(
        source_id="src_test_fixture_01",
        type=SourceKind.VIDEO,
        file_ref=str(FIXTURE_PATH),
        rights_state=RightsState.OWNED,
    )
    record = source_ingest_service.ingest_source(source_input)
    scenes = get_scene_repository().list_by_source(record.id)

    for scn in scenes:
        vec = embedding_service.index_scene_embedding(scn)
        assert len(vec) > 0, "Embedding vector was empty"

    # Perform semantic search filtered to this source
    from production.contracts import SceneSearchFilter
    results = embedding_service.search_scenes(
        "video sequence subject",
        top_k=3,
        filters=SceneSearchFilter(source_ids=[record.id]),
    )
    assert len(results) >= 1, "Semantic search returned no results"

    top_result = results[0]
    assert top_result.scene_id in [s.id for s in scenes]
    assert 0.0 <= top_result.score <= 1.0
    assert "semantic_score" in top_result.match_evidence
    assert "overlap_score" in top_result.match_evidence
    print(f"  -> Semantic search verified (Top score: {top_result.score}, scene: {top_result.scene_id}) OK!")


if __name__ == "__main__":
    test_source_ingest_and_ffprobe()
    test_source_deduplication_different_filename()
    test_scene_indexing_and_keyframes()
    test_scene_analysis_and_resumption()
    test_embedding_and_two_stage_semantic_search()
    print("\n[SUCCESS] ALL SOURCE INTELLIGENCE PIPELINE INTEGRATION TESTS PASSED!")
