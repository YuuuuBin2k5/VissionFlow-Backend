"""
Script Quality Gate Engine (Phase 3 & Phase 3.5 Hardening)
Implements Multi-Axis Editorial Validation (Spec 04 & 06):
1. Rule 1: Canonical Narration Consistency (scenes[].narration <-> full_script).
2. Rule 2: Hook Latency (< 15 words / < 4.5s in Scene 1).
3. Rule 3: Pacing / Speech Density (2.0 <= WpS <= 3.8 in Vietnamese).
4. Rule 4: Repetition & Lexical Echo (3-gram duplicates, repetitive starters).
5. Rule 5: Sentence Integrity & Broken Clauses (dangling commas, unfinished conjunctions).
6. Rule 6: Critical Fact Support (FactPack critical claims grounded in script).
7. Rule 7: Breathability (no run-on sentences > 35 words without pause).
8. Rule 8: Unsupported Script Claim Detection & Traceability:
   - Dangling fact_refs (BLOCKER)
   - Hallucinated metrics / ungrounded claims / extreme absolutes (BLOCKER or WARNING).

Outputs structured ScriptQualityGateReport with PASS / WARN / FAIL status.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional, Set

from production.contracts import (
    FactPack,
    QualityStatus,
    ScriptGateViolation,
    ScriptPlan,
    ScriptQualityGateReport,
)


class ScriptQualityGate:
    def __init__(
        self,
        max_hook_words: int = 16,
        min_wps: float = 2.0,
        max_wps: float = 3.8,
        max_sentence_words: int = 35,
    ):
        self.max_hook_words = max_hook_words
        self.min_wps = min_wps
        self.max_wps = max_wps
        self.max_sentence_words = max_sentence_words

    def evaluate(
        self,
        script_plan: ScriptPlan,
        fact_pack: Optional[FactPack] = None,
        target_duration_sec: float = 55.0,
        run_id: Optional[str] = None,
    ) -> ScriptQualityGateReport:
        violations: List[ScriptGateViolation] = []
        metrics: Dict[str, Any] = {}

        scenes = script_plan.scenes
        full_script = script_plan.full_script.strip()

        # -------------------------------------------------------------------
        # Rule 1: Canonical Narration Consistency (BLOCKER)
        # -------------------------------------------------------------------
        concatenated_narration = " ".join(s.narration.strip() for s in scenes)
        norm_concat = re.sub(r"\s+", " ", concatenated_narration).strip()
        norm_full = re.sub(r"\s+", " ", full_script).strip()

        if norm_concat != norm_full:
            violations.append(
                ScriptGateViolation(
                    rule_id="RULE_01_CANONICAL_CONSISTENCY",
                    severity="BLOCKER",
                    message="Mâu thuẫn giữa nội dung từng phân cảnh (scenes[].narration) và toàn bộ kịch bản (full_script).",
                    details={
                        "concatenated_len": len(norm_concat),
                        "full_script_len": len(norm_full),
                    },
                )
            )

        # -------------------------------------------------------------------
        # Rule 2: Hook Latency (Scene 1)
        # -------------------------------------------------------------------
        if scenes:
            hook_narration = scenes[0].narration.strip()
            hook_words = len(re.findall(r"\w+", hook_narration))
            metrics["hook_word_count"] = hook_words

            if hook_words > self.max_hook_words:
                violations.append(
                    ScriptGateViolation(
                        rule_id="RULE_02_HOOK_LATENCY",
                        severity="WARNING",
                        message=f"Câu mở đầu (Hook) quá dài ({hook_words} từ > {self.max_hook_words} từ). Cần truyền tải thông điệp tò mò nhanh hơn dưới 4 giây.",
                        scene_index=1,
                        details={"hook_words": hook_words, "max_allowed": self.max_hook_words},
                    )
                )
        else:
            violations.append(
                ScriptGateViolation(
                    rule_id="RULE_02_NO_SCENES",
                    severity="BLOCKER",
                    message="Kịch bản không chứa phân cảnh nào.",
                )
            )

        # -------------------------------------------------------------------
        # Rule 3: Pacing / Speech Density
        # -------------------------------------------------------------------
        total_words = len(re.findall(r"\w+", full_script))
        wps = round(total_words / target_duration_sec, 2) if target_duration_sec > 0 else 0.0
        metrics["total_words"] = total_words
        metrics["words_per_second"] = wps
        metrics["target_duration_sec"] = target_duration_sec

        if wps > self.max_wps:
            violations.append(
                ScriptGateViolation(
                    rule_id="RULE_03_PACING_TOO_FAST",
                    severity="WARNING",
                    message=f"Tốc độ đọc kịch bản quá nhanh ({wps:.1f} từ/giây > {self.max_wps} từ/giây). Cần rút ngắn văn bản để tránh dồn chữ.",
                    details={"wps": wps, "max_wps": self.max_wps},
                )
            )
        elif wps < self.min_wps:
            violations.append(
                ScriptGateViolation(
                    rule_id="RULE_03_PACING_TOO_SLOW",
                    severity="WARNING",
                    message=f"Tốc độ đọc kịch bản quá chậm ({wps:.1f} từ/giây < {self.min_wps} từ/giây). Video có thể bị loãng thông tin.",
                    details={"wps": wps, "min_wps": self.min_wps},
                )
            )

        # -------------------------------------------------------------------
        # Rule 4: Repetition & Lexical Echo
        # -------------------------------------------------------------------
        words_lower = [w.lower() for w in re.findall(r"\w+", full_script)]
        trigrams: Dict[str, int] = {}
        for i in range(len(words_lower) - 2):
            tri = f"{words_lower[i]} {words_lower[i+1]} {words_lower[i+2]}"
            trigrams[tri] = trigrams.get(tri, 0) + 1

        repeated_trigrams = [tri for tri, count in trigrams.items() if count >= 3]
        if repeated_trigrams:
            violations.append(
                ScriptGateViolation(
                    rule_id="RULE_04_REPETITION_ECHO",
                    severity="WARNING",
                    message=f"Phát hiện cụm từ lặp lại nhiều lần gây nhàm chán: {', '.join(repeated_trigrams[:3])}",
                    details={"repeated_trigrams": repeated_trigrams},
                )
            )

        # -------------------------------------------------------------------
        # Rule 5: Sentence Integrity & Broken Clauses
        # -------------------------------------------------------------------
        dangling_conjunctions = ("và", "nhưng", "hoặc", "bởi vì", "do đó", "mà", "tại vì", "thì")
        for scn in scenes:
            text = scn.narration.strip()
            # Check trailing comma or unfinished clause
            if text.endswith(",") or text.endswith(":") or text.endswith(";"):
                violations.append(
                    ScriptGateViolation(
                        rule_id="RULE_05_BROKEN_PUNCTUATION",
                        severity="BLOCKER",
                        message=f"Phân cảnh {scn.scene_index} kết thúc bằng dấu ngắt câu dở dang ({text[-1]}).",
                        scene_index=scn.scene_index,
                    )
                )

            words_in_scene = re.findall(r"\w+", text.lower())
            if words_in_scene and words_in_scene[-1] in dangling_conjunctions:
                violations.append(
                    ScriptGateViolation(
                        rule_id="RULE_05_DANGLING_CONJUNCTION",
                        severity="BLOCKER",
                        message=f"Phân cảnh {scn.scene_index} bị cụt câu ở liên từ kết thúc '{words_in_scene[-1]}'.",
                        scene_index=scn.scene_index,
                    )
                )

        # -------------------------------------------------------------------
        # Rule 6: Critical Fact Support
        # -------------------------------------------------------------------
        if fact_pack and fact_pack.claims:
            critical_claims = [c for c in fact_pack.claims if c.is_critical]
            unsupported_critical = []
            script_lower = full_script.lower()

            for c in critical_claims:
                claim_words = [w.lower() for w in re.findall(r"\w+", c.claim) if len(w) >= 3]
                stop_words = {"các", "những", "của", "cho", "trong", "được", "người", "trên", "đến"}
                sig_words = [w for w in claim_words if w not in stop_words]
                matched_count = sum(1 for w in sig_words if w in script_lower)
                if sig_words and matched_count == 0:
                    unsupported_critical.append(c.claim)

            metrics["critical_claims_count"] = len(critical_claims)
            metrics["unsupported_critical_count"] = len(unsupported_critical)

            if unsupported_critical:
                violations.append(
                    ScriptGateViolation(
                        rule_id="RULE_06_UNSUPPORTED_FACT",
                        severity="WARNING",
                        message=f"Các luận điểm quan trọng chưa thấy xuất hiện trong lời thoại kịch bản: {unsupported_critical[0]}",
                        details={"unsupported_claims": unsupported_critical},
                    )
                )

        # -------------------------------------------------------------------
        # Rule 7: Breathability & Run-on Sentences
        # -------------------------------------------------------------------
        for scn in scenes:
            sentences = [s.strip() for s in re.split(r"[.!?]+", scn.narration) if s.strip()]
            for s in sentences:
                s_words = len(re.findall(r"\w+", s))
                if s_words > self.max_sentence_words:
                    violations.append(
                        ScriptGateViolation(
                            rule_id="RULE_07_RUN_ON_SENTENCE",
                            severity="WARNING",
                            message=f"Phân cảnh {scn.scene_index} có câu quá dài ({s_words} từ mà không có dấu nghỉ ngắt nhịp). Khó khăn cho giọng đọc TTS.",
                            scene_index=scn.scene_index,
                            details={"sentence_words": s_words, "max_allowed": self.max_sentence_words},
                        )
                    )

        # -------------------------------------------------------------------
        # Rule 8: Unsupported Script Claim Detection & Traceability (Spec Phase 3.5)
        # -------------------------------------------------------------------
        if fact_pack:
            valid_fact_ids = {c.id for c in fact_pack.claims}

            # 8a: Dangling fact_refs check
            for scn in scenes:
                for ref in scn.fact_refs:
                    if ref not in valid_fact_ids:
                        violations.append(
                            ScriptGateViolation(
                                rule_id="RULE_08_DANGLING_FACT_REF",
                                severity="BLOCKER",
                                message=f"Phân cảnh {scn.scene_index} trỏ tới claim ID không tồn tại trong FactPack: '{ref}'.",
                                scene_index=scn.scene_index,
                                details={"dangling_ref": ref, "valid_fact_ids": sorted(list(valid_fact_ids))},
                            )
                        )

            # 8b: Unsupported claims, numbers, and ungrounded absolute assertions
            factpack_corpus = f"{fact_pack.topic} " + " ".join(c.claim for c in fact_pack.claims)
            factpack_corpus += " " + " ".join(fact_pack.entities)
            factpack_corpus += " " + " ".join(ev.snippet for ev in fact_pack.evidence_items)
            factpack_corpus_lower = factpack_corpus.lower()

            # Extreme absolute superlatives requiring explicit factpack support
            extreme_assertions = [
                ("số 1 thế giới", "BLOCKER"),
                ("độc nhất vô nhị", "BLOCKER"),
                ("chắc chắn 100%", "BLOCKER"),
                ("cam kết 100%", "BLOCKER"),
                ("chữa khỏi hoàn toàn", "BLOCKER"),
                ("bất khả chiến bại", "WARNING"),
                ("duy nhất trên thế giới", "BLOCKER"),
            ]

            for term, sev in extreme_assertions:
                if term in full_script.lower() and term not in factpack_corpus_lower:
                    violations.append(
                        ScriptGateViolation(
                            rule_id="RULE_08_SCRIPT_UNSUPPORTED_CLAIM",
                            severity=sev,
                            message=f"Kịch bản chứa khẳng định tuyệt đối chưa được chứng thực trong FactPack: '{term}'.",
                            details={"term": term, "severity": sev},
                        )
                    )

            # Check for ungrounded specific numbers/percentages/financial metrics
            # Matches sequences like: 99%, 500 tỷ, 10 triệu đô, 100%, 50%
            quant_matches = re.findall(r"\b(\d+(?:[.,]\d+)?\s*(?:%|triệu|tỷ|nghìn|đô|usd|vnd|\$))\b", full_script, re.IGNORECASE)
            for q in quant_matches:
                q_clean = q.lower().strip()
                # If neither the full number phrase nor the numeric value is in the factpack corpus
                num_only = re.findall(r"\d+", q_clean)[0]
                if q_clean not in factpack_corpus_lower and num_only not in factpack_corpus_lower:
                    # If high impact percentage or large currency amount, escalate to BLOCKER
                    is_high_impact = ("%" in q_clean) or ("tỷ" in q_clean) or ("triệu" in q_clean) or ("đô" in q_clean) or ("usd" in q_clean)
                    sev = "BLOCKER" if is_high_impact else "WARNING"
                    violations.append(
                        ScriptGateViolation(
                            rule_id="RULE_08_SCRIPT_UNSUPPORTED_CLAIM",
                            severity=sev,
                            message=f"Số liệu định lượng '{q}' xuất hiện trong kịch bản nhưng không có căn cứ trong FactPack hoặc nguồn tư liệu.",
                            details={"quant_claim": q, "severity": sev},
                        )
                    )

        # -------------------------------------------------------------------
        # Status & Quality Score Calculation
        # -------------------------------------------------------------------
        blockers = [v for v in violations if v.severity == "BLOCKER"]
        warnings = [v for v in violations if v.severity == "WARNING"]

        if blockers:
            status = QualityStatus.FAIL
            score = max(0.0, 0.50 - (len(blockers) * 0.20))
        elif warnings:
            status = QualityStatus.WARN
            score = max(0.70, 1.0 - (len(warnings) * 0.08))
        else:
            status = QualityStatus.PASS
            score = 1.0

        return ScriptQualityGateReport(
            report_id=f"sqg_{uuid.uuid4().hex[:10]}",
            run_id=run_id,
            status=status,
            score=round(score, 2),
            blocker_count=len(blockers),
            warning_count=len(warnings),
            violations=violations,
            metrics=metrics,
        )


script_quality_gate = ScriptQualityGate()
