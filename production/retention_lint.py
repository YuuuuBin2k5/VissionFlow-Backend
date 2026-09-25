"""Deterministic editorial-retention checks for evidence-led short videos.

This module deliberately operates on ``ScriptPlan`` and produces internal
diagnostics only.  It does not know about, or mutate, the renderer contract.
Timing before TTS is an estimate based on scene durations and word weights.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from production.contracts import FactPack, RetentionLintResult, ScriptPlan


WORD_RE = re.compile(r"[\wÀ-ỹ]+", re.UNICODE)
SENTENCE_RE = re.compile(r"[^.!?;]+[.!?;]?", re.UNICODE)

EVIDENCE_TERMS = {
    "bằng chứng", "dấu vết", "mảnh", "chiếc", "vật", "răng", "xương", "hóa thạch",
    "bia đá", "hạt", "mẫu", "dna", "x-quang", "xray", "quét", "scan", "đo được",
    "hợp chất", "phát hiện", "tìm thấy", "khắc", "vết cắt", "đồng vị", "tín hiệu",
    "kính thiên văn", "đá", "đồ gốm", "mộ", "quan tài", "hiện vật", "bản khắc",
}
CONTRADICTION_TERMS = {
    "nhưng", "trái lại", "thay vì", "không phải", "mâu thuẫn", "bất thường",
    "khác với", "lẽ ra", "tuy nhiên", "không hề", "ngược lại",
}
CORRECTION_TERMS = {
    "thực ra", "hóa ra", "điều đó cho thấy", "buộc họ sửa", "viết lại", "diễn giải lại",
    "không phải", "thay đổi cách", "chỉnh lại", "bác bỏ",
}
QUESTION_TERMS = {"vì sao", "tại sao", "bằng cách nào", "ai đã", "điều gì", "làm sao"}
STAKE_TERMS = {"nguy hiểm", "biến mất", "sụp đổ", "thay đổi", "lớn hơn", "sớm hơn", "lâu hơn"}
HUMAN_TERMS = {
    "người", "gia đình", "đứa trẻ", "người thợ", "người vô danh", "đã sống", "đã ăn",
    "đã chết", "bàn tay", "cuộc sống", "cộng đồng", "tổ tiên", "chủ nhân",
}
SCIENCE_TERMS = {
    "khảo cổ", "lịch sử", "cổ sinh", "dna", "pháp y", "thiên văn", "địa chất",
    "archaeology", "history", "paleontology", "forensic", "astronomy", "geology",
}
BACKGROUND_TERMS = {
    "năm ", "thế kỷ", "đại học", "viện nghiên cứu", "tạp chí", "phương pháp", "khảo cổ học",
    "địa chất", "niên đại", "kỷ nguyên", "nền tảng xã hội", "xu hướng", "thuật ngữ",
    "tọa lạc", "khu vực", "tỉnh ", "huyện ", "journal", "university", "formation",
}
GENERIC_ENDINGS = {
    "lịch sử vẫn còn nhiều bí ẩn", "con người còn nhiều điều để khám phá",
    "quá khứ luôn khiến chúng ta bất ngờ", "câu chuyện vẫn chưa kết thúc",
    "bạn nghĩ sao", "hãy theo dõi", "đừng quên theo dõi",
}
CURIOSITY_OPENERS = {
    "nhưng đó chưa phải điều lạ nhất", "nhưng câu chuyện chưa dừng ở đó",
    "điều kỳ lạ hơn là", "nhưng họ còn tìm thấy", "và đó chưa phải tất cả",
    "chưa phải tất cả", "chưa dừng lại ở đó",
}


@dataclass(frozen=True)
class TimedChunk:
    text: str
    start: float
    end: float
    scene_index: int


def _words(text: str) -> List[str]:
    return WORD_RE.findall(text.lower())


def _contains(text: str, terms: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def _timeline(script: ScriptPlan, target_duration_sec: float) -> List[TimedChunk]:
    """Build a stable pre-TTS timeline while respecting scene estimates."""
    scenes = script.scenes
    if not scenes:
        return []
    weights = [max(1, len(_words(scene.narration))) for scene in scenes]
    declared = [max(0.0, scene.estimated_speech_duration_sec) for scene in scenes]
    use_declared = sum(declared) > 0
    if use_declared:
        durations = [d if d > 0 else (w / sum(weights)) * target_duration_sec for d, w in zip(declared, weights)]
    else:
        total_words = max(1, sum(weights))
        durations = [(w / total_words) * target_duration_sec for w in weights]

    chunks: List[TimedChunk] = []
    cursor = 0.0
    for scene, duration in zip(scenes, durations):
        parts = [p.strip() for p in SENTENCE_RE.findall(scene.narration) if p.strip()]
        if not parts:
            cursor += duration
            continue
        part_weights = [max(1, len(_words(part))) for part in parts]
        total_part_words = sum(part_weights)
        for part, weight in zip(parts, part_weights):
            part_duration = duration * weight / total_part_words
            chunks.append(TimedChunk(part, cursor, cursor + part_duration, scene.scene_index))
            cursor += part_duration
    return chunks


def _window_text(chunks: Sequence[TimedChunk], start: float, end: float) -> str:
    return " ".join(chunk.text for chunk in chunks if chunk.start < end and chunk.end > start).strip()


def _gain_types(text: str) -> set[str]:
    gains: set[str] = set()
    if _contains(text, EVIDENCE_TERMS):
        gains.add("evidence")
    if _contains(text, CONTRADICTION_TERMS):
        gains.add("contradiction")
    if _contains(text, CORRECTION_TERMS):
        gains.add("correction")
    if _contains(text, QUESTION_TERMS) or "?" in text:
        gains.add("question")
    if _contains(text, STAKE_TERMS):
        gains.add("stakes")
    if _contains(text, HUMAN_TERMS):
        gains.add("human_detail")
    return gains


def _primary_gain_type(gains: set[str]) -> Optional[str]:
    for gain_type in ("evidence", "contradiction", "correction", "question", "stakes", "human_detail"):
        if gain_type in gains:
            return gain_type
    return None


def _proper_nouns(text: str, fact_pack: Optional[FactPack]) -> List[str]:
    found: List[str] = []
    lowered = text.lower()
    if fact_pack:
        for entity in fact_pack.entities:
            entity = entity.strip()
            if entity and entity.lower() in lowered and entity.lower() not in found:
                found.append(entity.lower())
    # Multi-token title-case names are a useful Vietnamese/English pre-TTS heuristic.
    for match in re.finditer(r"(?<![.!?]\s)\b[A-ZĐ][\wÀ-ỹ-]+(?:\s+[A-ZĐ][\wÀ-ỹ-]+)+", text):
        value = match.group(0).lower()
        if value not in found:
            found.append(value)
    return found


class RetentionLint:
    """Evidence-first editorial validator for the YuuBin channel profile."""

    def evaluate(
        self,
        script_plan: ScriptPlan,
        fact_pack: Optional[FactPack] = None,
        target_duration_sec: Optional[float] = None,
    ) -> RetentionLintResult:
        target = float(target_duration_sec or script_plan.estimated_total_duration_sec or 55.0)
        chunks = _timeline(script_plan, target)
        first_3 = _window_text(chunks, 0, 3)
        three_7 = _window_text(chunks, 3, 7)
        seven_10 = _window_text(chunks, 7, 10)
        first_10 = _window_text(chunks, 0, 10)
        warnings: List[str] = []

        hook_1_gains = _gain_types(first_3)
        hook_2_gains = _gain_types(three_7)
        final_window_gains = _gain_types(seven_10)
        if not (hook_1_gains & {"evidence", "contradiction", "question", "stakes"}):
            warnings.append("WEAK_HOOK_0_3")
        if not hook_2_gains or hook_2_gains.issubset(hook_1_gains):
            warnings.append("NO_NEW_INFORMATION_3_7")
        if not (final_window_gains & {"evidence", "contradiction", "correction", "question", "stakes"}):
            warnings.append("SETUP_ONLY_FIRST_10_SECONDS")

        first_10_chunks = [chunk for chunk in chunks if chunk.start < 10]
        gain_chunks = [(chunk, _gain_types(chunk.text)) for chunk in chunks]
        first_10_gain_count = sum(bool(gains) for chunk, gains in gain_chunks if chunk.start < 10)
        information_gain_count = sum(bool(gains) for _, gains in gain_chunks)

        evidence_positions = [chunk.start for chunk, gains in gain_chunks if "evidence" in gains]
        science_context = _contains(
            f"{fact_pack.topic if fact_pack else ''} {script_plan.full_script}",
            SCIENCE_TERMS,
        )
        if science_context and (not evidence_positions or evidence_positions[0] >= 7.0):
            warnings.append("EVIDENCE_TOO_LATE")
        background_chunks = [chunk for chunk in first_10_chunks if _contains(chunk.text, BACKGROUND_TERMS)]
        second_evidence_at = evidence_positions[1] if len(evidence_positions) > 1 else None
        background_too_early = bool(background_chunks) and (
            second_evidence_at is None or any(chunk.start < second_evidence_at for chunk in background_chunks)
        )
        if background_too_early:
            warnings.append("BACKGROUND_TOO_EARLY")

        proper_nouns = _proper_nouns(first_10, fact_pack)
        if len(proper_nouns) > 1:
            warnings.append("PROPER_NOUN_OVERLOAD")

        curiosity_state = "none"
        for chunk in chunks:
            if not _contains(chunk.text, CURIOSITY_OPENERS):
                continue
            payoff_text = _window_text(chunks, chunk.end, chunk.end + 4.0)
            if _gain_types(payoff_text) & {"evidence", "contradiction", "correction", "stakes", "human_detail"}:
                curiosity_state = "paid"
            else:
                curiosity_state = "unpaid"
                warnings.append("UNPAID_CURIOSITY_DEBT")
                break

        full_text = script_plan.full_script.strip()
        ending = " ".join(full_text.split()[-35:]).lower()
        generic_ending = _contains(ending, GENERIC_ENDINGS)
        last_chunks = chunks[-2:] if len(chunks) >= 2 else chunks
        ending_text = " ".join(chunk.text for chunk in last_chunks)
        human_payoff = bool(_gain_types(ending_text) & {"human_detail"}) and bool(
            _gain_types(ending_text) & {"evidence", "correction", "contradiction"}
        )
        if generic_ending or not human_payoff:
            warnings.append("GENERIC_HUMAN_PAYOFF")

        if first_10_gain_count < 2:
            warnings.append("WEAK_FIRST_10_INFORMATION_GAIN")

        gain_times = [chunk.start for chunk, gains in gain_chunks if gains]
        max_gap = 0.0
        if gain_times:
            points = [0.0, *gain_times, target]
            max_gap = max(max(0.0, b - a) for a, b in zip(points, points[1:]))
        else:
            max_gap = target
        if target >= 45 and (information_gain_count < 3 or max_gap > 15.0):
            warnings.append("WEAK_INFORMATION_DENSITY")

        hook_strength = min(10, 2 + 2 * len(hook_1_gains)) if first_3 else 0
        second_hook_strength = min(10, 2 * len(hook_2_gains)) if three_7 else 0
        viability = max(0, min(10, round((hook_strength + second_hook_strength) / 2)))
        if first_10_gain_count >= 2:
            viability = min(10, viability + 2)
        if background_too_early:
            viability = max(0, viability - 2)

        blocker_codes = {
            "SETUP_ONLY_FIRST_10_SECONDS", "UNPAID_CURIOSITY_DEBT",
            "GENERIC_HUMAN_PAYOFF", "WEAK_FIRST_10_INFORMATION_GAIN",
        }
        passed = not any(code in blocker_codes for code in warnings)
        return RetentionLintResult(
            pass_=passed,
            hook_1=first_3,
            hook_2=three_7,
            information_gain_10s=seven_10,
            hook_strength=hook_strength,
            second_hook_strength=second_hook_strength,
            first_10s_viability=viability,
            background_tax="high" if background_too_early else ("medium" if background_chunks else "low"),
            curiosity_debt=curiosity_state,
            proper_noun_load="high" if len(proper_nouns) > 2 else ("medium" if len(proper_nouns) > 1 else "low"),
            information_gain_count=information_gain_count,
            second_reveal_present=any(bool(gains) for chunk, gains in gain_chunks if 3 <= chunk.start < target),
            correction_present=any("correction" in gains for _, gains in gain_chunks),
            human_payoff_present=human_payoff,
            generic_ending=generic_ending,
            warnings=list(dict.fromkeys(warnings)),
            checkpoints={
                str(point): sorted(_gain_types(_window_text(chunks, max(0, point - 1.5), point + 1.5)))
                for point in (2, 5, 10, 15, 25, 40) if point <= target
            },
            max_information_gap_sec=round(max_gap, 2),
            hook_1_type=_primary_gain_type(hook_1_gains),
            hook_2_type=_primary_gain_type(hook_2_gains),
            estimated_background_entry_second=(round(background_chunks[0].start, 2) if background_chunks else None),
            estimated_first_evidence_second=(round(evidence_positions[0], 2) if evidence_positions else None),
            estimated_second_information_gain_second=(round(gain_times[1], 2) if len(gain_times) > 1 else None),
        )


retention_lint = RetentionLint()
