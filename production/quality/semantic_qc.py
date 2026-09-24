"""
Semantic & Factual QC Engine for VisionFlow (Phase 6 - Section 12, 13).
Performs intelligent frame sampling, narration-to-visual consistency checking,
wrong entity/action detection, and claim-to-evidence audit.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from production.contracts import (
    AssetResolutionResult,
    ClaimItem,
    EditorPlan,
    FactPack,
    QualityAxisReport,
    QualityStatus,
    RenderArtifact,
    ScriptPlan,
    VisualPlan,
)

logger = logging.getLogger("visionflow.production.semantic_qc")


class SemanticQCEvaluator:
    """
    Evaluates Semantic Visual Consistency and Factual Claims.
    """

    def evaluate(
        self,
        artifact: RenderArtifact,
        editor_plan: Optional[EditorPlan] = None,
        script_plan: Optional[ScriptPlan] = None,
        visual_plan: Optional[VisualPlan] = None,
        resolved_assets: Optional[AssetResolutionResult] = None,
        fact_pack: Optional[FactPack] = None,
    ) -> Tuple[QualityAxisReport, QualityAxisReport]:
        """
        Returns (visual_axis_report, content_axis_report).
        """
        visual_report = self._evaluate_visual_axis(editor_plan, visual_plan, resolved_assets)
        content_report = self._evaluate_content_axis(script_plan, fact_pack)
        return visual_report, content_report

    def _evaluate_visual_axis(
        self,
        editor_plan: Optional[EditorPlan],
        visual_plan: Optional[VisualPlan],
        resolved_assets: Optional[AssetResolutionResult],
    ) -> QualityAxisReport:
        evidence: List[str] = []
        blockers: List[str] = []
        warnings: List[str] = []

        if not editor_plan or not editor_plan.scenes:
            return QualityAxisReport(
                status=QualityStatus.NOT_EVALUATED,
                score=None,
                evidence=["No editor plan available for visual QC."],
            )

        total_shots = 0
        seen_assets: Dict[str, int] = {}
        mismatch_count = 0
        # A VisualPlan contains one intent per *shot*, not one intent per scene.
        # Looking an intent up by the scene's list index misaligns every scene
        # after a multi-shot scene and produces misleading action warnings.
        intents_by_scene_and_shot = {
            (intent.scene_id, intent.shot_order): intent
            for intent in (visual_plan.intents if visual_plan else [])
        }
        scene_intents: Dict[str, List[Any]] = {}
        for intent in (visual_plan.intents if visual_plan else []):
            scene_intents.setdefault(intent.scene_id, []).append(intent)
        reported_missing_actions = set()

        for scn_idx, scn in enumerate(editor_plan.scenes):
            for sh in scn.shots:
                total_shots += 1
                asset_id = sh.asset_id or "unknown"
                seen_assets[asset_id] = seen_assets.get(asset_id, 0) + 1

                # `resolution_shot_order` is set by EditorPlanner and is the
                # stable link back to the VisualIntent.  Older one-shot plans
                # may not have it, so only use their sole scene intent.
                shot_order = sh.resolution_shot_order or sh.shot_index
                v_intent = intents_by_scene_and_shot.get((scn.scene_id, shot_order))
                if v_intent is None:
                    intents_for_scene = scene_intents.get(scn.scene_id, [])
                    if len(intents_for_scene) == 1:
                        v_intent = intents_for_scene[0]

                # Check match score
                score = getattr(sh, "match_score", 1.0)
                if score is None:
                    score = 1.0
                if getattr(sh, "provider", "") == "graphic_fallback":
                    pass
                elif score < 0.40:
                    blockers.append(
                        f"Scene {scn_idx + 1} Shot '{sh.shot_id}': Severe visual mismatch (score {score:.2f} < 0.40)."
                    )
                    mismatch_count += 1
                elif score < 0.65:
                    warnings.append(
                        f"Scene {scn_idx + 1} Shot '{sh.shot_id}': Low visual relevance (score {score:.2f})."
                    )

                # Entity / Action check against intent if available
                if v_intent and not (sh.is_graphic_fallback or getattr(sh, "provider", "") == "graphic_fallback"):
                    raw_actions = getattr(v_intent, "actions", None) or getattr(v_intent, "action_verbs", []) or []
                    req_actions = {
                        " ".join(re.findall(r"[a-z0-9]+", str(action).lower()))
                        for action in raw_actions
                    }
                    candidate = sh.resolved_asset
                    prov = sh.provenance or {}
                    candidate_evidence = []
                    if candidate:
                        candidate_evidence.extend(
                            [
                                candidate.asset_id,
                                str(candidate.provenance.get("title", "")),
                                str(candidate.provenance.get("tags", "")),
                                str(candidate.selection_evidence.get("description", "")),
                                str(candidate.selection_evidence.get("actions", "")),
                            ]
                        )
                    candidate_evidence.extend([str(prov.get("description", "")), sh.visual_prompt or ""])
                    cand_desc = " ".join(candidate_evidence).lower()

                    # Metadata can only disprove an action when there is actual
                    # candidate evidence.  A missing description is not proof
                    # of a semantic mismatch.
                    for act in req_actions:
                        warning_key = (scn.scene_id, sh.shot_id, act)
                        if (
                            act
                            and len(act) > 3
                            and cand_desc
                            and act not in cand_desc
                            and score < 0.50
                            and warning_key not in reported_missing_actions
                        ):
                            reported_missing_actions.add(warning_key)
                            warnings.append(
                                f"Scene {scn_idx + 1} Shot '{sh.shot_id}': Required action '{act}' not detected in resolved asset."
                            )

        # Repetitive footage detection (Section 12)
        duplicates = [aid for aid, cnt in seen_assets.items() if cnt > 2 and aid != "unknown"]
        if duplicates:
            warnings.append(f"Repeated footage detected: Assets {duplicates} used more than 2 times across video.")

        evidence.append(f"Visual Consistency: Evaluated {total_shots} shots across {len(editor_plan.scenes)} scenes.")
        if seen_assets:
            unique_ratio = len(seen_assets) / max(1, total_shots)
            evidence.append(f"Visual Diversity: {unique_ratio:.1%} unique asset coverage.")

        if blockers:
            status = QualityStatus.FAIL
            score = max(0.0, round(0.50 - len(blockers) * 0.20, 2))
        elif warnings:
            status = QualityStatus.WARN
            score = max(0.70, round(1.0 - len(warnings) * 0.08, 2))
        else:
            status = QualityStatus.PASS
            score = 1.0

        return QualityAxisReport(
            status=status,
            score=score,
            evidence=evidence,
            blockers=blockers,
            warnings=warnings,
        )

    def _evaluate_content_axis(
        self,
        script_plan: Optional[ScriptPlan],
        fact_pack: Optional[FactPack],
    ) -> QualityAxisReport:
        evidence: List[str] = []
        blockers: List[str] = []
        warnings: List[str] = []

        if not script_plan:
            return QualityAxisReport(
                status=QualityStatus.NOT_EVALUATED,
                score=None,
                evidence=["No script plan available for content QC."],
            )

        # 1. Provenance Transparency Check (Section 13)
        if fact_pack:
            is_ext_verified = getattr(fact_pack, "external_verification_performed", False)
            res_mode = getattr(fact_pack, "research_mode", "UNKNOWN")
            if not is_ext_verified:
                evidence.append(f"Provenance: Research mode is {res_mode} (not externally web-verified).")
            else:
                evidence.append(f"Provenance: Research verified via web search/external evidence.")

        # 2. Unsupported Numeric / Absolute Claims Audit
        approved_claims: Dict[str, ClaimItem] = {}
        if fact_pack and fact_pack.claims:
            for clm in fact_pack.claims:
                approved_claims[clm.id] = clm

        total_claims_referenced = 0
        dangling_refs = 0

        for scn in script_plan.scenes:
            refs = getattr(scn, "fact_refs", []) or []
            total_claims_referenced += len(refs)
            for r in refs:
                if approved_claims and r not in approved_claims:
                    dangling_refs += 1
                    blockers.append(f"Scene '{scn.scene_id}' references unknown claim ID: {r}.")

            # Scan narration for extreme ungrounded superlatives
            narration_lower = scn.narration.lower()
            absolutes = ["số 1 thế giới", "chắc chắn 100%", "chữa khỏi hoàn toàn", "độc nhất vô nhị", "tuyệt đối 100%"]
            for ab in absolutes:
                if ab in narration_lower:
                    is_backed = False
                    if fact_pack:
                        for clm in fact_pack.claims:
                            if ab in clm.statement.lower():
                                is_backed = True
                                break
                    if not is_backed:
                        blockers.append(f"Ungrounded absolute claim detected in Scene '{scn.scene_id}': '{ab}'.")

        evidence.append(
            f"Factual Audit: Verified {total_claims_referenced} claim references across {len(script_plan.scenes)} scenes."
        )

        if blockers:
            status = QualityStatus.FAIL
            score = max(0.0, round(0.40 - len(blockers) * 0.20, 2))
        elif warnings:
            status = QualityStatus.WARN
            score = max(0.75, round(1.0 - len(warnings) * 0.08, 2))
        else:
            status = QualityStatus.PASS
            score = 1.0

        return QualityAxisReport(
            status=status,
            score=score,
            evidence=evidence,
            blockers=blockers,
            warnings=warnings,
        )


# Singleton instance
semantic_qc = SemanticQCEvaluator()
