"""
Pilot Production Learning Loop & Ground Truth Recording Service (Real Channel Pilot Support).
Collects authentic telemetry, manual interventions, scene feedback, visual swaps, script diffs,
and channel profile recommendations without any AI auto-filling or unauthorized alterations.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from production.contracts import (
    ChannelProfileRecommendation,
    ChannelRecommendationStatus,
    ManualInterventionRecord,
    ManualInterventionType,
    InterventionSource,
    ReviewSource,
    ProductionRun,
    ProductionRunStatus,
    RunEnvironment,
    SceneFeedbackItem,
    SceneFeedbackTag,
    ScriptDiffGroundTruth,
    ScriptPlan,
    VisualReplacementGroundTruth,
)
from production.repositories.run_repository import run_repository
from production.channel_profile import channel_profile_registry

logger = logging.getLogger("visionflow.production.pilot_learning")

GROUND_TRUTH_DIR = Path("d:/VisionFlow/.pilot_ground_truth")
VISUAL_SWAPS_DIR = GROUND_TRUTH_DIR / "visual_swaps"
SCRIPT_DIFFS_DIR = GROUND_TRUTH_DIR / "script_diffs"
RECOMMENDATIONS_DIR = Path("d:/VisionFlow/.channel_recommendations")

VISUAL_SWAPS_DIR.mkdir(parents=True, exist_ok=True)
SCRIPT_DIFFS_DIR.mkdir(parents=True, exist_ok=True)
RECOMMENDATIONS_DIR.mkdir(parents=True, exist_ok=True)


class PilotLearningService:
    """
    Manages operator interventions, ground-truth dataset persistence,
    channel profile recommendations, and pilot reporting.
    """

    def __init__(
        self,
        ground_truth_dir: Optional[Path] = None,
        recommendations_dir: Optional[Path] = None,
    ):
        self.ground_truth_dir = ground_truth_dir or GROUND_TRUTH_DIR
        self.visual_swaps_dir = self.ground_truth_dir / "visual_swaps"
        self.script_diffs_dir = self.ground_truth_dir / "script_diffs"
        self.recommendations_dir = recommendations_dir or RECOMMENDATIONS_DIR

        self.visual_swaps_dir.mkdir(parents=True, exist_ok=True)
        self.script_diffs_dir.mkdir(parents=True, exist_ok=True)
        self.recommendations_dir.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------------
    # 1. Manual Intervention Tracking
    # -----------------------------------------------------------------------
    def record_manual_intervention(
        self,
        run_id: str,
        intervention_type: ManualInterventionType | str,
        scene_index: Optional[int] = None,
        description: str = "",
        before_value: Optional[Any] = None,
        after_value: Optional[Any] = None,
        operator_id: str = "operator",
        intervention_source: InterventionSource = InterventionSource.REAL_OPERATOR,
    ) -> ManualInterventionRecord:
        """Records an explicit operator intervention on a production run."""
        run = run_repository.get(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        if isinstance(intervention_type, str):
            intervention_type = ManualInterventionType(intervention_type)

        rec = ManualInterventionRecord(
            run_id=run_id,
            intervention_type=intervention_type,
            scene_index=scene_index,
            description=description,
            before_value=before_value,
            after_value=after_value,
            operator_id=operator_id,
            intervention_source=intervention_source,
            timestamp=datetime.now(timezone.utc),
        )

        run.manual_interventions.append(rec)
        run_repository.update(run)
        logger.info("Recorded intervention %s on run %s by %s", intervention_type.value, run_id, operator_id)
        return rec

    # -----------------------------------------------------------------------
    # 2. Visual Replacement Ground Truth
    # -----------------------------------------------------------------------
    def record_visual_swap_ground_truth(
        self,
        run_id: str,
        scene_index: int,
        rejected_asset_id: str,
        selected_replacement_id: str,
        reason: str = "",
        rejected_asset_url: Optional[str] = None,
        selected_replacement_url: Optional[str] = None,
        visual_intent: Optional[Dict[str, Any]] = None,
        operator_id: str = "operator",
        intervention_source: InterventionSource = InterventionSource.REAL_OPERATOR,
    ) -> VisualReplacementGroundTruth:
        """
        Captures fine-tuning ground truth when operator swaps an asset.
        Links rejected asset, replacement, intent, and operator reason.
        """
        run = run_repository.get(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        gt = VisualReplacementGroundTruth(
            run_id=run_id,
            scene_index=scene_index,
            rejected_asset_id=rejected_asset_id,
            rejected_asset_url=rejected_asset_url,
            selected_replacement_id=selected_replacement_id,
            selected_replacement_url=selected_replacement_url,
            visual_intent=visual_intent,
            reason=reason,
            operator_id=operator_id,
            intervention_source=intervention_source,
            timestamp=datetime.now(timezone.utc),
        )

        run.visual_ground_truth.append(gt)

        # Also log as a manual intervention
        self.record_manual_intervention(
            run_id=run_id,
            intervention_type=ManualInterventionType.VISUAL_CHANGED,
            scene_index=scene_index,
            description=f"Swapped asset from {rejected_asset_id} to {selected_replacement_id}: {reason}",
            before_value=rejected_asset_id,
            after_value=selected_replacement_id,
            operator_id=operator_id,
            intervention_source=intervention_source,
        )

        # Persist ground truth JSON
        file_path = self.visual_swaps_dir / f"{gt.record_id}.json"
        tmp_path = file_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(gt.model_dump_json(indent=2))
        os.replace(tmp_path, file_path)

        run_repository.update(run)
        logger.info("Persisted visual replacement ground truth %s", gt.record_id)
        return gt

    # -----------------------------------------------------------------------
    # 3. Script Diff Ground Truth
    # -----------------------------------------------------------------------
    def record_script_edit(
        self,
        run_id: str,
        edited_script_plan: ScriptPlan,
        operator_id: str = "operator",
        categories: Optional[List[str]] = None,
        intervention_source: InterventionSource = InterventionSource.REAL_OPERATOR,
    ) -> ScriptDiffGroundTruth:
        """
        Records structured diff between original generated ScriptPlan and operator-edited version.
        Ensures original_script_plan is strictly preserved.
        """
        run = run_repository.get(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        # Invariant: Ensure original_script_plan is preserved
        if not run.original_script_plan:
            if run.script_plan:
                run.original_script_plan = run.script_plan.model_copy(deep=True)
            else:
                run.original_script_plan = edited_script_plan.model_copy(deep=True)

        orig = run.original_script_plan
        orig_hook = orig.scenes[0].narration if orig.scenes else ""
        edited_hook = edited_script_plan.scenes[0].narration if edited_script_plan.scenes else ""
        hook_changed = (orig_hook != edited_hook)

        # Compute scene-level diffs
        scene_diffs = []
        max_scenes = max(len(orig.scenes), len(edited_script_plan.scenes))
        for idx in range(max_scenes):
            orig_scn = orig.scenes[idx] if idx < len(orig.scenes) else None
            edit_scn = edited_script_plan.scenes[idx] if idx < len(edited_script_plan.scenes) else None
            diff_entry = {
                "scene_index": idx + 1,
                "original_narration": orig_scn.narration if orig_scn else None,
                "edited_narration": edit_scn.narration if edit_scn else None,
                "narration_changed": (orig_scn.narration != edit_scn.narration) if (orig_scn and edit_scn) else True,
            }
            scene_diffs.append(diff_entry)

        words_delta = edited_script_plan.total_word_count - orig.total_word_count

        # Auto-detect categories if not explicitly passed
        cat_list = list(categories) if categories else []
        if hook_changed and "hook_change" not in cat_list:
            cat_list.append("hook_change")
        if words_delta < -10 and "shortening" not in cat_list:
            cat_list.append("shortening")
        if words_delta > 10 and "expansion" not in cat_list:
            cat_list.append("expansion")
        if not cat_list:
            cat_list.append("style_refinement")

        diff_record = ScriptDiffGroundTruth(
            run_id=run_id,
            original_title=orig.title,
            edited_title=edited_script_plan.title,
            hook_changed=hook_changed,
            original_hook=orig_hook,
            edited_hook=edited_hook,
            words_delta=words_delta,
            scene_diffs=scene_diffs,
            categories=cat_list,
            operator_id=operator_id,
            intervention_source=intervention_source,
            timestamp=datetime.now(timezone.utc),
        )

        run.script_diff_ground_truth = diff_record
        run.script_plan = edited_script_plan

        # Log intervention
        self.record_manual_intervention(
            run_id=run_id,
            intervention_type=ManualInterventionType.SCRIPT_EDITED,
            description=f"Script edited by operator: {', '.join(cat_list)} (Word delta: {words_delta:+d})",
            before_value=orig.full_script,
            after_value=edited_script_plan.full_script,
            operator_id=operator_id,
        )

        if hook_changed:
            self.record_manual_intervention(
                run_id=run_id,
                intervention_type=ManualInterventionType.HOOK_EDITED,
                scene_index=1,
                description=f"Hook modified from '{orig_hook[:50]}...' to '{edited_hook[:50]}...'",
                before_value=orig_hook,
                after_value=edited_hook,
                operator_id=operator_id,
                intervention_source=intervention_source,
            )

        # Persist ground truth JSON
        file_path = self.script_diffs_dir / f"{diff_record.diff_id}.json"
        tmp_path = file_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(diff_record.model_dump_json(indent=2))
        os.replace(tmp_path, file_path)

        run_repository.update(run)
        logger.info("Persisted script diff ground truth %s", diff_record.diff_id)
        return diff_record

    # -----------------------------------------------------------------------
    # 4. Channel Profile Learning & Recommendations
    # -----------------------------------------------------------------------
    def generate_channel_recommendations(self, channel_id: str) -> List[ChannelProfileRecommendation]:
        """
        Analyzes pilot runs for a given channel and produces profile adjustments
        (voice_rate, target_duration_seconds, visual_pacing, etc.).
        Requires explicit operator approval before applying.
        """
        all_runs = run_repository.list_all(limit=100)
        channel_runs = [
            r for r in all_runs
            if r.channel_profile_id == channel_id and r.run_environment == RunEnvironment.PILOT
        ]

        if not channel_runs:
            # Check runs by request channel_profile_id
            channel_runs = [
                r for r in all_runs
                if getattr(r.request, "channel_profile_id", None) == channel_id
                and r.run_environment == RunEnvironment.PILOT
            ]

        profile = channel_profile_registry.get_profile(channel_id)
        recommendations: List[ChannelProfileRecommendation] = []

        if not channel_runs:
            return recommendations

        # 1. Hook pacing / rating check
        hook_scores = [
            r.human_review.ratings.hook_score
            for r in channel_runs
            if r.human_review and r.human_review.review_source == ReviewSource.REAL_OPERATOR and r.human_review.ratings
        ]
        hook_interventions = sum(
            1 for r in channel_runs
            if any(i.intervention_type == ManualInterventionType.HOOK_EDITED and i.intervention_source == InterventionSource.REAL_OPERATOR for i in r.manual_interventions)
        )
        if (hook_scores and sum(hook_scores) / len(hook_scores) < 4.2) or (hook_interventions >= len(channel_runs) * 0.3):
            recommendations.append(
                ChannelProfileRecommendation(
                    channel_id=channel_id,
                    parameter="visual_pacing",
                    current_value=profile.visual_pacing,
                    suggested_value="dynamic_hook_fast",
                    confidence=0.88,
                    evidence=f"Hook scores averaged {sum(hook_scores)/len(hook_scores):.1f}/5 with {hook_interventions} manual hook edits across {len(channel_runs)} pilot videos.",
                )
            )

        # 2. Duration tuning check
        durations = []
        for r in channel_runs:
            if r.render_artifact and r.render_artifact.duration_seconds:
                durations.append(r.render_artifact.duration_seconds)
            elif r.editor_plan and r.editor_plan.total_duration_sec:
                durations.append(r.editor_plan.total_duration_sec)

        if durations:
            avg_dur = sum(durations) / len(durations)
            target = profile.target_duration_seconds
            if abs(avg_dur - target) >= 6.0:
                suggested_target = int(round(avg_dur / 5.0) * 5)
                recommendations.append(
                    ChannelProfileRecommendation(
                        channel_id=channel_id,
                        parameter="target_duration_seconds",
                        current_value=target,
                        suggested_value=suggested_target,
                        confidence=0.85,
                        evidence=f"Actual rendered durations averaged {avg_dur:.1f}s, deviating by {avg_dur - target:+.1f}s from target {target}s.",
                    )
                )

        # 3. Voice rate / pacing check
        pacing_scores = [
            r.human_review.ratings.pacing_score
            for r in channel_runs
            if r.human_review and r.human_review.review_source == ReviewSource.REAL_OPERATOR and r.human_review.ratings
        ]
        voice_regenerations = sum(
            1 for r in channel_runs
            if any(i.intervention_type == ManualInterventionType.VOICE_REGENERATED and i.intervention_source == InterventionSource.REAL_OPERATOR for i in r.manual_interventions)
        )
        if (pacing_scores and sum(pacing_scores) / len(pacing_scores) < 4.0) or voice_regenerations > 0:
            recommendations.append(
                ChannelProfileRecommendation(
                    channel_id=channel_id,
                    parameter="voice_rate",
                    current_value=1.0,
                    suggested_value=1.06,
                    confidence=0.82,
                    evidence=f"Pacing score average ({sum(pacing_scores)/max(1, len(pacing_scores)):.1f}/5) suggests slightly faster audio delivery improves retention.",
                )
            )

        # Persist pending recommendations
        for rec in recommendations:
            file_path = self.recommendations_dir / f"{rec.recommendation_id}.json"
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(rec.model_dump_json(indent=2))

        return recommendations

    def get_pending_recommendations(self, channel_id: Optional[str] = None) -> List[ChannelProfileRecommendation]:
        """Loads recommendations with PENDING status from storage."""
        recs = []
        for p in self.recommendations_dir.glob("*.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    item = ChannelProfileRecommendation.model_validate(json.load(f))
                    if item.status == ChannelRecommendationStatus.PENDING:
                        if not channel_id or item.channel_id == channel_id:
                            recs.append(item)
            except Exception:
                pass
        return recs

    def apply_recommendation(
        self,
        channel_id: str,
        recommendation_id: str,
        operator_id: str = "operator",
        approval_source: ReviewSource = ReviewSource.REAL_OPERATOR,
    ) -> bool:
        """
        Explicitly applies an operator-approved recommendation to the channel profile.
        """
        rec_file = self.recommendations_dir / f"{recommendation_id}.json"
        if not rec_file.exists():
            raise ValueError(f"Recommendation {recommendation_id} not found")

        with open(rec_file, "r", encoding="utf-8") as f:
            rec = ChannelProfileRecommendation.model_validate(json.load(f))

        if approval_source != ReviewSource.REAL_OPERATOR:
            raise ValueError("ChannelProfile recommendations require REAL_OPERATOR approval")
        if not operator_id or operator_id == "operator":
            raise ValueError("A real operator identifier is required to approve a ChannelProfile recommendation")

        profile = channel_profile_registry.get_profile(channel_id)
        if not hasattr(profile, rec.parameter):
            logger.warning("ChannelProfile does not have attribute %s", rec.parameter)

        # Update profile attribute
        setattr(profile, rec.parameter, rec.suggested_value)
        channel_profile_registry.register_profile(profile)

        rec.status = ChannelRecommendationStatus.APPROVED
        rec.approved_by = operator_id
        rec.approved_at = datetime.now(timezone.utc)
        rec.approval_source = approval_source
        with open(rec_file, "w", encoding="utf-8") as f:
            f.write(rec.model_dump_json(indent=2))

        logger.info("Applied recommendation %s to channel %s by %s", recommendation_id, channel_id, operator_id)
        return True

    def reject_recommendation(
        self,
        recommendation_id: str,
        operator_id: str = "operator",
    ) -> bool:
        """Rejects a recommendation."""
        rec_file = self.recommendations_dir / f"{recommendation_id}.json"
        if not rec_file.exists():
            raise ValueError(f"Recommendation {recommendation_id} not found")

        with open(rec_file, "r", encoding="utf-8") as f:
            rec = ChannelProfileRecommendation.model_validate(json.load(f))

        rec.status = ChannelRecommendationStatus.REJECTED
        with open(rec_file, "w", encoding="utf-8") as f:
            f.write(rec.model_dump_json(indent=2))

        logger.info("Rejected recommendation %s by %s", recommendation_id, operator_id)
        return True

    # -----------------------------------------------------------------------
    # 5. Pilot Production Report Compiler
    # -----------------------------------------------------------------------
    def compile_pilot_report(
        self,
        run_ids: Optional[List[str]] = None,
        channel_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Compiles the comprehensive Real Channel Pilot Report covering:
        - Segregated pilot runs only (run_environment = PILOT)
        - Cost accounting ($/video, $/minute, breakdowns)
        - Latency and bottleneck distribution
        - First-pass QC & human approval rates
        - Manual intervention breakdown and rates
        - Scene-level feedback counts
        - Ground truth datasets gathered
        - Root cause failure analysis
        - Final production GO / TUNE / NO-GO recommendation
        """
        all_runs = run_repository.list_all(limit=200)

        # Filter strictly by PILOT environment
        if run_ids:
            target_runs = [r for r in all_runs if r.id in run_ids]
        else:
            target_runs = [r for r in all_runs if r.run_environment == RunEnvironment.PILOT]

        if channel_id:
            target_runs = [
                r for r in target_runs
                if r.channel_profile_id == channel_id or getattr(r.request, "channel_profile_id", None) == channel_id
            ]

        total_runs = len(target_runs)
        if total_runs == 0:
            return {
                "report_id": f"pilot_rep_{int(datetime.now(timezone.utc).timestamp())}",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_runs": 0,
                "status": "NO_DATA",
                "recommendation": "NO_GO",
                "notes": "No pilot runs recorded with run_environment = PILOT.",
            }

        # Status & Quality metrics
        completed_renders = sum(1 for r in target_runs if r.render_artifact is not None)
        approved_runs = sum(1 for r in target_runs if r.status == ProductionRunStatus.APPROVED)
        first_pass_qc_passes = sum(1 for r in target_runs if r.first_pass_qc_pass is True)
        first_pass_approvals = sum(1 for r in target_runs if r.first_pass_human_approval is True)
        auto_fixed_runs = sum(1 for r in target_runs if len(r.auto_fix_history) > 0)

        # Cost accounting
        total_cost_usd = sum((r.cost_telemetry.total_cost_usd if r.cost_telemetry else 0.0) for r in target_runs)
        total_render_compute_sec = sum(
            (r.cost_telemetry.render_compute_seconds if r.cost_telemetry else 0.0) for r in target_runs
        )
        total_llm_cost = sum((r.cost_telemetry.llm_cost_usd if r.cost_telemetry else 0.0) for r in target_runs)
        total_tts_cost = sum((r.cost_telemetry.tts_cost_usd if r.cost_telemetry else 0.0) for r in target_runs)
        total_stock_cost = sum((r.cost_telemetry.stock_api_cost_usd if r.cost_telemetry else 0.0) for r in target_runs)
        total_duration_sec = sum(
            (r.render_artifact.duration_seconds if r.render_artifact else 45.0) for r in target_runs
        )
        total_output_minutes = max(0.1, total_duration_sec / 60.0)

        cost_per_video = round(total_cost_usd / total_runs, 4)
        cost_per_output_minute = round(total_cost_usd / total_output_minutes, 4)

        # Provider fallback count
        provider_fallbacks = sum(
            sum(1 for rec in (r.cost_telemetry.records if r.cost_telemetry else []) if rec.fallback_used)
            for r in target_runs
        )

        # Latency metrics
        total_wall_clock_ms = sum(
            (r.latency_telemetry.total_pipeline_duration_ms if r.latency_telemetry else 0)
            for r in target_runs
        )
        avg_pipeline_duration_sec = round((total_wall_clock_ms / 1000.0) / total_runs, 2)

        bottlenecks: Dict[str, int] = {}
        for r in target_runs:
            bn = r.latency_telemetry.bottleneck_stage if r.latency_telemetry else None
            if bn:
                bottlenecks[bn] = bottlenecks.get(bn, 0) + 1

        # Manual interventions
        all_interventions: List[ManualInterventionRecord] = []
        for r in target_runs:
            all_interventions.extend(r.manual_interventions)

        real_interventions = [i for i in all_interventions if i.intervention_source == InterventionSource.REAL_OPERATOR]
        simulated_interventions = [i for i in all_interventions if i.intervention_source != InterventionSource.REAL_OPERATOR]
        total_interventions = len(real_interventions)
        interventions_by_type: Dict[str, int] = {}
        for i in real_interventions:
            t = i.intervention_type.value if hasattr(i.intervention_type, "value") else str(i.intervention_type)
            interventions_by_type[t] = interventions_by_type.get(t, 0) + 1

        avg_intervention_rate = round(
            sum(r.manual_intervention_rate for r in target_runs) / total_runs, 2
        )

        # Scene feedback breakdown
        scene_feedback_counts: Dict[str, int] = {}
        for r in target_runs:
            if r.human_review and r.human_review.review_source == ReviewSource.REAL_OPERATOR and r.human_review.scene_feedback:
                for fb in r.human_review.scene_feedback.values():
                    tag = fb.tag.value if hasattr(fb.tag, "value") else str(fb.tag)
                    scene_feedback_counts[tag] = scene_feedback_counts.get(tag, 0) + 1

        # Rubric scores averages
        rubric_averages: Dict[str, float] = {}
        reviewed_runs = [r for r in target_runs if r.human_review and r.human_review.review_source == ReviewSource.REAL_OPERATOR and r.human_review.ratings]
        if reviewed_runs:
            rubric_averages = {
                "hook_score": round(sum(r.human_review.ratings.hook_score for r in reviewed_runs) / len(reviewed_runs), 2),
                "script_score": round(sum(r.human_review.ratings.script_score for r in reviewed_runs) / len(reviewed_runs), 2),
                "factual_confidence_score": round(sum(r.human_review.ratings.factual_confidence_score for r in reviewed_runs) / len(reviewed_runs), 2),
                "visual_relevance_score": round(sum(r.human_review.ratings.visual_relevance_score for r in reviewed_runs) / len(reviewed_runs), 2),
                "pacing_score": round(sum(r.human_review.ratings.pacing_score for r in reviewed_runs) / len(reviewed_runs), 2),
                "subtitle_score": round(sum(r.human_review.ratings.subtitle_score for r in reviewed_runs) / len(reviewed_runs), 2),
                "audio_score": round(sum(r.human_review.ratings.audio_score for r in reviewed_runs) / len(reviewed_runs), 2),
                "overall_publishability": round(sum(r.human_review.ratings.overall_publishability for r in reviewed_runs) / len(reviewed_runs), 2),
            }

        # Ground truth counts
        visual_swaps_count = len(list(self.visual_swaps_dir.glob("*.json")))
        script_diffs_count = len(list(self.script_diffs_dir.glob("*.json")))

        # Root cause failure analysis
        failure_causes: Dict[str, int] = {
            "RESEARCH": 0,
            "SCRIPT": 0,
            "VISUAL_RETRIEVAL": 0,
            "ASSET_QUALITY": 0,
            "TTS": 0,
            "EDITOR": 0,
            "RENDER": 0,
            "QC_FALSE_POSITIVE": 0,
            "RIGHTS": 0,
            "PUBLISHING": 0,
            "OTHER": 0,
        }

        for r in target_runs:
            if r.status in (ProductionRunStatus.FAILED, ProductionRunStatus.RENDER_FAILED):
                failure_causes["RENDER"] += 1
            elif r.status == ProductionRunStatus.BLOCKED_RIGHTS:
                failure_causes["RIGHTS"] += 1
            elif r.status == ProductionRunStatus.BLOCKED_FACTS:
                failure_causes["RESEARCH"] += 1
            elif r.quality_report and r.quality_report.blocker_count > 0:
                for b in r.quality_report.blockers:
                    b_lower = b.lower()
                    if "right" in b_lower:
                        failure_causes["RIGHTS"] += 1
                    elif "visual" in b_lower:
                        failure_causes["ASSET_QUALITY"] += 1
                    elif "fact" in b_lower:
                        failure_causes["RESEARCH"] += 1
                    else:
                        failure_causes["OTHER"] += 1

        # Final Production Recommendation Formulation
        render_success_rate = (completed_renders / total_runs) * 100.0
        first_pass_qc_rate = (first_pass_qc_passes / total_runs) * 100.0
        real_reviews = [r.human_review for r in target_runs if r.human_review and r.human_review.review_source == ReviewSource.REAL_OPERATOR]
        simulated_reviews = [r.human_review for r in target_runs if r.human_review and r.human_review.review_source != ReviewSource.REAL_OPERATOR]
        real_approved = sum(1 for review in real_reviews if review.decision == "APPROVED")
        approval_rate = (real_approved / len(real_reviews)) * 100.0 if real_reviews else 0.0
        rights_blockers = failure_causes["RIGHTS"]

        if not real_reviews:
            final_recommendation = "GO_REAL_HUMAN_PILOT"
            recommendation_reason = "Pipeline/simulation evidence exists, but no REAL_OPERATOR review data is available."
        elif render_success_rate >= 90.0 and rights_blockers == 0 and first_pass_qc_rate >= 60.0 and approval_rate >= 80.0:
            final_recommendation = "GO_REAL_HUMAN_PILOT"
            recommendation_reason = (
                f"Video pipeline exhibits high reliability ({render_success_rate:.0f}% render success), "
                f"zero commercial rights infractions, robust first-pass QC ({first_pass_qc_rate:.0f}%), "
                f"and high operator satisfaction ({approval_rate:.0f}% approved)."
            )
        elif render_success_rate >= 80.0:
            final_recommendation = "TUNE_REQUIRED"
            recommendation_reason = (
                f"Core pipeline is functional ({render_success_rate:.0f}% renders), but channel profile "
                f"tuning or manual intervention reduction ({avg_intervention_rate:.2f} rate) is recommended before daily batch publishing."
            )
        else:
            final_recommendation = "NO_GO"
            recommendation_reason = f"Render success rate ({render_success_rate:.0f}%) is below operational readiness threshold (80%)."

        report = {
            "report_id": f"pilot_rep_{int(datetime.now(timezone.utc).timestamp())}",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "channel_id": channel_id or "goc_chiem_nghiem_yuubin",
            "run_environment": "PILOT",
            "summary": {
                "total_pilot_runs": total_runs,
                "completed_renders": completed_renders,
                "render_success_rate_pct": round(render_success_rate, 1),
                "first_pass_qc_passes": first_pass_qc_passes,
                "first_pass_qc_rate_pct": round(first_pass_qc_rate, 1),
                "auto_fixed_runs": auto_fixed_runs,
                "approved_runs": real_approved,
                "first_pass_approvals": first_pass_approvals,
                "approval_rate_pct": round(approval_rate, 1),
            },
            "cost_accounting": {
                "total_cost_usd": round(total_cost_usd, 4),
                "cost_per_video_usd": cost_per_video,
                "cost_per_output_minute_usd": cost_per_output_minute,
                "total_output_minutes": round(total_output_minutes, 2),
                "total_render_compute_seconds": round(total_render_compute_sec, 2),
                "breakdown": {
                    "llm_usd": round(total_llm_cost, 4),
                    "tts_usd": round(total_tts_cost, 4),
                    "stock_api_usd": round(total_stock_cost, 4),
                },
                "provider_fallbacks_logged": provider_fallbacks,
            },
            "latency_metrics": {
                "avg_pipeline_duration_seconds": avg_pipeline_duration_sec,
                "bottleneck_stage_distribution": bottlenecks,
            },
            "manual_interventions": {
                "total_interventions": total_interventions,
                "average_intervention_rate": avg_intervention_rate,
                "by_type": interventions_by_type,
            },
            "simulation": {"runs": total_runs, "simulated_reviews": len(simulated_reviews), "simulated_interventions": len(simulated_interventions)},
            "real_operator": {
                "runs_reviewed": len(real_reviews), "approved": real_approved,
                "first_pass_approval_rate": (round(sum(1 for r in target_runs if r.first_pass_human_approval is True) / len(real_reviews) * 100, 1) if real_reviews else None),
                "human_rating_average": (round(sum(review.ratings.overall_publishability for review in real_reviews) / len(real_reviews), 2) if real_reviews else None),
                "manual_intervention_rate": avg_intervention_rate if real_reviews else None,
            },
            "scene_feedback_summary": scene_feedback_counts,
            "operator_rubric_averages_8_axes": rubric_averages,
            "ground_truth_datasets_collected": {
                "visual_swaps_count": visual_swaps_count,
                "script_diffs_count": script_diffs_count,
            },
            "failure_root_causes": failure_causes,
            "final_evaluation": {
                "recommendation": final_recommendation,
                "justification": recommendation_reason,
                "action_items": [
                    "Review channel profile recommendations in .channel_recommendations/",
                    "Keep auto-publish OFF until 5 consecutive runs achieve zero manual interventions",
                    "Fine-tune visual query prompts using the collected visual swap ground truth dataset",
                ],
            },
        }

        # Save to scripts/pilot_production_report.json
        out_path = Path("d:/VisionFlow/VisionFlow_Bakend/scripts/pilot_production_report.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info("Saved pilot production report to %s", out_path)
        return report


pilot_learning_service = PilotLearningService()
