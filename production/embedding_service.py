"""
Embedding Service & Two-Stage Semantic Scene Retrieval (Phase 2 & Phase 2.5)
Implements:
- Controlled scene text representation synthesis (no raw JSON dumping).
- Model routing via config/model_routing.yaml:
  - Primary: gemini-embedding-2 (768 dim, CLOUD_SEMANTIC)
  - Text fallback: gemini-embedding-001 (768 dim, CLOUD_SEMANTIC)
  - Offline fallback: hashed-lexical-v1 (256 dim, LEXICAL_FALLBACK)
- Strict dimension & version safety: never compare vectors of different dimensions.
- Honest lexical fallback naming (HashedLexicalEmbeddingProvider).
- Two-stage retrieval:
  - Stage A: Filtering & Vector similarity (pgvector <=> or in-memory brute force)
  - Stage B: Lightweight reranker combining semantic similarity, entity/action overlap, and technical quality.
- Accurate latency tracking (vector_search_ms, rerank_ms, total_ms).
- Visual near-duplicate group annotation via dHash hamming distance.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import yaml

from production.contracts import (
    RetrievalMode,
    RightsState,
    SceneSearchFilter,
    SceneSearchResult,
    SourceSceneRecord,
)
from production.repositories.source_repository import (
    get_embedding_repository,
    get_scene_repository,
    get_source_repository,
)
from production.visual_hasher import hamming_distance

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent / "config" / "model_routing.yaml"


def load_model_routing() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            pass
    return {
        "scene_embedding": {
            "primary": {"provider": "gemini", "model": "gemini-embedding-2", "dimensions": 768},
            "text_fallback": {"provider": "gemini", "model": "gemini-embedding-001", "dimensions": 768},
            "offline_fallback": {"provider": "local", "model": "hashed-lexical-v1", "dimensions": 256},
        }
    }


def synthesize_scene_text_representation(scene: SourceSceneRecord) -> str:
    """
    Controlled text representation:
    Combines description, entities, actions, location context, shot type, and transcript.
    """
    entity_str = ", ".join(
        (e.get("value", "") if isinstance(e, dict) else str(e))
        for e in scene.entities
    )
    action_str = ", ".join(
        (a.get("value", "") if isinstance(a, dict) else str(a))
        for a in scene.actions
    )
    parts = [
        f"Description: {scene.description.strip()}" if scene.description else "",
        f"Entities: {entity_str}" if entity_str else "",
        f"Actions: {action_str}" if action_str else "",
        f"Setting: {scene.location_context}" if scene.location_context else "",
        f"Shot: {scene.shot_type}" if scene.shot_type else "",
        f"Audio: {scene.transcript.strip()}" if scene.transcript else "",
    ]
    return " | ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Embedding Provider Interfaces
# ---------------------------------------------------------------------------

class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        pass

    @property
    @abstractmethod
    def dimensions(self) -> int:
        pass

    @property
    @abstractmethod
    def retrieval_mode(self) -> RetrievalMode:
        pass

    @abstractmethod
    def embed_text(self, text: str) -> List[float]:
        pass

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        pass


class GeminiEmbeddingProvider(EmbeddingProvider):
    """
    Cloud semantic vector provider using Google Gemini GenAI SDK.
    Supports logical model routing: gemini-embedding-2 (primary) or gemini-embedding-001.
    """
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "gemini-embedding-2",
        fallback_model: str = "gemini-embedding-001",
        dimensions: int = 768,
    ):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self._model_name = model_name
        self._fallback_model = fallback_model
        self._dimensions = dimensions

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def retrieval_mode(self) -> RetrievalMode:
        return RetrievalMode.CLOUD_SEMANTIC

    def embed_text(self, text: str) -> List[float]:
        res = self.embed_batch([text])
        return res[0] if res else []

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not configured")
        try:
            from google import genai
            client = genai.Client(api_key=self.api_key)
            result = []
            for t in texts:
                content_str = t.strip() or "scene"
                try:
                    resp = client.models.embed_content(
                        model=self._model_name,
                        contents=content_str,
                    )
                except Exception:
                    # Fallback to secondary model if primary unavailable
                    resp = client.models.embed_content(
                        model=self._fallback_model,
                        contents=content_str,
                    )
                result.append(resp.embedding.values)
            return result
        except Exception as e:
            # Zero secret logging: Never expose api key fragments in errors
            raise ValueError(f"Gemini embedding failed: {e}") from e


class HashedLexicalEmbeddingProvider(EmbeddingProvider):
    """
    Deterministic local lexical vector provider using stable MD5 feature hashing.
    Provides fast, zero-cost, 100% offline normalized vector embeddings with unigram & bigram support.
    Explicitly labeled as LEXICAL_FALLBACK (not a deep neural semantic model).
    """
    def __init__(self, vocab_dim: int = 256, model_name: str = "hashed-lexical-v1"):
        self._vocab_dim = vocab_dim
        self._model_name = model_name

    @property
    def provider_name(self) -> str:
        return "local"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._vocab_dim

    @property
    def retrieval_mode(self) -> RetrievalMode:
        return RetrievalMode.LEXICAL_FALLBACK

    def _hash_embed(self, text: str) -> List[float]:
        vec = np.zeros(self._vocab_dim, dtype=np.float32)
        words = re.findall(r"\w+", text.lower())
        if not words:
            return vec.tolist()

        for w in words:
            idx = int(hashlib.md5(w.encode("utf-8")).hexdigest(), 16) % self._vocab_dim
            vec[idx] += 1.0

        for i in range(len(words) - 1):
            bg = f"{words[i]}_{words[i+1]}"
            idx = int(hashlib.md5(bg.encode("utf-8")).hexdigest(), 16) % self._vocab_dim
            vec[idx] += 1.5

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    def embed_text(self, text: str) -> List[float]:
        return self._hash_embed(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self._hash_embed(t) for t in texts]


# Backward-compatible alias for existing imports
TfIdfSemanticProvider = HashedLexicalEmbeddingProvider


class VietnameseQueryTranslationBridge:
    """
    Cross-Language Query Normalization & Translation Bridge (Phase 3.5).
    Translates Vietnamese visual concepts and craft terms into English synonyms
    to ensure high recall across English/bilingual scene libraries.
    """
    CONCEPT_MAP = {
        # Woodworking & craftsmanship
        "thợ mộc": "carpenter woodworker woodworking",
        "đục": "chisel carving gouge mortise",
        "bào": "hand plane shaving planer",
        "mộng gỗ": "wood joinery mortise tenon kigumi interlocking",
        "ghép gỗ": "wood interlocking joinery timber craft",
        "gỗ": "wood timber lumber",
        # Culinary
        "mì": "noodle ramen pasta",
        "nước dùng": "broth soup boiling simmering",
        "nấu": "cooking boiling culinary preparation",
        "thịt": "meat chashu pork beef broth",
        # Tech & Manufacturing
        "vi mạch": "microchip semiconductor transistor wafer cleanroom",
        "bán dẫn": "semiconductor silicon microchip fab",
        "wafer": "silicon wafer cleanroom fabrication",
        "phòng sạch": "cleanroom iso laboratory semiconductor wafer",
        "quang khắc": "photolithography exposure etching semiconductor",
        # Nature & Landscape
        "núi": "mountain alpine peak slope landscape",
        "thác": "waterfall cascading stream river torrent",
        "băng": "glacier ice frozen snowy alpine",
        "biển": "ocean sea coast marine underwater",
        "san hô": "coral reef underwater aquatic marine",
        "cá hề": "clownfish anemone tropical fish reef",
        "hoàng hôn": "sunset golden hour dusk evening",
        "bình minh": "sunrise dawn morning early daybreak",
        # Medical
        "bác sĩ": "doctor surgeon medical physician",
        "phẫu thuật": "surgery operating room scalpel surgeon hospital",
        "bệnh viện": "hospital clinic intensive care medical",
        # Sports
        "chạy": "running sprint track race sprinter",
        "vận động viên": "athlete sprinter runner track stadium",
        "sân vận động": "stadium arena track field sports",
        # Architecture & Culture
        "chùa": "pagoda temple shrine zen buddhist monk",
        "chuông": "bell temple bell resonance bronze",
        "nhà cổ": "ancient house heritage traditional architecture",
        # Shot types & Camera movements
        "cận cảnh": "close-up macro detail zoom focus",
        "toàn cảnh": "wide shot landscape establishing panorama aerial",
        "trung cảnh": "medium shot focal action waist",
        "quay chậm": "slow motion high frame rate slomo",
        "góc nghiêng": "dutch angle slanted perspective dramatic",
        # Modern & Futuristic
        "robot": "robot android automaton cybernetic mechanical",
        "neon": "neon lights cyberpunk glowing city night vibrant",
        "tương lai": "futuristic future sci-fi high-tech cyberpunk",
        # Production & Studio
        "phim trường": "film set movie studio stage cinema",
        "đạo diễn": "director clapperboard camera operator filming",
        "máy quay": "camera cinema lens filming videography",
    }

    VIETNAMESE_DIACRITICS_REGEX = re.compile(
        r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]",
        re.IGNORECASE,
    )

    @classmethod
    def is_vietnamese(cls, text: str) -> bool:
        return bool(cls.VIETNAMESE_DIACRITICS_REGEX.search(text))

    @classmethod
    def translate_and_enrich(cls, query: str) -> Tuple[str, bool, Optional[str]]:
        """
        Returns (enriched_query, translation_used, translated_query).
        Only activates when query is detected as Vietnamese, leaving English queries intact.
        """
        if not cls.is_vietnamese(query):
            return query, False, None

        query_lower = query.lower()
        matched_en_terms: List[str] = []

        for vi_concept, en_terms in cls.CONCEPT_MAP.items():
            if vi_concept in query_lower:
                matched_en_terms.append(en_terms)

        if matched_en_terms:
            translated_str = " ".join(matched_en_terms)
            enriched_query = f"{query} {translated_str}"
            return enriched_query, True, translated_str

        return query, False, None


def compute_cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """
    Strict dimension safety: Returns 0.0 if vectors have different dimensions or zero norm.
    """
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    a = np.array(vec_a, dtype=np.float32)
    b = np.array(vec_b, dtype=np.float32)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# ---------------------------------------------------------------------------
# Embedding Service & Two-Stage Search (Section 14 & 15)
# ---------------------------------------------------------------------------

class EmbeddingService:
    def __init__(self):
        self.embedding_repo = get_embedding_repository()
        self.scene_repo = get_scene_repository()
        self.source_repo = get_source_repository()
        self.routing_config = load_model_routing()

        scene_cfg = self.routing_config.get("scene_embedding", {})
        primary_cfg = scene_cfg.get("primary", {})
        fallback_cfg = scene_cfg.get("text_fallback", {})
        offline_cfg = scene_cfg.get("offline_fallback", {})

        self.local_provider = HashedLexicalEmbeddingProvider(
            vocab_dim=offline_cfg.get("dimensions", 256),
            model_name=offline_cfg.get("model", "hashed-lexical-v1"),
        )

        has_gemini_key = bool(os.getenv("GEMINI_API_KEY"))
        if has_gemini_key:
            self.cloud_provider: Optional[EmbeddingProvider] = GeminiEmbeddingProvider(
                model_name=primary_cfg.get("model", "gemini-embedding-2"),
                fallback_model=fallback_cfg.get("model", "gemini-embedding-001"),
                dimensions=primary_cfg.get("dimensions", 768),
            )
            self.primary_provider = self.cloud_provider
        else:
            self.cloud_provider = None
            self.primary_provider = self.local_provider

    def index_scene_embedding(
        self,
        scene: SourceSceneRecord,
        provider: Optional[EmbeddingProvider] = None,
    ) -> List[float]:
        active_provider = provider or self.primary_provider
        text_repr = synthesize_scene_text_representation(scene)

        try:
            vector = active_provider.embed_text(text_repr)
        except Exception:
            # Fallback to local provider if cloud provider fails
            active_provider = self.local_provider
            vector = active_provider.embed_text(text_repr)

        self.embedding_repo.save_embedding(
            scene_id=scene.id,
            vector=vector,
            text_repr=text_repr,
            model_name=active_provider.model_name,
            provider=active_provider.provider_name,
            dimensions=active_provider.dimensions,
            embedding_version="v1",
        )
        return vector

    def search_scenes(
        self,
        query: str,
        filters: Optional[SceneSearchFilter] = None,
        top_k: int = 5,
    ) -> List[SceneSearchResult]:
        """
        Two-Stage Retrieval (Phase 2 & Phase 2.5):
        Stage A: Filters + vector similarity against all candidates -> top 30.
        Stage B: Lightweight rerank with entity/action overlap and quality -> top_k.
        Enforces strict dimension and model space isolation.
        Tracks vector_search_ms and rerank_ms accurately.
        """
        t0 = time.perf_counter()
        filters = filters or SceneSearchFilter()

        # Determine active provider
        active_provider = self.primary_provider
        if filters.provider == "local" or (filters.dimensions and filters.dimensions == 256):
            active_provider = self.local_provider

        # Cross-language query normalization & translation bridge
        query_normalized, translation_used, translated_query = (
            VietnameseQueryTranslationBridge.translate_and_enrich(query)
        )

        # Embed query text (using normalized cross-lingual representation)
        try:
            query_vector = active_provider.embed_text(query_normalized)
            used_mode = active_provider.retrieval_mode
        except Exception:
            active_provider = self.local_provider
            query_vector = active_provider.embed_text(query_normalized)
            used_mode = RetrievalMode.LEXICAL_FALLBACK

        candidates = self.scene_repo.list_candidates(filters, limit=200)
        if not candidates:
            return []

        candidate_ids = [scn.id for scn in candidates]
        candidate_map = {scn.id: scn for scn in candidates}

        # Stage A: Vector Search & Candidate Scoring
        t_vec_start = time.perf_counter()

        # Ensure candidates are indexed in the active model space
        for scn in candidates:
            existing_vec = self.embedding_repo.get_embedding(
                scn.id,
                provider=active_provider.provider_name,
                model=active_provider.model_name,
                dimensions=active_provider.dimensions,
                embedding_version="v1",
            )
            if not existing_vec:
                self.index_scene_embedding(scn, provider=active_provider)

        # Search similar via repository using strict model and dimensions
        stage_a_matches = self.embedding_repo.search_similar(
            query_vector=query_vector,
            provider=active_provider.provider_name,
            model=active_provider.model_name,
            dimensions=active_provider.dimensions,
            embedding_version="v1",
            candidate_scene_ids=candidate_ids,
            limit=30,
        )

        t_vec_end = time.perf_counter()
        vector_search_ms = round((t_vec_end - t_vec_start) * 1000, 2)

        # Stage B: Lightweight Reranking
        t_rerank_start = time.perf_counter()
        # Include words from both original query and normalized translation
        query_words = set(re.findall(r"\w+", query_normalized.lower()))

        def _is_concept_matched(concept_val: str) -> bool:
            c_clean = concept_val.lower().strip()
            if not c_clean:
                return False
            if c_clean in query_normalized.lower():
                return True
            c_words = re.findall(r"\w+", c_clean)
            if not c_words:
                return False
            if len(c_words) == 1:
                return c_words[0] in query_words
            matched_words = [w for w in c_words if w in query_words]
            return len(matched_words) >= min(2, len(c_words))

        results: List[SceneSearchResult] = []

        # Find near-duplicate clusters among candidates for duplicate grouping
        candidate_visual_hashes = {
            scn.id: scn.visual_fingerprint
            for scn in candidates
            if scn.visual_fingerprint
        }

        for scene_id, semantic_score in stage_a_matches:
            scn = candidate_map.get(scene_id)
            if not scn:
                continue

            raw_entities = [
                e.get("value", "") if isinstance(e, dict) else str(e)
                for e in scn.entities
            ]
            raw_actions = [
                a.get("value", "") if isinstance(a, dict) else str(a)
                for a in scn.actions
            ]

            entity_matches = [val for val in raw_entities if _is_concept_matched(val)]
            action_matches = [val for val in raw_actions if _is_concept_matched(val)]

            overlap_count = len(entity_matches) + len(action_matches)
            overlap_score = min(1.0, overlap_count * 0.35)

            # Combined score: 60% semantic + 30% exact entity overlap + 10% technical quality
            composite_score = round(
                0.60 * max(0.0, semantic_score) + 0.30 * overlap_score + 0.10 * scn.technical_quality_score,
                3,
            )

            # Check if this scene has a near duplicate group
            dup_group = None
            if scn.visual_fingerprint:
                for other_id, other_vfp in candidate_visual_hashes.items():
                    if other_id != scn.id and hamming_distance(scn.visual_fingerprint, other_vfp) <= 6:
                        # Shared duplicate group cluster tag based on min sorted id
                        sorted_pair = sorted([scn.id, other_id])
                        dup_group = f"dup_{sorted_pair[0][:8]}"
                        break

            match_evidence = {
                "semantic_score": round(semantic_score, 3),
                "overlap_score": round(overlap_score, 3),
                "entity_matches": entity_matches,
                "action_matches": action_matches,
                "technical_quality": scn.technical_quality_score,
                "vector_search_ms": vector_search_ms,
                "embedding_model": active_provider.model_name,
                "embedding_dimensions": active_provider.dimensions,
                "embedding_version": "v1",
                "query_original": query,
                "query_normalized": query_normalized,
                "translation_used": translation_used,
                "translated_query": translated_query,
                "retrieval_mode": used_mode.value,
            }

            res = SceneSearchResult(
                scene_id=scn.id,
                source_id=scn.source_id,
                score=composite_score,
                start_sec=scn.start_sec,
                end_sec=scn.end_sec,
                duration_sec=scn.duration_sec,
                description=scn.description,
                match_evidence=match_evidence,
                scene=scn,
                retrieval_mode=used_mode,
                latency_ms=0.0,  # will finalize after rerank
                possible_duplicate_group=dup_group,
            )
            results.append(res)

        t_rerank_end = time.perf_counter()
        rerank_ms = round((t_rerank_end - t_rerank_start) * 1000, 2)
        total_ms = round((t_rerank_end - t0) * 1000, 2)

        # Finalize latency breakdown on results
        for r in results:
            r.latency_ms = total_ms
            r.match_evidence["rerank_ms"] = rerank_ms
            r.match_evidence["total_ms"] = total_ms

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]


embedding_service = EmbeddingService()
