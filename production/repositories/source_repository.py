"""
Source, Scene, and Embedding Repositories for VisionFlow Scene Library (Phase 2 & Phase 2.5)
Supports:
- Abstract interfaces (SourceRepositoryInterface, SceneRepositoryInterface, EmbeddingRepositoryInterface)
- Production PostgreSQL adapters with pgvector (PostgresSourceRepository, PostgresSceneRepository, PostgresVectorRepository)
- Development JSON-on-disk adapters (DevelopmentSourceRepository, DevelopmentSceneRepository, DevelopmentBruteForceRepository)
- Strict model, version, and dimension isolation (never compare vectors of different dimensions).
"""

from __future__ import annotations

import json
import math
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import psycopg

from production.contracts import (
    RightsState,
    SceneSearchFilter,
    SourceAssetRecord,
    SourceIngestState,
    SourceSceneRecord,
    WatermarkState,
)

DEV_STORAGE_DIR = Path(__file__).resolve().parent.parent / ".sources_storage"
DEV_STORAGE_DIR.mkdir(exist_ok=True, parents=True)


def _compute_cosine_sim(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    arr_a = np.array(a, dtype=np.float32)
    arr_b = np.array(b, dtype=np.float32)
    norm_a = np.linalg.norm(arr_a)
    norm_b = np.linalg.norm(arr_b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(arr_a, arr_b) / (norm_a * norm_b))


# ---------------------------------------------------------------------------
# Abstract Interfaces
# ---------------------------------------------------------------------------

class SourceRepositoryInterface(ABC):
    @abstractmethod
    def save(self, source: SourceAssetRecord) -> SourceAssetRecord:
        pass

    @abstractmethod
    def get(self, source_id: str) -> Optional[SourceAssetRecord]:
        pass

    @abstractmethod
    def get_by_fingerprint(self, fingerprint: str) -> Optional[SourceAssetRecord]:
        pass

    @abstractmethod
    def get_by_fast_fingerprint(self, fast_fingerprint: str) -> Optional[SourceAssetRecord]:
        pass

    @abstractmethod
    def list_all(self, limit: int = 50) -> List[SourceAssetRecord]:
        pass

    @abstractmethod
    def delete(self, source_id: str) -> bool:
        pass


class SceneRepositoryInterface(ABC):
    @abstractmethod
    def save(self, scene: SourceSceneRecord) -> SourceSceneRecord:
        pass

    @abstractmethod
    def save_batch(self, scenes: List[SourceSceneRecord]) -> List[SourceSceneRecord]:
        pass

    @abstractmethod
    def get(self, scene_id: str) -> Optional[SourceSceneRecord]:
        pass

    @abstractmethod
    def list_by_source(self, source_id: str) -> List[SourceSceneRecord]:
        pass

    @abstractmethod
    def get_by_fingerprint(self, fingerprint: str) -> Optional[SourceSceneRecord]:
        pass

    @abstractmethod
    def get_scenes_with_visual_fingerprint(self) -> List[Tuple[str, str]]:
        pass

    @abstractmethod
    def list_candidates(self, filters: SceneSearchFilter, limit: int = 100) -> List[SourceSceneRecord]:
        pass


class EmbeddingRepositoryInterface(ABC):
    @abstractmethod
    def save_embedding(
        self,
        scene_id: str,
        vector: List[float],
        text_repr: str,
        model_name: str,
        provider: str = "local",
        dimensions: Optional[int] = None,
        embedding_version: str = "v1",
    ) -> None:
        pass

    @abstractmethod
    def get_embedding(
        self,
        scene_id: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        dimensions: Optional[int] = None,
        embedding_version: Optional[str] = None,
    ) -> Optional[List[float]]:
        pass

    @abstractmethod
    def list_all_embeddings(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        dimensions: Optional[int] = None,
        embedding_version: Optional[str] = None,
    ) -> Dict[str, Tuple[List[float], str]]:
        pass

    @abstractmethod
    def search_similar(
        self,
        query_vector: List[float],
        provider: str,
        model: str,
        dimensions: int,
        embedding_version: str = "v1",
        candidate_scene_ids: Optional[List[str]] = None,
        limit: int = 50,
    ) -> List[Tuple[str, float]]:
        pass


# ---------------------------------------------------------------------------
# Development JSON-on-disk Adapters
# ---------------------------------------------------------------------------

class DevelopmentSourceRepository(SourceRepositoryInterface):
    def __init__(self, storage_dir: Path = DEV_STORAGE_DIR / "sources"):
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._sources: Dict[str, SourceAssetRecord] = {}
        self._load()

    def _load(self):
        for f in self.storage_dir.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                    rec = SourceAssetRecord.model_validate(data)
                    self._sources[rec.id] = rec
            except Exception:
                pass

    def save(self, source: SourceAssetRecord) -> SourceAssetRecord:
        self._sources[source.id] = source
        file_path = self.storage_dir / f"{source.id}.json"
        with open(file_path, "w", encoding="utf-8") as fp:
            json.dump(source.model_dump(mode="json"), fp, indent=2, ensure_ascii=False)
        return source

    def get(self, source_id: str) -> Optional[SourceAssetRecord]:
        return self._sources.get(source_id)

    def get_by_fingerprint(self, fingerprint: str) -> Optional[SourceAssetRecord]:
        for src in self._sources.values():
            if src.fingerprint == fingerprint:
                return src
        return None

    def get_by_fast_fingerprint(self, fast_fingerprint: str) -> Optional[SourceAssetRecord]:
        for src in self._sources.values():
            if src.fast_fingerprint == fast_fingerprint:
                return src
        return None

    def list_all(self, limit: int = 50) -> List[SourceAssetRecord]:
        return list(self._sources.values())[:limit]

    def delete(self, source_id: str) -> bool:
        if source_id in self._sources:
            del self._sources[source_id]
            f = self.storage_dir / f"{source_id}.json"
            if f.exists():
                f.unlink()
            return True
        return False


class DevelopmentSceneRepository(SceneRepositoryInterface):
    def __init__(self, storage_dir: Path = DEV_STORAGE_DIR / "scenes"):
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._scenes: Dict[str, SourceSceneRecord] = {}
        self._load()

    def _load(self):
        for f in self.storage_dir.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                    rec = SourceSceneRecord.model_validate(data)
                    self._scenes[rec.id] = rec
            except Exception:
                pass

    def save(self, scene: SourceSceneRecord) -> SourceSceneRecord:
        self._scenes[scene.id] = scene
        file_path = self.storage_dir / f"{scene.id}.json"
        with open(file_path, "w", encoding="utf-8") as fp:
            json.dump(scene.model_dump(mode="json"), fp, indent=2, ensure_ascii=False)
        return scene

    def save_batch(self, scenes: List[SourceSceneRecord]) -> List[SourceSceneRecord]:
        return [self.save(s) for s in scenes]

    def get(self, scene_id: str) -> Optional[SourceSceneRecord]:
        return self._scenes.get(scene_id)

    def list_by_source(self, source_id: str) -> List[SourceSceneRecord]:
        return [s for s in self._scenes.values() if s.source_id == source_id]

    def get_by_fingerprint(self, fingerprint: str) -> Optional[SourceSceneRecord]:
        for scn in self._scenes.values():
            if scn.fingerprint == fingerprint:
                return scn
        return None

    def get_scenes_with_visual_fingerprint(self) -> List[Tuple[str, str]]:
        return [
            (s.id, s.visual_fingerprint)
            for s in self._scenes.values()
            if s.visual_fingerprint
        ]

    def list_candidates(self, filters: SceneSearchFilter, limit: int = 100) -> List[SourceSceneRecord]:
        candidates = []
        for scn in self._scenes.values():
            if filters.source_ids and scn.source_id not in filters.source_ids:
                continue
            if scn.technical_quality_score < filters.min_technical_quality:
                continue
            if filters.duration_range:
                min_dur, max_dur = filters.duration_range[0], filters.duration_range[1]
                if not (min_dur <= scn.duration_sec <= max_dur):
                    continue
            if filters.shot_type and scn.shot_type != filters.shot_type:
                continue
            candidates.append(scn)
            if len(candidates) >= limit:
                break
        return candidates


class DevelopmentBruteForceRepository(EmbeddingRepositoryInterface):
    """
    In-memory / JSON-backed brute-force vector repository.
    Enforces strict dimension, model, and version isolation:
    Vectors of differing dimensions are NEVER compared.
    """
    def __init__(self, storage_dir: Path = DEV_STORAGE_DIR / "embeddings"):
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._entries: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        for f in self.storage_dir.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                    key = f"{data.get('scene_id')}_{data.get('model', data.get('model_name'))}_{data.get('embedding_version', 'v1')}"
                    self._entries[key] = data
            except Exception:
                pass

    def save_embedding(
        self,
        scene_id: str,
        vector: List[float],
        text_repr: str,
        model_name: str,
        provider: str = "local",
        dimensions: Optional[int] = None,
        embedding_version: str = "v1",
    ) -> None:
        dim = dimensions or len(vector)
        entry = {
            "scene_id": scene_id,
            "vector": vector,
            "text_repr": text_repr,
            "model_name": model_name,
            "provider": provider,
            "model": model_name,
            "dimensions": dim,
            "embedding_version": embedding_version,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        key = f"{scene_id}_{model_name}_{embedding_version}"
        self._entries[key] = entry
        file_path = self.storage_dir / f"{scene_id}.json"
        with open(file_path, "w", encoding="utf-8") as fp:
            json.dump(entry, fp, indent=2, ensure_ascii=False)

    def get_embedding(
        self,
        scene_id: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        dimensions: Optional[int] = None,
        embedding_version: Optional[str] = None,
    ) -> Optional[List[float]]:
        for entry in self._entries.values():
            if entry["scene_id"] != scene_id:
                continue
            if provider and entry.get("provider") != provider:
                continue
            if model and entry.get("model") != model and entry.get("model_name") != model:
                continue
            if dimensions and entry.get("dimensions") != dimensions:
                continue
            if embedding_version and entry.get("embedding_version") != embedding_version:
                continue
            return entry["vector"]
        return None

    def list_all_embeddings(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        dimensions: Optional[int] = None,
        embedding_version: Optional[str] = None,
    ) -> Dict[str, Tuple[List[float], str]]:
        result = {}
        for entry in self._entries.values():
            if provider and entry.get("provider") != provider:
                continue
            if model and entry.get("model") != model and entry.get("model_name") != model:
                continue
            if dimensions and entry.get("dimensions") != dimensions:
                continue
            if embedding_version and entry.get("embedding_version") != embedding_version:
                continue
            result[entry["scene_id"]] = (entry["vector"], entry["text_repr"])
        return result

    def search_similar(
        self,
        query_vector: List[float],
        provider: str,
        model: str,
        dimensions: int,
        embedding_version: str = "v1",
        candidate_scene_ids: Optional[List[str]] = None,
        limit: int = 50,
    ) -> List[Tuple[str, float]]:
        # Strict dimension and model safety check
        if len(query_vector) != dimensions:
            raise ValueError(
                f"Query vector dimension ({len(query_vector)}) does not match expected dimensions ({dimensions})"
            )

        candidate_set = set(candidate_scene_ids) if candidate_scene_ids is not None else None
        scores: List[Tuple[str, float]] = []

        for entry in self._entries.values():
            scene_id = entry["scene_id"]
            if candidate_set is not None and scene_id not in candidate_set:
                continue
            # Dimension isolation: reject anything not matching dimensions exactly
            if entry.get("dimensions") != dimensions:
                continue
            # Model & Version isolation
            entry_model = entry.get("model") or entry.get("model_name")
            if entry_model != model:
                continue
            if entry.get("embedding_version", "v1") != embedding_version:
                continue

            vec = entry["vector"]
            if len(vec) != dimensions:
                continue

            sim = _compute_cosine_sim(query_vector, vec)
            scores.append((scene_id, sim))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:limit]


# Backward-compatible alias
DevelopmentEmbeddingRepository = DevelopmentBruteForceRepository


# ---------------------------------------------------------------------------
# Production PostgreSQL Adapters
# ---------------------------------------------------------------------------

class PostgresSourceRepository(SourceRepositoryInterface):
    def __init__(self, dsn: str):
        self.dsn = dsn

    def _get_conn(self):
        return psycopg.connect(self.dsn)

    def save(self, source: SourceAssetRecord) -> SourceAssetRecord:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO source_assets (
                        id, source_type, original_uri, storage_ref, fingerprint,
                        fast_fingerprint, duration, width, height, fps, codec, language,
                        transcript_state, rights_state, watermark_state,
                        ingest_status, analysis_version, metadata_json
                    ) VALUES (
                        %(id)s, %(source_type)s, %(original_uri)s, %(storage_ref)s, %(fingerprint)s,
                        %(fast_fingerprint)s, %(duration)s, %(width)s, %(height)s, %(fps)s, %(codec)s, %(language)s,
                        %(transcript_state)s, %(rights_state)s, %(watermark_state)s,
                        %(ingest_status)s, %(analysis_version)s, %(metadata_json)s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        storage_ref = EXCLUDED.storage_ref,
                        fingerprint = EXCLUDED.fingerprint,
                        fast_fingerprint = EXCLUDED.fast_fingerprint,
                        duration = EXCLUDED.duration,
                        width = EXCLUDED.width,
                        height = EXCLUDED.height,
                        fps = EXCLUDED.fps,
                        codec = EXCLUDED.codec,
                        transcript_state = EXCLUDED.transcript_state,
                        rights_state = EXCLUDED.rights_state,
                        watermark_state = EXCLUDED.watermark_state,
                        ingest_status = EXCLUDED.ingest_status,
                        metadata_json = EXCLUDED.metadata_json,
                        updated_at = NOW()
                """, {
                    "id": source.id,
                    "source_type": source.source_type,
                    "original_uri": source.original_uri,
                    "storage_ref": source.storage_ref,
                    "fingerprint": source.fingerprint,
                    "fast_fingerprint": source.fast_fingerprint,
                    "duration": source.duration,
                    "width": source.width,
                    "height": source.height,
                    "fps": source.fps,
                    "codec": source.codec,
                    "language": source.language,
                    "transcript_state": source.transcript_state,
                    "rights_state": source.rights_state.value if isinstance(source.rights_state, RightsState) else source.rights_state,
                    "watermark_state": source.watermark_state.value if isinstance(source.watermark_state, WatermarkState) else source.watermark_state,
                    "ingest_status": source.ingest_status.value if isinstance(source.ingest_status, SourceIngestState) else source.ingest_status,
                    "analysis_version": source.analysis_version,
                    "metadata_json": json.dumps(source.metadata_json),
                })
            conn.commit()
        return source

    def get(self, source_id: str) -> Optional[SourceAssetRecord]:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, source_type, original_uri, storage_ref, fingerprint,
                           fast_fingerprint, duration, width, height, fps, codec, language,
                           transcript_state, rights_state, watermark_state, ingest_status,
                           analysis_version, metadata_json, created_at
                    FROM source_assets WHERE id = %s
                """, (source_id,))
                row = cur.fetchone()
                if not row:
                    return None
                return SourceAssetRecord(
                    id=row[0],
                    source_type=row[1],
                    original_uri=row[2],
                    storage_ref=row[3],
                    fingerprint=row[4],
                    fast_fingerprint=row[5],
                    duration=row[6],
                    width=row[7],
                    height=row[8],
                    fps=row[9],
                    codec=row[10],
                    language=row[11],
                    transcript_state=row[12],
                    rights_state=RightsState(row[13]),
                    watermark_state=WatermarkState(row[14]),
                    ingest_status=SourceIngestState(row[15]),
                    analysis_version=row[16],
                    metadata_json=row[17] if isinstance(row[17], dict) else json.loads(row[17] or "{}"),
                    created_at=row[18],
                )

    def get_by_fingerprint(self, fingerprint: str) -> Optional[SourceAssetRecord]:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM source_assets WHERE fingerprint = %s LIMIT 1", (fingerprint,))
                row = cur.fetchone()
                if not row:
                    return None
                return self.get(row[0])

    def get_by_fast_fingerprint(self, fast_fingerprint: str) -> Optional[SourceAssetRecord]:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM source_assets WHERE fast_fingerprint = %s LIMIT 1", (fast_fingerprint,))
                row = cur.fetchone()
                if not row:
                    return None
                return self.get(row[0])

    def list_all(self, limit: int = 50) -> List[SourceAssetRecord]:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM source_assets ORDER BY created_at DESC LIMIT %s", (limit,))
                rows = cur.fetchall()
                return [self.get(r[0]) for r in rows if r[0] is not None]

    def delete(self, source_id: str) -> bool:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM source_assets WHERE id = %s", (source_id,))
                deleted = cur.rowcount > 0
            conn.commit()
            return deleted


class PostgresSceneRepository(SceneRepositoryInterface):
    def __init__(self, dsn: str):
        self.dsn = dsn

    def _get_conn(self):
        return psycopg.connect(self.dsn)

    def save(self, scene: SourceSceneRecord) -> SourceSceneRecord:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO source_scenes (
                        id, source_id, start_sec, end_sec, duration_sec,
                        fingerprint, visual_fingerprint, description, transcript,
                        entities, actions, location_context, shot_type, motion_score,
                        technical_quality_score, embedding_ref, analysis_version, keyframes
                    ) VALUES (
                        %(id)s, %(source_id)s, %(start_sec)s, %(end_sec)s, %(duration_sec)s,
                        %(fingerprint)s, %(visual_fingerprint)s, %(description)s, %(transcript)s,
                        %(entities)s, %(actions)s, %(location_context)s, %(shot_type)s, %(motion_score)s,
                        %(technical_quality_score)s, %(embedding_ref)s, %(analysis_version)s, %(keyframes)s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        fingerprint = EXCLUDED.fingerprint,
                        visual_fingerprint = EXCLUDED.visual_fingerprint,
                        description = EXCLUDED.description,
                        transcript = EXCLUDED.transcript,
                        entities = EXCLUDED.entities,
                        actions = EXCLUDED.actions,
                        location_context = EXCLUDED.location_context,
                        shot_type = EXCLUDED.shot_type,
                        motion_score = EXCLUDED.motion_score,
                        technical_quality_score = EXCLUDED.technical_quality_score,
                        embedding_ref = EXCLUDED.embedding_ref,
                        keyframes = EXCLUDED.keyframes,
                        updated_at = NOW()
                """, {
                    "id": scene.id,
                    "source_id": scene.source_id,
                    "start_sec": scene.start_sec,
                    "end_sec": scene.end_sec,
                    "duration_sec": scene.duration_sec,
                    "fingerprint": scene.fingerprint,
                    "visual_fingerprint": scene.visual_fingerprint,
                    "description": scene.description,
                    "transcript": scene.transcript,
                    "entities": json.dumps(scene.entities),
                    "actions": json.dumps(scene.actions),
                    "location_context": scene.location_context,
                    "shot_type": scene.shot_type,
                    "motion_score": scene.motion_score,
                    "technical_quality_score": scene.technical_quality_score,
                    "embedding_ref": scene.embedding_ref,
                    "analysis_version": scene.analysis_version,
                    "keyframes": json.dumps(scene.keyframes),
                })
            conn.commit()
        return scene

    def save_batch(self, scenes: List[SourceSceneRecord]) -> List[SourceSceneRecord]:
        for s in scenes:
            self.save(s)
        return scenes

    def get(self, scene_id: str) -> Optional[SourceSceneRecord]:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, source_id, start_sec, end_sec, duration_sec, fingerprint,
                           visual_fingerprint, description, transcript, entities, actions,
                           location_context, shot_type, motion_score, technical_quality_score,
                           embedding_ref, analysis_version, keyframes, created_at
                    FROM source_scenes WHERE id = %s
                """, (scene_id,))
                row = cur.fetchone()
                if not row:
                    return None
                return SourceSceneRecord(
                    id=row[0],
                    source_id=row[1],
                    start_sec=row[2],
                    end_sec=row[3],
                    duration_sec=row[4],
                    fingerprint=row[5],
                    visual_fingerprint=row[6],
                    description=row[7] or "",
                    transcript=row[8],
                    entities=row[9] if isinstance(row[9], list) else json.loads(row[9] or "[]"),
                    actions=row[10] if isinstance(row[10], list) else json.loads(row[10] or "[]"),
                    location_context=row[11],
                    shot_type=row[12],
                    motion_score=row[13],
                    technical_quality_score=row[14],
                    embedding_ref=row[15],
                    analysis_version=row[16],
                    keyframes=row[17] if isinstance(row[17], list) else json.loads(row[17] or "[]"),
                    created_at=row[18],
                )

    def list_by_source(self, source_id: str) -> List[SourceSceneRecord]:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM source_scenes WHERE source_id = %s ORDER BY start_sec ASC", (source_id,))
                rows = cur.fetchall()
                return [self.get(r[0]) for r in rows if r[0] is not None]

    def get_by_fingerprint(self, fingerprint: str) -> Optional[SourceSceneRecord]:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM source_scenes WHERE fingerprint = %s LIMIT 1", (fingerprint,))
                row = cur.fetchone()
                if not row:
                    return None
                return self.get(row[0])

    def get_scenes_with_visual_fingerprint(self) -> List[Tuple[str, str]]:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, visual_fingerprint FROM source_scenes WHERE visual_fingerprint IS NOT NULL")
                rows = cur.fetchall()
                return [(r[0], r[1]) for r in rows if r[0] and r[1]]

    def list_candidates(self, filters: SceneSearchFilter, limit: int = 100) -> List[SourceSceneRecord]:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id FROM source_scenes 
                    WHERE technical_quality_score >= %s
                    ORDER BY technical_quality_score DESC
                    LIMIT %s
                """, (filters.min_technical_quality, limit))
                rows = cur.fetchall()
                return [self.get(r[0]) for r in rows if r[0] is not None]


class PostgresVectorRepository(EmbeddingRepositoryInterface):
    """
    Production vector repository utilizing PostgreSQL pgvector extension (<=> operator).
    Enforces strict dimension, model, and version isolation in SQL queries.
    Falls back to in-memory cosine similarity if pgvector extension or vector column is unavailable.
    """
    def __init__(self, dsn: str):
        self.dsn = dsn

    def _get_conn(self):
        return psycopg.connect(self.dsn)

    def save_embedding(
        self,
        scene_id: str,
        vector: List[float],
        text_repr: str,
        model_name: str,
        provider: str = "local",
        dimensions: Optional[int] = None,
        embedding_version: str = "v1",
    ) -> None:
        emb_id = f"emb_{scene_id}"
        dim = dimensions or len(vector)
        vec_literal = f"[{','.join(str(float(x)) for x in vector)}]"

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO scene_embeddings (
                        id, scene_id, vector_data, text_representation, model_name,
                        dimensions, provider, model, embedding_version, embedding_vec
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s::vector
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        vector_data = EXCLUDED.vector_data,
                        text_representation = EXCLUDED.text_representation,
                        model_name = EXCLUDED.model_name,
                        dimensions = EXCLUDED.dimensions,
                        provider = EXCLUDED.provider,
                        model = EXCLUDED.model,
                        embedding_version = EXCLUDED.embedding_version,
                        embedding_vec = EXCLUDED.embedding_vec,
                        updated_at = NOW()
                """, (
                    emb_id, scene_id, json.dumps(vector), text_repr, model_name,
                    dim, provider, model_name, embedding_version, vec_literal
                ))
            conn.commit()

    def get_embedding(
        self,
        scene_id: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        dimensions: Optional[int] = None,
        embedding_version: Optional[str] = None,
    ) -> Optional[List[float]]:
        query = "SELECT vector_data FROM scene_embeddings WHERE scene_id = %s"
        params: List[Any] = [scene_id]

        if provider:
            query += " AND provider = %s"
            params.append(provider)
        if model:
            query += " AND (model = %s OR model_name = %s)"
            params.extend([model, model])
        if dimensions:
            query += " AND dimensions = %s"
            params.append(dimensions)
        if embedding_version:
            query += " AND embedding_version = %s"
            params.append(embedding_version)

        query += " LIMIT 1"

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                row = cur.fetchone()
                if not row:
                    return None
                data = row[0]
                return data if isinstance(data, list) else json.loads(data or "[]")

    def list_all_embeddings(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        dimensions: Optional[int] = None,
        embedding_version: Optional[str] = None,
    ) -> Dict[str, Tuple[List[float], str]]:
        query = "SELECT scene_id, vector_data, text_representation FROM scene_embeddings WHERE 1=1"
        params: List[Any] = []

        if provider:
            query += " AND provider = %s"
            params.append(provider)
        if model:
            query += " AND (model = %s OR model_name = %s)"
            params.extend([model, model])
        if dimensions:
            query += " AND dimensions = %s"
            params.append(dimensions)
        if embedding_version:
            query += " AND embedding_version = %s"
            params.append(embedding_version)

        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()
                result = {}
                for r in rows:
                    vec = r[1] if isinstance(r[1], list) else json.loads(r[1] or "[]")
                    result[r[0]] = (vec, r[2])
                return result

    def search_similar(
        self,
        query_vector: List[float],
        provider: str,
        model: str,
        dimensions: int,
        embedding_version: str = "v1",
        candidate_scene_ids: Optional[List[str]] = None,
        limit: int = 50,
    ) -> List[Tuple[str, float]]:
        # Strict dimension check
        if len(query_vector) != dimensions:
            raise ValueError(
                f"Query vector dimension ({len(query_vector)}) does not match expected dimensions ({dimensions})"
            )

        vec_literal = f"[{','.join(str(float(x)) for x in query_vector)}]"

        # Try native pgvector <=> operator with strict isolation
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    query = """
                        SELECT scene_id, (1.0 - (embedding_vec <=> %s::vector)) AS cosine_sim
                        FROM scene_embeddings
                        WHERE dimensions = %s
                          AND (model = %s OR model_name = %s)
                          AND embedding_version = %s
                          AND embedding_vec IS NOT NULL
                    """
                    params: List[Any] = [vec_literal, dimensions, model, model, embedding_version]

                    if candidate_scene_ids:
                        query += " AND scene_id = ANY(%s)"
                        params.append(candidate_scene_ids)

                    query += " ORDER BY (embedding_vec <=> %s::vector) ASC LIMIT %s"
                    params.extend([vec_literal, limit])

                    cur.execute(query, tuple(params))
                    rows = cur.fetchall()
                    return [(r[0], float(r[1])) for r in rows]
        except Exception:
            # Fallback to python calculation over matching rows in Postgres
            pass

        # Python fallback over database rows matching strict model/dimensions
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                query = """
                    SELECT scene_id, vector_data
                    FROM scene_embeddings
                    WHERE dimensions = %s
                      AND (model = %s OR model_name = %s)
                      AND embedding_version = %s
                """
                params = [dimensions, model, model, embedding_version]
                if candidate_scene_ids:
                    query += " AND scene_id = ANY(%s)"
                    params.append(candidate_scene_ids)

                cur.execute(query, tuple(params))
                rows = cur.fetchall()
                results: List[Tuple[str, float]] = []
                for r in rows:
                    sid = r[0]
                    vec = r[1] if isinstance(r[1], list) else json.loads(r[1] or "[]")
                    if len(vec) == dimensions:
                        sim = _compute_cosine_sim(query_vector, vec)
                        results.append((sid, sim))

                results.sort(key=lambda x: x[1], reverse=True)
                return results[:limit]


# Backward-compatible alias
PostgresEmbeddingRepository = PostgresVectorRepository


# ---------------------------------------------------------------------------
# Default Repository Accessors
# ---------------------------------------------------------------------------

_USE_DEV = os.getenv("VISIONFLOW_USE_DEV_REPOSITORIES") == "1"
_PG_DSN = None if _USE_DEV else (os.getenv("DIRECT_DATABASE_URL") or os.getenv("DATABASE_URL"))

if _PG_DSN:
    source_repository: SourceRepositoryInterface = PostgresSourceRepository(_PG_DSN)
    scene_repository: SceneRepositoryInterface = PostgresSceneRepository(_PG_DSN)
    embedding_repository: EmbeddingRepositoryInterface = PostgresVectorRepository(_PG_DSN)
else:
    source_repository = DevelopmentSourceRepository()
    scene_repository = DevelopmentSceneRepository()
    embedding_repository = DevelopmentBruteForceRepository()


def set_repositories_mode(use_dev: bool = True) -> None:
    global source_repository, scene_repository, embedding_repository
    if use_dev:
        source_repository = DevelopmentSourceRepository()
        scene_repository = DevelopmentSceneRepository()
        embedding_repository = DevelopmentBruteForceRepository()
    elif _PG_DSN:
        source_repository = PostgresSourceRepository(_PG_DSN)
        scene_repository = PostgresSceneRepository(_PG_DSN)
        embedding_repository = PostgresVectorRepository(_PG_DSN)


def get_source_repository() -> SourceRepositoryInterface:
    return source_repository


def get_scene_repository() -> SceneRepositoryInterface:
    return scene_repository


def get_embedding_repository() -> EmbeddingRepositoryInterface:
    return embedding_repository
