"""
Dimension & Version Safety Unit Test Suite (Phase 2.5 - Sections 2, 4, 10)
Verifies:
- Strict dimension isolation: search_similar raises or isolates vectors of differing dimensions.
- Never compares vectors of differing dimensions (e.g. 256 vs 768).
- Model and version isolation: searches only match the requested model and version.
- Explicit retrieval_mode exposure (CLOUD_SEMANTIC vs LEXICAL_FALLBACK).
- Accurate latency tracking breakdown on search results.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from production.contracts import RetrievalMode, SceneSearchFilter, SourceSceneRecord
from production.repositories.source_repository import DevelopmentBruteForceRepository
from production.embedding_service import (
    HashedLexicalEmbeddingProvider,
    compute_cosine_similarity,
    embedding_service,
)


def test_cosine_similarity_dimension_safety():
    vec_256 = [0.1] * 256
    vec_768 = [0.1] * 768
    vec_256_b = [0.2] * 256

    # Comparing mismatched dimensions returns 0.0 without crash
    sim_mismatch = compute_cosine_similarity(vec_256, vec_768)
    assert sim_mismatch == 0.0

    # Matching dimensions computes valid cosine
    sim_valid = compute_cosine_similarity(vec_256, vec_256_b)
    assert 0.99 <= sim_valid <= 1.01


def test_brute_force_repo_strict_dimension_isolation(tmp_path: Path):
    repo = DevelopmentBruteForceRepository(storage_dir=tmp_path / "embeddings")

    # Save a 256-dim embedding
    repo.save_embedding(
        scene_id="scn_256",
        vector=[0.1] * 256,
        text_repr="test 256",
        model_name="hashed-lexical-v1",
        provider="local",
        dimensions=256,
        embedding_version="v1",
    )

    # Save a 768-dim embedding
    repo.save_embedding(
        scene_id="scn_768",
        vector=[0.2] * 768,
        text_repr="test 768",
        model_name="gemini-embedding-2",
        provider="gemini",
        dimensions=768,
        embedding_version="v1",
    )

    # Search with 256-dim query vector for hashed-lexical-v1
    results_256 = repo.search_similar(
        query_vector=[0.1] * 256,
        provider="local",
        model="hashed-lexical-v1",
        dimensions=256,
        embedding_version="v1",
    )

    assert len(results_256) == 1
    assert results_256[0][0] == "scn_256"
    assert "scn_768" not in [r[0] for r in results_256]

    # Searching with 768-dim query vector for gemini-embedding-2
    results_768 = repo.search_similar(
        query_vector=[0.2] * 768,
        provider="gemini",
        model="gemini-embedding-2",
        dimensions=768,
        embedding_version="v1",
    )

    assert len(results_768) == 1
    assert results_768[0][0] == "scn_768"
    assert "scn_256" not in [r[0] for r in results_768]

    # Passing mismatched dimensions must raise ValueError
    with pytest.raises(ValueError, match="Query vector dimension.*does not match expected dimensions"):
        repo.search_similar(
            query_vector=[0.1] * 256,
            provider="gemini",
            model="gemini-embedding-2",
            dimensions=768,  # Expected 768 but passed 256
            embedding_version="v1",
        )


def test_retrieval_mode_and_latency_telemetry():
    from production.repositories.source_repository import get_scene_repository, get_source_repository
    from production.contracts import SourceAssetRecord, RightsState, SourceIngestState
    source_repo = get_source_repository()
    scene_repo = get_scene_repository()
    if not source_repo.get("src_telemetry_parent"):
        source_repo.save(
            SourceAssetRecord(
                id="src_telemetry_parent",
                source_type="video",
                fingerprint="fp_telemetry_parent",
                duration=10.0,
                width=1920,
                height=1080,
                fps=30.0,
                rights_state=RightsState.OWNED,
                ingest_status=SourceIngestState.INGESTED,
            )
        )
    test_scene = SourceSceneRecord(
        id="scn_telemetry_test",
        source_id="src_telemetry_parent",
        start_sec=0.0,
        end_sec=5.0,
        duration_sec=5.0,
        fingerprint="fp_telemetry_test",
        description="Master carpenter working with oak wood in timber workshop",
        technical_quality_score=0.9,
    )
    scene_repo.save(test_scene)
    embedding_service.index_scene_embedding(test_scene)

    # Execute a search query with local provider
    results = embedding_service.search_scenes("carpenter working with wood", top_k=3)
    assert len(results) > 0

    first = results[0]
    # Verify retrieval mode is explicitly exposed
    assert first.retrieval_mode in (RetrievalMode.LEXICAL_FALLBACK, RetrievalMode.CLOUD_SEMANTIC)

    # Verify latency telemetry is recorded
    assert first.latency_ms > 0.0
    evidence = first.match_evidence
    assert "vector_search_ms" in evidence
    assert "rerank_ms" in evidence
    assert "total_ms" in evidence
    assert "embedding_model" in evidence
    assert "embedding_dimensions" in evidence
    assert "embedding_version" in evidence
