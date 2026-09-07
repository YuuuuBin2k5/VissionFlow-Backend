"""
Editorial QC Engine for VisionFlow (Phase 6 - Section 14).
Evaluates creative pacing, hook visual strength, cut density, static sections,
and visual role coverage to produce an authoritative post-render edit_score.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from production.contracts import (
    EditorPlan,
    QualityAxisReport,
    QualityStatus,
    RenderArtifact,
)

logger = logging.getLogger("visionflow.production.editorial_qc")


class EditorialQCEvaluator:
    """
    Evaluates editorial and pacing craft.
    """

    def evaluate(
        self,
        artifact: RenderArtifact,
        editor_plan: Optional[EditorPlan] = None,
    ) -> QualityAxisReport:
        evidence: List[str] = []
        blockers: List[str] = []
        warnings: List[str] = []

        if not editor_plan or not editor_plan.scenes:
            return QualityAxisReport(
                status=QualityStatus.NOT_EVALUATED,
                score=None,
                evidence=["No editor plan available for editorial QC."],
            )

        all_shots = [sh for scn in editor_plan.scenes for sh in scn.shots]
        if not all_shots:
            blockers.append("No shots found in editor plan.")
            return QualityAxisReport(
                status=QualityStatus.FAIL,
                score=0.0,
                evidence=evidence,
                blockers=blockers,
                warnings=warnings,
            )

        # 1. Hook Visual Strength (first 3 seconds)
        first_shot = all_shots[0]
        hook_role = getattr(first_shot, "visual_role", "PROCESS")
        hook_motion = getattr(first_shot, "motion_effect", None)

        if hook_role != "HOOK" and not hook_motion:
            warnings.append("Opening shot (0-3s) lacks dynamic HOOK visual role or motion effect.")
            evidence.append(f"Hook Evaluation: Initial shot role is '{hook_role}' without motion.")
        else:
            evidence.append(f"Hook Evaluation: Strong opening hook ({hook_role}, motion: {hook_motion or 'cut'}).")

        # 2. Cut Density & Shot Durations (Ideal short-form pacing: 1.5s - 4.5s)
        durations = [sh.duration_sec for sh in all_shots if sh.duration_sec > 0]
        avg_shot_dur = sum(durations) / max(1, len(durations))

        long_shots = [sh for sh in all_shots if sh.duration_sec > 6.0 and not sh.motion_effect]
        if long_shots:
            warnings.append(f"Detected {len(long_shots)} long static shots (>6.0s) without camera motion.")

        fast_shots = [sh for sh in all_shots if sh.duration_sec < 1.0]
        if len(fast_shots) > 3:
            warnings.append(f"Detected {len(fast_shots)} ultra-rapid cuts (<1.0s) that may disorient viewers.")

        evidence.append(
            f"Cut Pacing: Average shot length is {avg_shot_dur:.2f}s ({len(all_shots)} total cuts)."
        )

        # 3. Visual Role Coverage
        roles = {getattr(sh, "visual_role", "PROCESS") for sh in all_shots}
        has_core_roles = "HOOK" in roles or "PROCESS" in roles
        evidence.append(f"Visual Role Coverage: {len(roles)} distinct roles ({', '.join(roles)}).")

        # 4. Source Concentration
        providers: Dict[str, int] = {}
        for sh in all_shots:
            prov = sh.provider or "unknown"
            providers[prov] = providers.get(prov, 0) + 1

        top_provider_ratio = max(providers.values()) / max(1, len(all_shots)) if providers else 1.0
        if top_provider_ratio > 0.90 and len(all_shots) > 6:
            warnings.append(f"High source concentration: {top_provider_ratio:.1%} of footage from single source.")

        # Compute editorial craft score
        score = 1.0
        if long_shots:
            score -= 0.10 * min(3, len(long_shots))
        if fast_shots:
            score -= 0.05 * min(2, len(fast_shots))
        if top_provider_ratio > 0.90:
            score -= 0.08
        if "HOOK" not in roles:
            score -= 0.05

        score = max(0.60, round(score, 3))

        status = QualityStatus.PASS if not warnings else QualityStatus.WARN

        return QualityAxisReport(
            status=status,
            score=score,
            evidence=evidence,
            blockers=blockers,
            warnings=warnings,
        )


# Singleton instance
editorial_qc = EditorialQCEvaluator()
