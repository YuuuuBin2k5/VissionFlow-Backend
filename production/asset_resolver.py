"""
Asset Resolver Service (Phase 4 - Sections 7 to 16)
Resolves canonical VisualIntents to ranked AssetCandidates with:
- Strict RightsGuard enforcement (OWNED, APPROVED_STOCK, LICENSED_COMMERCIAL, PERMISSION_COMMERCIAL; rejects BLOCKED; never auto-upgrades UNKNOWN)
- PexelsStockAdapter with Token Bucket rate limiter, request coalescing, exponential backoff, and offline thematic library fallback
- Config-driven scoring (quality_thresholds.yaml) with visual role modulation
- Hard disqualifications (BLOCKED rights, semantic/action contradiction, broken media, exact duplicates)
- Penalties (visual near-duplicate dhash <= 6 -> -0.35, 3 consecutive same source -> -0.15, watermark -> -0.25)
- Anti-repetition tracker and coverage ratio calculation
- Full provenance tracking on every resolved candidate
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

from production.contracts import (
    AssetCandidate,
    AssetResolutionResult,
    RightsState,
    SceneAssetResolution,
    SceneSearchFilter,
    SourceAssetRecord,
    SourceInput,
    SourceSceneRecord,
    VisualIntent,
    VisualPlan,
    VisualRole,
    WatermarkState,
)
from production.config_loader import config_loader
from production.repositories.source_repository import (
    get_scene_repository,
    get_source_repository,
)
from production.visual_hasher import hamming_distance

logger = logging.getLogger(__name__)

CACHE_FILE_PATH = Path(__file__).resolve().parent / ".asset_cache.json"

# ---------------------------------------------------------------------------
# Thematic HD Stock Library (Deterministic Offline & Fallback Catalog)
# ---------------------------------------------------------------------------
THEMATIC_STOCK_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "pex_33671897",
        "title": "Bamboo Craftsman Shaping Wood Workshop",
        "url": "https://videos.pexels.com/video-files/33671897/bamboo_craft.mp4",
        "thumbnail": "https://images.pexels.com/videos/33671897/bamboo_thumb.jpg",
        "duration": 8.5,
        "width": 1080,
        "height": 1920,
        "shot_type": "medium_close_up",
        "motion_score": 0.65,
        "technical_quality": 0.92,
        "tags": ["bamboo", "chopsticks", "wood", "artisan", "workshop", "craft", "shaping", "carving", "hands"],
        "fingerprint": "dhash:a1b2c3d4e5f60718",
    },
    {
        "id": "pex_33671898",
        "title": "Traditional Japanese Wood Joinery Fitting",
        "url": "https://videos.pexels.com/video-files/33671898/wood_joinery.mp4",
        "thumbnail": "https://images.pexels.com/videos/33671898/joinery_thumb.jpg",
        "duration": 6.2,
        "width": 1080,
        "height": 1920,
        "shot_type": "close_up",
        "motion_score": 0.55,
        "technical_quality": 0.94,
        "tags": ["wood", "joinery", "mortise", "tenon", "carpentry", "fitting", "chiseling", "chisel"],
        "fingerprint": "dhash:b2c3d4e5f6071829",
    },
    {
        "id": "pex_33671899",
        "title": "Blacksmith Forging Glowing Katana Blade",
        "url": "https://videos.pexels.com/video-files/33671899/sword_forge.mp4",
        "thumbnail": "https://images.pexels.com/videos/33671899/forge_thumb.jpg",
        "duration": 7.0,
        "width": 1080,
        "height": 1920,
        "shot_type": "medium_close_up",
        "motion_score": 0.88,
        "technical_quality": 0.95,
        "tags": ["blacksmith", "forging", "sword", "blade", "katana", "steel", "anvil", "sparks", "hammer", "glowing metal"],
        "fingerprint": "dhash:c3d4e5f60718293a",
    },
    {
        "id": "pex_33671900",
        "title": "High Tech Semiconductor Cleanroom Wafer Etching",
        "url": "https://videos.pexels.com/video-files/33671900/semiconductor.mp4",
        "thumbnail": "https://images.pexels.com/videos/33671900/semi_thumb.jpg",
        "duration": 9.0,
        "width": 1080,
        "height": 1920,
        "shot_type": "macro",
        "motion_score": 0.70,
        "technical_quality": 0.96,
        "tags": ["semiconductor", "microchip", "wafer", "silicon", "cleanroom", "automated", "robotic", "etching", "fab"],
        "fingerprint": "dhash:d4e5f60718293a4b",
    },
    {
        "id": "pex_33671901",
        "title": "Watchmaker Assembling Luxury Mechanical Movement",
        "url": "https://videos.pexels.com/video-files/33671901/watchmaker.mp4",
        "thumbnail": "https://images.pexels.com/videos/33671901/watch_thumb.jpg",
        "duration": 6.8,
        "width": 1080,
        "height": 1920,
        "shot_type": "macro",
        "motion_score": 0.50,
        "technical_quality": 0.93,
        "tags": ["watchmaker", "watch", "gears", "movement", "tweezers", "precision", "tourbillon", "mechanical"],
        "fingerprint": "dhash:e5f60718293a4b5c",
    },
    {
        "id": "pex_33671902",
        "title": "Pottery Wheel Wet Clay Shaping Artisan Hands",
        "url": "https://videos.pexels.com/video-files/33671902/pottery.mp4",
        "thumbnail": "https://images.pexels.com/videos/33671902/pottery_thumb.jpg",
        "duration": 7.5,
        "width": 1080,
        "height": 1920,
        "shot_type": "medium_close_up",
        "motion_score": 0.60,
        "technical_quality": 0.91,
        "tags": ["pottery", "clay", "ceramic", "spinning", "wheel", "sculpting", "artisan", "hands"],
        "fingerprint": "dhash:f60718293a4b5c6d",
    },
    {
        "id": "pex_33671903",
        "title": "Majestic Mountain Waterfall Rushing River",
        "url": "https://videos.pexels.com/video-files/33671903/waterfall.mp4",
        "thumbnail": "https://images.pexels.com/videos/33671903/waterfall_thumb.jpg",
        "duration": 10.0,
        "width": 1080,
        "height": 1920,
        "shot_type": "wide",
        "motion_score": 0.85,
        "technical_quality": 0.95,
        "tags": ["waterfall", "river", "nature", "mountain", "valley", "flowing", "water", "mist", "forest"],
        "fingerprint": "dhash:0718293a4b5c6d7e",
    },
    {
        "id": "pex_33671904",
        "title": "Modern Cyberpunk Neon City Traffic Timelapse",
        "url": "https://videos.pexels.com/video-files/33671904/city_timelapse.mp4",
        "thumbnail": "https://images.pexels.com/videos/33671904/city_thumb.jpg",
        "duration": 8.0,
        "width": 1080,
        "height": 1920,
        "shot_type": "wide",
        "motion_score": 0.90,
        "technical_quality": 0.94,
        "tags": ["city", "neon", "cyberpunk", "traffic", "night", "skyline", "timelapse", "urban"],
        "fingerprint": "dhash:18293a4b5c6d7e8f",
    },
    {
        "id": "pex_33671905",
        "title": "Historical Ancient Castle Stone Architecture",
        "url": "https://videos.pexels.com/video-files/33671905/castle.mp4",
        "thumbnail": "https://images.pexels.com/videos/33671905/castle_thumb.jpg",
        "duration": 6.5,
        "width": 1080,
        "height": 1920,
        "shot_type": "medium_wide",
        "motion_score": 0.40,
        "technical_quality": 0.90,
        "tags": ["castle", "ancient", "stone", "architecture", "history", "monument", "medieval"],
        "fingerprint": "dhash:293a4b5c6d7e8f90",
    },
    {
        "id": "pex_33671906",
        "title": "Deep Ocean Waves Atmospheric Surface 60fps",
        "url": "https://videos.pexels.com/video-files/33671906/ocean_waves.mp4",
        "thumbnail": "https://images.pexels.com/videos/33671906/waves_thumb.jpg",
        "duration": 9.5,
        "width": 1080,
        "height": 1920,
        "shot_type": "wide",
        "motion_score": 0.75,
        "technical_quality": 0.92,
        "tags": ["ocean", "sea", "waves", "water", "blue", "depth", "deep", "calm"],
        "fingerprint": "dhash:3a4b5c6d7e8f90a1",
    },
]


# ---------------------------------------------------------------------------
# Rights Guard (Section 11)
# ---------------------------------------------------------------------------
class RightsGuard:
    """
    Enforces intellectual property and commercial usage rights.
    Permitted states: OWNED, LICENSED_COMMERCIAL, PERMISSION_COMMERCIAL, APPROVED_STOCK.
    Disqualified: BLOCKED.
    Policy on UNKNOWN: Never auto-upgrades to APPROVED. Under strict mode, UNKNOWN is disqualified.
    """

    ALLOWED_COMMERCIAL_STATES: Set[RightsState] = {
        RightsState.OWNED,
        RightsState.LICENSED_COMMERCIAL,
        RightsState.PERMISSION_COMMERCIAL,
        RightsState.APPROVED_STOCK,
    }

    @classmethod
    def evaluate_rights(
        cls,
        rights_state: RightsState | str,
        strict: bool = True,
    ) -> Tuple[bool, float, Optional[str]]:
        """
        Returns (is_permitted, rights_score, rejection_reason).
        """
        if isinstance(rights_state, str):
            try:
                rights_state = RightsState(rights_state)
            except Exception:
                rights_state = RightsState.UNKNOWN

        if rights_state == RightsState.BLOCKED:
            return False, 0.0, "Disqualified: Rights state is BLOCKED (copyright restricted or private)"

        if rights_state in cls.ALLOWED_COMMERCIAL_STATES:
            if rights_state in (RightsState.OWNED, RightsState.APPROVED_STOCK):
                return True, 1.0, None
            elif rights_state == RightsState.LICENSED_COMMERCIAL:
                return True, 0.95, None
            else:  # PERMISSION_COMMERCIAL
                return True, 0.90, None

        # Handle UNKNOWN
        if strict:
            return False, 0.0, "Disqualified: Rights state is UNKNOWN under strict commercial policy"
        else:
            return True, 0.40, "Warning: Rights state UNKNOWN accepted under relaxed policy with penalty"


# ---------------------------------------------------------------------------
# Rate Limiter & Token Bucket
# ---------------------------------------------------------------------------
class TokenBucketRateLimiter:
    """
    Token bucket rate limiter to prevent stock API throttling (e.g. 5 req/sec).
    """

    def __init__(self, rate: float = 5.0, capacity: float = 5.0):
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_refill = now

            if self.tokens < 1.0:
                sleep_needed = (1.0 - self.tokens) / self.rate
                await asyncio.sleep(sleep_needed)
                self.tokens = 0.0
                self.last_refill = time.monotonic()
            else:
                self.tokens -= 1.0


# ---------------------------------------------------------------------------
# Pexels Stock Adapter (Section 12)
# ---------------------------------------------------------------------------
class PexelsStockAdapter:
    """
    Stock footage retrieval adapter for Pexels.
    Includes rate limiting, query coalescing, 429 exponential backoff,
    and deterministic fallback to thematic library.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("PEXELS_API_KEY", "")
        self.headers = {"Authorization": self.api_key} if self.api_key else {}
        self.rate_limiter = TokenBucketRateLimiter(rate=5.0, capacity=5.0)
        self._cache: Dict[str, List[Dict[str, Any]]] = {}
        self._in_flight: Dict[str, asyncio.Future] = {}
        self._load_cache()

    def _load_cache(self) -> None:
        if CACHE_FILE_PATH.exists():
            try:
                with open(CACHE_FILE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._cache = data
            except Exception as e:
                logger.warning(f"Could not load asset cache: {e}")

    def _save_cache(self) -> None:
        try:
            with open(CACHE_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save asset cache: {e}")

    async def search_stock(
        self,
        query: str,
        limit: int = 6,
        prefer_portrait: bool = True,
    ) -> List[AssetCandidate]:
        clean_q = re.sub(r"[^\w\s]", "", query).strip().lower()
        if not clean_q:
            clean_q = "cinematic atmospheric footage"

        cache_key = f"pex:{clean_q}:{limit}:{prefer_portrait}"
        if cache_key in self._cache:
            raw_cached = self._cache[cache_key]
            live_cached = [c for c in raw_cached if c.get('provenance', {}).get('origin') == 'pexels_api'
                           and c.get('selection_evidence', {}).get('description') and c.get('media_url')]
            if live_cached:
                return [AssetCandidate.model_validate(c) for c in live_cached]

        # Request Coalescing
        if cache_key in self._in_flight:
            return await self._in_flight[cache_key]

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._in_flight[cache_key] = fut

        try:
            candidates = await self._fetch_pexels_or_fallback(clean_q, limit, prefer_portrait)
            self._cache[cache_key] = [c.model_dump(mode="json") for c in candidates]
            self._save_cache()
            fut.set_result(candidates)
            return candidates
        except Exception as exc:
            fut.set_exception(exc)
            fut.exception()  # Observe producer error even when there are no coalesced waiters.
            raise
        finally:
            self._in_flight.pop(cache_key, None)

    async def _fetch_pexels_or_fallback(
        self,
        query: str,
        limit: int,
        prefer_portrait: bool,
    ) -> List[AssetCandidate]:
        # A missing provider is an error, not permission to invent stock results.
        if not self.api_key or self.api_key.startswith("YOUR_"):
            raise RuntimeError("PEXELS_NOT_CONFIGURED")

        # Apply rate limiting
        await self.rate_limiter.acquire()

        # Retry with exponential backoff for 429
        url = "https://api.pexels.com/videos/search"
        params = {
            "query": query,
            "per_page": min(15, max(limit, 3)),
            "orientation": "portrait" if prefer_portrait else "landscape",
        }

        retries = 2
        backoff = 1.0

        for attempt in range(retries + 1):
            try:
                loop = asyncio.get_running_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: requests.get(url, headers=self.headers, params=params, timeout=8),
                )
                if response.status_code == 200:
                    data = response.json()
                    videos = data.get("videos", [])
                    if not videos:
                        logger.info('Pexels returned no search results')
                        return []

                    results: List[AssetCandidate] = []
                    for v in videos[:limit]:
                        files = [f for f in v.get('video_files', []) if f.get('file_type') == 'video/mp4' and f.get('link')]
                        if not files or not v.get('duration'):
                            continue
                        hd_file = next(
                            (f for f in files if f.get("height", 0) >= 720 and f.get("width", 0) <= f.get("height", 0)),
                            files[0] if files else {},
                        )
                        v_id = str(v.get("id"))
                        cand = AssetCandidate(
                            asset_id=f"pex_{v_id}",
                            source_id=f"pex_{v_id}",
                            provider="pexels_stock",
                            start_sec=0.0,
                            end_sec=float(v['duration']),
                            duration_sec=float(v['duration']),
                            thumbnail_url=v.get("image"),
                            media_url=hd_file['link'],
                            technical_quality_score=min(1.0, (hd_file.get('width', 0) * hd_file.get('height', 0)) / (1080 * 1920)),
                            rights_state=RightsState.APPROVED_STOCK,
                            rights_score=1.0,
                            visual_fingerprint=f"dhash:pex_{v_id[:12]}",
                            provenance={
                                "origin": "pexels_api",
                                "provider": "pexels_stock",
                                "source_id": v_id,
                                "license_ref": "Pexels License Free Commercial",
                                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                                "original_url": v.get("url"),
                            },
                            selection_evidence={"description": re.sub(r"[-_/]+", " ", str(v.get("url", "")))},
                        )
                        results.append(cand)
                    return results

                elif response.status_code == 429:
                    logger.warning(f"Pexels 429 Rate Limit encountered. Backoff {backoff}s...")
                    if attempt < retries:
                        await asyncio.sleep(backoff + random.uniform(0.1, 0.3))
                        backoff *= 2.0
                        continue
                    else:
                        logger.warning('Pexels 429 retries exhausted')
                        raise RuntimeError("PEXELS_RATE_LIMITED")
                else:
                    logger.warning('Pexels HTTP failure: %s', response.status_code)
                    raise RuntimeError(f"PEXELS_HTTP_{response.status_code}")

            except Exception as e:
                logger.warning("Pexels request failed: %s", type(e).__name__)
                raise RuntimeError("PEXELS_REQUEST_FAILED") from None

        return []

    def _match_thematic_catalog(self, query: str, limit: int) -> List[AssetCandidate]:
        """Matches query terms against local vetted thematic catalog."""
        tokens = set(re.findall(r"\w+", query.lower()))
        scored_entries: List[Tuple[float, Dict[str, Any]]] = []

        for item in THEMATIC_STOCK_CATALOG:
            tags = [t.lower() for t in item["tags"]]
            title_words = [w.lower() for w in re.findall(r"\w+", item["title"])]
            overlap_tags = sum(2.0 for t in tokens if t in tags)
            overlap_title = sum(1.5 for t in tokens if t in title_words)
            partial = sum(0.5 for t in tokens if any(t in tag for tag in tags))
            raw_overlap = overlap_tags + overlap_title + partial
            score = round(raw_overlap / max(1.0, len(tokens) * 2.0), 3)
            scored_entries.append((score, item))

        scored_entries.sort(key=lambda x: x[0], reverse=True)

        results: List[AssetCandidate] = []
        for score, item in scored_entries[:limit]:
            cand = AssetCandidate(
                asset_id=item["id"],
                source_id=item["id"],
                provider="pexels_stock",
                start_sec=0.0,
                end_sec=item["duration"],
                duration_sec=item["duration"],
                thumbnail_url=item["thumbnail"],
                media_url=item["url"],
                semantic_score=round(min(1.0, max(0.40, score)), 3),
                technical_quality_score=item["technical_quality"],
                rights_state=RightsState.APPROVED_STOCK,
                rights_score=1.0,
                visual_fingerprint=item["fingerprint"],
                provenance={
                    "origin": "thematic_stock_catalog",
                    "provider": "pexels_stock",
                    "source_id": item["id"],
                    "license_ref": "Pexels License Free Commercial",
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "title": item["title"],
                },
                selection_evidence={"overlap_terms": [t for t in tokens if t in item["tags"]]},
            )
            results.append(cand)
        return results


# ---------------------------------------------------------------------------
# Scoring & Penalty Engine (Sections 8, 9, 10)
# ---------------------------------------------------------------------------
class CandidateScorer:
    """
    Computes fine-grained component scores and applies penalties based on
    canonical weights from quality_thresholds.yaml.
    """

    def __init__(self):
        thresholds = config_loader.quality_thresholds or {}
        scoring_weights = thresholds.get("asset_scoring", {})
        self.w_semantic = scoring_weights.get("semantic_similarity", 0.30)
        self.w_entity_action = scoring_weights.get("entity_action_match", 0.15)
        self.w_visual_role = scoring_weights.get("visual_role_match", 0.10)
        self.w_shot_type = scoring_weights.get("shot_type_match", 0.07)
        self.w_tech_quality = scoring_weights.get("technical_quality", 0.10)
        self.w_duration_fit = scoring_weights.get("duration_trim_fit", 0.08)
        self.w_source_diversity = scoring_weights.get("source_diversity_bonus", 0.05)
        self.w_rights = scoring_weights.get("rights_confidence", 0.15)

        penalties = thresholds.get("penalties", {})
        self.p_repeated_scene = penalties.get("repeated_scene", 0.35)
        self.p_same_source_consecutive = penalties.get("same_source_3_consecutive", 0.15)
        self.p_visible_watermark = penalties.get("visible_watermark", 0.25)
        self.p_entity_conflict = penalties.get("entity_conflict", 1.0)

    def score_candidate(
        self,
        candidate: AssetCandidate,
        intent: VisualIntent,
        target_duration: float,
        used_asset_ids: Set[str],
        recent_source_ids: List[str],
        used_visual_fingerprints: Set[str],
        strict_rights: bool = True,
    ) -> Tuple[bool, AssetCandidate, List[str]]:
        """
        Scores candidate, returns (is_qualified, updated_candidate, rejection_or_warning_reasons).
        """
        rejection_reasons: List[str] = []

        # 1. Hard Rejection: Exact duplicate asset ID
        if candidate.asset_id in used_asset_ids:
            return False, candidate, [f"Disqualified: Exact duplicate asset ID '{candidate.asset_id}' already used"]

        # 2. Hard Rejection: Rights Check
        is_permitted, rights_score, rights_reason = RightsGuard.evaluate_rights(
            candidate.rights_state,
            strict=strict_rights,
        )
        if not is_permitted:
            return False, candidate, [rights_reason or "Disqualified: Rights not permitted"]
        candidate.rights_score = rights_score

        # 3. Hard Rejection: Broken Media Check
        if candidate.media_url and not candidate.media_url.startswith("http"):
            lower_url = candidate.media_url.lower()
            media_exts = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".jpg", ".jpeg", ".png")
            is_file_path = any(lower_url.endswith(ext) for ext in media_exts) or (len(candidate.media_url) > 2 and candidate.media_url[1] == ":")
            if is_file_path and not Path(candidate.media_url).exists():
                return False, candidate, [f"Disqualified: Broken local media reference '{candidate.media_url}'"]

        # 4. Conflict & Contradiction Check (Section 10)
        conflict_detected = False
        evidence_parts = [
            candidate.asset_id,
            str(candidate.provenance.get("title", "")),
            str(candidate.provenance.get("tags", "")),
            str(candidate.selection_evidence.get("overlap_terms", "")),
            str(candidate.selection_evidence.get("description", "")),
            str(candidate.selection_evidence.get("entities", "")),
            str(candidate.selection_evidence.get("actions", "")),
        ]
        evidence_text = " ".join(evidence_parts).lower()

        # Check explicit must_avoid
        for avoid in intent.must_avoid:
            avoid_clean = avoid.strip().lower()
            if avoid_clean and avoid_clean in evidence_text:
                conflict_detected = True
                rejection_reasons.append(f"Disqualified: Contains forbidden visual concept '{avoid}'")
                break

        # Check Automated vs Manual Contradiction
        req_automated = any(k in intent.search_query_en.lower() or k in " ".join(intent.actions).lower() for k in ["automated", "robotic", "cleanroom"])
        has_manual = any(k in evidence_text for k in ["artisan hands", "manual", "hand crafted", "hand knife"])
        if req_automated and has_manual:
            conflict_detected = True
            rejection_reasons.append("Disqualified: Direct action contradiction (automated process required, but candidate is manual hand craft)")

        req_craft = any(k in intent.search_query_en.lower() or k in " ".join(intent.subjects).lower() for k in ["artisan", "bamboo", "chopsticks", "sword", "pottery"])
        has_industrial_conflict = any(k in evidence_text for k in ["plastic factory", "modern laser", "mass production"])
        if req_craft and has_industrial_conflict:
            conflict_detected = True
            rejection_reasons.append("Disqualified: Direct context contradiction (traditional craft required, candidate shows industrial factory)")

        if conflict_detected:
            candidate.conflict_penalty = self.p_entity_conflict
            return False, candidate, rejection_reasons

        # 5. Semantic Match Score
        # If semantic score not already precomputed, estimate via query overlap
        if candidate.semantic_score == 0.0:
            query_tokens = set(re.findall(r"\w+", intent.search_query_en.lower()))
            overlap = sum(1 for t in query_tokens if t in evidence_text)
            candidate.semantic_score = round(min(1.0, overlap / max(1, len(query_tokens))), 3)

        # 6. Entity & Action Match Score
        def _match_concept(concept: str) -> bool:
            concept_clean = concept.strip().lower()
            if not concept_clean:
                return False
            if concept_clean in evidence_text:
                return True
            tokens = [t for t in re.findall(r"\w+", concept_clean) if len(t) > 2]
            return any(t in evidence_text for t in tokens) if tokens else False

        matched_subjects = sum(1 for s in intent.subjects if _match_concept(s))
        matched_actions = sum(1 for a in intent.actions if _match_concept(a))
        total_concepts = max(1, len(intent.subjects) + len(intent.actions))
        candidate.entity_action_score = round(min(1.0, (matched_subjects + matched_actions) / total_concepts), 3)

        # 7. Visual Role Modulation
        v_role = intent.visual_role.upper() if intent.visual_role else VisualRole.PROCESS.value
        role_score = 0.80

        if v_role == VisualRole.HOOK.value:
            # Hooks reward high motion and visual dynamism
            if candidate.technical_quality_score >= 0.90:
                role_score = 1.0
            else:
                role_score = 0.85
        elif v_role == VisualRole.EVIDENCE.value:
            # Evidence prioritizes factual and entity overlap
            if candidate.entity_action_score >= 0.70:
                role_score = 1.0
            else:
                role_score = 0.75
        elif v_role == VisualRole.DETAIL.value:
            # Details favor close up or macro
            pref_match = any(p in ["close_up", "macro", "medium_close_up"] for p in intent.shot_preferences)
            role_score = 0.95 if pref_match else 0.70
        elif v_role == VisualRole.ESTABLISHING.value:
            # Establishing favors wide or medium wide
            pref_match = any(p in ["wide", "medium_wide", "extreme_wide"] for p in intent.shot_preferences)
            role_score = 0.95 if pref_match else 0.70
        candidate.visual_role_score = role_score

        # 8. Shot Type Match Score
        candidate.shot_type_score = 0.0  # No measured shot-type evidence for this candidate.

        # 9. Technical Quality Score
        # Keep missing technical evidence at zero; do not invent a quality score.

        # 10. Duration Fit Score
        if candidate.duration_sec >= target_duration:
            candidate.duration_fit_score = 1.0
        elif candidate.duration_sec >= target_duration * 0.7:
            candidate.duration_fit_score = 0.80
        else:
            candidate.duration_fit_score = round(candidate.duration_sec / max(0.1, target_duration), 2)

        # 11. Source Diversity Score
        is_same_consecutive = len(recent_source_ids) >= 2 and recent_source_ids[-1] == candidate.source_id and recent_source_ids[-2] == candidate.source_id
        if is_same_consecutive:
            candidate.source_diversity_score = 0.20
            candidate.repetition_penalty += self.p_same_source_consecutive
            rejection_reasons.append("Applied diversity penalty: 3 consecutive shots from same source")
        else:
            candidate.source_diversity_score = 1.0

        # 12. Visual Near-Duplicate Detection (dHash Hamming Distance <= 6)
        if candidate.visual_fingerprint:
            for used_fp in used_visual_fingerprints:
                dist = hamming_distance(candidate.visual_fingerprint, used_fp)
                if dist <= 6:
                    candidate.repetition_penalty += self.p_repeated_scene
                    rejection_reasons.append(f"Applied visual near-duplicate penalty: Hamming distance {dist} <= 6")
                    break

        # 13. Watermark Penalty
        if getattr(candidate, "watermark_state", WatermarkState.NONE) == WatermarkState.VISIBLE:
            candidate.watermark_penalty = self.p_visible_watermark
            rejection_reasons.append("Applied visible watermark penalty")

        # 14. Composite Score Formulation
        weighted_sum = (
            self.w_semantic * candidate.semantic_score
            + self.w_entity_action * candidate.entity_action_score
            + self.w_visual_role * candidate.visual_role_score
            + self.w_shot_type * candidate.shot_type_score
            + self.w_tech_quality * candidate.technical_quality_score
            + self.w_duration_fit * candidate.duration_fit_score
            + self.w_source_diversity * candidate.source_diversity_score
            + self.w_rights * candidate.rights_score
        )

        total_penalties = candidate.repetition_penalty + candidate.watermark_penalty + candidate.conflict_penalty
        candidate.composite_score = round(max(0.0, min(1.0, weighted_sum - total_penalties)), 3)
        candidate.score_source = "LEXICAL_RESOLVER"

        # Populate selection evidence
        candidate.selection_evidence = {
            "semantic_score": candidate.semantic_score,
            "entity_action_score": candidate.entity_action_score,
            "visual_role_score": candidate.visual_role_score,
            "rights_score": candidate.rights_score,
            "repetition_penalty": candidate.repetition_penalty,
            "composite_score": candidate.composite_score,
        }

        # Hard rejection threshold
        if candidate.composite_score < 0.20:
            return False, candidate, [f"Disqualified: Composite score {candidate.composite_score} below minimum floor 0.20"]

        # Invariant A: Hard Relevance Floor
        # Footage must meet minimum relevance requirement (cannot have near-zero semantic AND entity/action match)
        if candidate.provider != "graphic_fallback":
            if candidate.semantic_score < 0.15 and candidate.entity_action_score < 0.15:
                return False, candidate, [
                    f"Disqualified: Fails minimum relevance requirement for intent (semantic={candidate.semantic_score:.2f} < 0.15 and entity_action={candidate.entity_action_score:.2f} < 0.15)"
                ]

        return True, candidate, rejection_reasons


# ---------------------------------------------------------------------------
# Asset Resolver Service (Section 7 to 16)
# ---------------------------------------------------------------------------
class CandidateBatch(list):
    def __init__(self):
        super().__init__()
        self.diagnostics = {'errors': [], 'scene_library_available': None, 'pexels_request_success': None}


class AssetResolver:
    """
    Main Asset Resolver Service.
    Resolves VisualPlan -> AssetResolutionResult across User Sources,
    Scene Library, and Stock footage.
    """

    def __init__(self):
        self.stock_adapter = PexelsStockAdapter()
        self.scorer = CandidateScorer()
        self.scene_repo = get_scene_repository()
        self.source_repo = get_source_repository()

    async def resolve_visual_plan(
        self,
        visual_plan: VisualPlan,
        user_sources: Optional[List[SourceInput]] = None,
        channel_profile: Optional[Dict[str, Any]] = None,
        run_id: str = "run_default",
        strict_rights: bool = True,
    ) -> AssetResolutionResult:
        """
        Executes stage 11 Asset Resolution:
        Processes each VisualIntent in the VisualPlan, evaluates candidates across
        configured source priority, eliminates duplicates, and returns structured resolution.
        """
        source_priority = config_loader.production_defaults.get(
            "source_priority",
            ["user_provided", "approved_scene_library", "approved_stock", "graphic_fallback"],
        )

        resolutions: List[SceneAssetResolution] = []
        used_asset_ids: Set[str] = set()
        recent_source_ids: List[str] = []
        used_fingerprints: Set[str] = set()

        total_duration_weight = sum(vi.duration_weight for vi in visual_plan.intents) or 1.0
        resolved_duration_weight = 0.0
        rights_blocker_count = 0
        unresolved_count = 0
        match_scores: List[float] = []

        for intent in visual_plan.intents:
            target_dur = intent.duration_weight * 4.0  # nominal 4s duration per unit
            warnings: List[str] = []
            rejection_reasons: List[str] = []

            # Gather candidates across prioritized sources
            diagnostics = {"query": intent.search_query_en, "user_source_count": len(user_sources or []), "errors": []}
            try:
                raw_candidates = await self._gather_candidates_for_intent(
                    intent=intent, source_priority=source_priority, user_sources=user_sources,
                )
            except RuntimeError as exc:
                raw_candidates = []
                diagnostics["errors"].append(str(exc) if str(exc).startswith('PEXELS_') else 'RETRIEVAL_UNAVAILABLE')
            diagnostics["raw_count"] = len(raw_candidates)
            diagnostics.update(getattr(raw_candidates, 'diagnostics', {}))
            diagnostics['pexels_configured'] = bool(getattr(self.stock_adapter, 'api_key', None))
            diagnostics['r2_source_count'] = sum(bool(c.storage_ref) for c in raw_candidates)
            diagnostics['gemini_visual_analysis_mode'] = 'NOT_RECORDED'

            # Score and filter candidates
            qualified_candidates: List[AssetCandidate] = []
            for raw_cand in raw_candidates:
                is_qual, scored_cand, reasons = self.scorer.score_candidate(
                    candidate=raw_cand,
                    intent=intent,
                    target_duration=target_dur,
                    used_asset_ids=used_asset_ids,
                    recent_source_ids=recent_source_ids,
                    used_visual_fingerprints=used_fingerprints,
                    strict_rights=strict_rights,
                )
                if is_qual:
                    qualified_candidates.append(scored_cand)
                else:
                    rejection_reasons.extend(reasons)
                    if any("Rights state is BLOCKED" in r for r in reasons):
                        rights_blocker_count += 1

            # Sort qualified candidates respecting source priority:
            # Source priority applies ONLY AFTER hard eligibility and relevance floor:
            # User footage only receives Tier 2 priority if it meets relevance floor (composite_score >= 0.40 and (semantic >= 0.20 or entity_action >= 0.20))
            def _get_provider_tier(c: AssetCandidate) -> int:
                if c.provider == "user_source":
                    if c.composite_score >= 0.40 and (c.semantic_score >= 0.20 or c.entity_action_score >= 0.20):
                        return 3
                    return 1  # Demoted to standard tier if relevance is marginal
                elif c.provider == "scene_library":
                    return 2
                elif c.provider == "pexels_stock":
                    return 1
                return 0

            qualified_candidates.sort(
                key=lambda c: (_get_provider_tier(c), c.composite_score),
                reverse=True,
            )

            if qualified_candidates:
                selected = qualified_candidates[0]
                alternates = qualified_candidates[1:4]

                # Update anti-repetition tracking
                used_asset_ids.add(selected.asset_id)
                recent_source_ids.append(selected.source_id)
                if selected.visual_fingerprint:
                    used_fingerprints.add(selected.visual_fingerprint)

                resolved_duration_weight += intent.duration_weight
                match_scores.append(selected.composite_score)

                resolutions.append(
                    SceneAssetResolution(
                        scene_id=intent.scene_id,
                        shot_order=intent.shot_order,
                        intent_id=intent.id,
                        selected_candidate=selected,
                        alternate_candidates=alternates,
                        warnings=warnings + diagnostics['errors'],
                        rejection_reasons=rejection_reasons[:5],
                        is_unresolved=False,
                        retrieval_diagnostics={**diagnostics, "eligible_count": len(qualified_candidates)},
                    )
                )
            else:
                # No candidate qualified -> Graphic fallback or unresolved
                unresolved_count += 1
                fallback_cand = None if diagnostics["errors"] else self._create_graphic_fallback_candidate(intent)
                resolutions.append(
                    SceneAssetResolution(
                        scene_id=intent.scene_id,
                        shot_order=intent.shot_order,
                        intent_id=intent.id,
                        selected_candidate=fallback_cand,
                        alternate_candidates=[],
                        warnings=diagnostics["errors"] or ["No eligible footage. Explanatory graphic; not source footage."],
                        rejection_reasons=rejection_reasons[:5],
                        is_unresolved=True,
                        retrieval_diagnostics={**diagnostics, "eligible_count": 0},
                    )
                )

        # Overall Metrics
        from production.review_media import review_candidate
        coverage_ratio = sum(bool(r.selected_candidate and review_candidate(r.selected_candidate).renderable) for r in resolutions) / max(1, len(resolutions))
        avg_match = round(sum(match_scores) / max(1, len(match_scores)), 3) if match_scores else 0.0

        return AssetResolutionResult(
            run_id=run_id,
            resolutions=resolutions,
            visual_coverage_ratio=coverage_ratio,
            duplicate_count=0,  # Exact duplicates are strictly blocked
            rights_blocker_count=rights_blocker_count,
            unresolved_count=unresolved_count,
            average_match_score=avg_match,
            cache_hit=False,
            resolved_at=datetime.now(timezone.utc),
        )

    async def _gather_candidates_for_intent(
        self,
        intent: VisualIntent,
        source_priority: List[str],
        user_sources: Optional[List[SourceInput]],
    ) -> List[AssetCandidate]:
        candidates = CandidateBatch()

        for source_type in source_priority:
            # 1. User Provided
            if source_type == "user_provided" and user_sources:
                for src in user_sources:
                    user_scenes = self.scene_repo.list_by_source(src.source_id)
                    for scn in user_scenes:
                        cand = self._convert_scene_record_to_candidate(scn, provider="user_source")
                        candidates.append(cand)

            # 2. Approved Scene Library
            elif source_type == "approved_scene_library":
                try:
                    from production.embedding_service import embedding_service
                    hits = embedding_service.search_scenes(query=intent.search_query_en, filters=SceneSearchFilter(), top_k=20)
                    lib_scenes = [hit.scene for hit in hits if hit.scene]
                    candidates.diagnostics['scene_library_available'] = True
                    candidates.diagnostics['scene_library_count'] = len(lib_scenes)
                    for scn in lib_scenes:
                        cand = self._convert_scene_record_to_candidate(scn, provider="scene_library")
                        hit = next(h for h in hits if h.scene_id == scn.id)
                        cand.semantic_score = max(0, min(1, hit.score))
                        candidates.append(cand)
                except Exception as e:
                    candidates.diagnostics['scene_library_available'] = False
                    candidates.diagnostics['errors'].append('SCENE_LIBRARY_UNAVAILABLE')
                    logger.warning('Scene Library lookup failed: %s', type(e).__name__)

            # 3. Approved Stock (Pexels)
            elif source_type == "approved_stock":
                try:
                    stock_cands = await self.stock_adapter.search_stock(
                        query=intent.search_query_en, limit=5, prefer_portrait=True,
                    )
                    candidates.extend(stock_cands)
                    candidates.diagnostics['pexels_request_success'] = True
                    candidates.diagnostics['stock_count'] = len(stock_cands)
                except RuntimeError:
                    candidates.diagnostics['pexels_request_success'] = False
                    candidates.diagnostics['errors'].append('PEXELS_UNAVAILABLE')

        # Provider failure or empty retrieval must never use a hardcoded catalog.

        return candidates

    def _convert_scene_record_to_candidate(
        self,
        record: SourceSceneRecord,
        provider: str = "scene_library",
    ) -> AssetCandidate:
        source = self.source_repo.get(record.source_id)
        rights = source.rights_state if source else RightsState.UNKNOWN
        rights_score = 1.0 if rights in (RightsState.OWNED, RightsState.APPROVED_STOCK) else 0.90
        candidate = AssetCandidate(
            asset_id=record.id,
            source_id=record.source_id,
            provider=provider,
            start_sec=record.start_sec,
            end_sec=record.end_sec,
            duration_sec=record.duration_sec or (record.end_sec - record.start_sec),
            thumbnail_url=record.keyframes[0] if (hasattr(record, "keyframes") and record.keyframes) else None,
            media_url=source.storage_ref if source else None,
            technical_quality_score=getattr(record, "technical_quality_score", 0.0),
            rights_state=rights,
            rights_score=rights_score,
            visual_fingerprint=getattr(record, "visual_fingerprint", None) or record.fingerprint,
            provenance={
                "origin": provider,
                "provider": provider,
                "source_id": record.source_id,
                "scene_id": record.id,
                "license_ref": "User Ingested Archive",
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            },
            selection_evidence={
                "description": record.description,
                "entities": record.entities,
                "actions": record.actions,
            },
        )
        from production.review_media import ingest_review_media
        return ingest_review_media(candidate)

    def _create_graphic_fallback_candidate(self, intent: VisualIntent) -> AssetCandidate:
        from production.review_media import materialize_graphic
        candidate = AssetCandidate(
            asset_id=f"gfx_{intent.id}",
            source_id="graphic_backdrop_engine",
            provider="graphic_fallback",
            start_sec=0.0,
            end_sec=intent.duration_weight * 4.0,
            duration_sec=intent.duration_weight * 4.0,
            semantic_score=0.0,
            composite_score=0.0,
            technical_quality_score=0.0,
            rights_state=RightsState.OWNED,
            rights_score=1.0,
            visual_fingerprint=f"dhash:gfx_{intent.id[:8]}",
            provenance={
                "origin": "kinetic_typography_engine",
                "provider": "graphic_fallback",
                "source_id": "gfx_fallback",
                "license_ref": "Internal Graphic Engine",
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            },
            selection_evidence={"reason": "fallback_graphic_motion_backdrop"},
        )
        return materialize_graphic(candidate, intent)

    def swap_asset(
        self,
        resolution_result: AssetResolutionResult,
        scene_id: str,
        shot_order: int,
        new_asset_id: str,
    ) -> SceneAssetResolution:
        """
        Manually swaps selected asset for a specific shot from alternatives or catalog.
        Marks candidate as is_locked=True.
        """
        target_res = next(
            (r for r in resolution_result.resolutions if r.scene_id == scene_id and r.shot_order == shot_order),
            None,
        )
        if not target_res:
            raise ValueError(f"Resolution not found for scene '{scene_id}' and shot_order {shot_order}")

        # Search in alternates
        alt_match = next((a for a in target_res.alternate_candidates if a.asset_id == new_asset_id), None)
        if alt_match:
            old_selected = target_res.selected_candidate
            target_res.selected_candidate = alt_match
            alt_match.is_locked = True
            if old_selected:
                target_res.alternate_candidates = [
                    old_selected,
                    *(a for a in target_res.alternate_candidates if a.asset_id != new_asset_id),
                ]
            target_res.warnings.append(f"User manually swapped asset to '{new_asset_id}'")
            return target_res

        raise ValueError(f"Asset '{new_asset_id}' is not an available candidate for this shot")


# Global singleton accessor
asset_resolver = AssetResolver()
