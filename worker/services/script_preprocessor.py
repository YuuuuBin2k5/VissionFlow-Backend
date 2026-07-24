"""
Script Pre-Processor — Tiền Xử Lý Kịch Bản Viral Audio 2026
=============================================================
Theo tài liệu ToiUuGiongDocAI.docx:
  1. Chunking kịch bản thành phân đoạn 500-800 ký tự (tránh voice drift)
  2. Chuyển số → chữ (tránh đọc sai)
  3. Chuẩn hóa ký tự đặc biệt ($, %, km, ...)
  4. Chèn SSML <break> cho Multilingual v2
  5. Chèn emotion tags [whispers], [hesitates], [pause] cho Eleven v3
"""
from __future__ import annotations

import re


# ═══════════════════════════════════════════════════════════════════════════
# 1. NUMBER → WORDS (số → chữ) — Hỗ trợ tiếng Việt
# ═══════════════════════════════════════════════════════════════════════════

_VI_UNITS = ["", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
_VI_TEENS = [
    "mười", "mười một", "mười hai", "mười ba", "mười bốn",
    "mười lăm", "mười sáu", "mười bảy", "mười tám", "mười chín"
]
_VI_TENS = ["", "mười", "hai mươi", "ba mươi", "bốn mươi", "năm mươi",
            "sáu mươi", "bảy mươi", "tám mươi", "chín mươi"]


def _num_under_1000_vi(n: int) -> str:
    if n == 0:
        return "không"
    if n < 10:
        return _VI_UNITS[n]
    if n < 20:
        return _VI_TEENS[n - 10]
    if n < 100:
        tens = _VI_TENS[n // 10]
        unit = n % 10
        if unit == 0:
            return tens
        if unit == 1:
            return f"{tens} mốt"
        if unit == 5:
            return f"{tens} lăm"
        return f"{tens} {_VI_UNITS[unit]}"
    hundreds = n // 100
    remainder = n % 100
    if remainder == 0:
        return f"{_VI_UNITS[hundreds]} trăm"
    if remainder < 10:
        return f"{_VI_UNITS[hundreds]} trăm lẻ {_num_under_1000_vi(remainder)}"
    return f"{_VI_UNITS[hundreds]} trăm {_num_under_1000_vi(remainder)}"


def number_to_words_vi(n: int) -> str:
    """Chuyển số nguyên → chữ tiếng Việt (hỗ trợ đến hàng tỷ)."""
    if n < 0:
        return f"âm {number_to_words_vi(-n)}"
    if n == 0:
        return "không"
    parts = []
    if n >= 1_000_000_000:
        parts.append(f"{_num_under_1000_vi(n // 1_000_000_000)} tỷ")
        n %= 1_000_000_000
    if n >= 1_000_000:
        parts.append(f"{_num_under_1000_vi(n // 1_000_000)} triệu")
        n %= 1_000_000
    if n >= 1_000:
        parts.append(f"{_num_under_1000_vi(n // 1_000)} nghìn")
        n %= 1_000
    if n > 0:
        parts.append(_num_under_1000_vi(n))
    return " ".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# 2. NORMALIZE TEXT — Chuẩn hóa văn bản trước khi gửi API
# ═══════════════════════════════════════════════════════════════════════════

def _replace_number_str(num_str: str) -> str:
    """Xóa dấu phẩy/chấm phân tách và chuyển sang chữ."""
    cleaned = re.sub(r"[,\.]", "", num_str)
    try:
        val = int(cleaned)
        return number_to_words_vi(val)
    except ValueError:
        return num_str


def normalize_numbers_and_symbols(text: str) -> str:
    """
    Bước 1: Thay thế đơn vị + ký hiệu đặc biệt.
    Bước 2: Thay thế số thuần túy còn lại thành chữ.
    """
    # 1. Đơn vị tiền tệ
    text = re.sub(r"\$(\d+(?:[,\.]\d+)*)", lambda m: f"{_replace_number_str(m.group(1))} đô la", text)
    text = re.sub(r"(\d+(?:[,\.]\d+)*)\s*USD\b", lambda m: f"{_replace_number_str(m.group(1))} đô la", text, flags=re.IGNORECASE)
    text = re.sub(r"(\d+(?:[,\.]\d+)*)\s*(?:VNĐ|VND)\b", lambda m: f"{_replace_number_str(m.group(1))} đồng", text, flags=re.IGNORECASE)
    text = re.sub(r"(\d+(?:[,\.]\d+)*)\s*%", lambda m: f"{_replace_number_str(m.group(1))} phần trăm", text)

    # 2. Đơn vị đo lường
    text = re.sub(r"(\d+(?:[,\.]\d+)*)\s*km\b", lambda m: f"{_replace_number_str(m.group(1))} ki-lô-mét", text, flags=re.IGNORECASE)
    text = re.sub(r"(\d+(?:[,\.]\d+)*)\s*kg\b", lambda m: f"{_replace_number_str(m.group(1))} ki-lô-gam", text, flags=re.IGNORECASE)
    text = re.sub(r"(\d+(?:[,\.]\d+)*)\s*m\b", lambda m: f"{_replace_number_str(m.group(1))} mét", text, flags=re.IGNORECASE)
    text = re.sub(r"(\d+(?:[,\.]\d+)*)\s*cm\b", lambda m: f"{_replace_number_str(m.group(1))} cen-ti-mét", text, flags=re.IGNORECASE)

    # 3. Ký tự đặc biệt
    text = re.sub(r"\bCtrl\+Z\b", "control Z", text, flags=re.IGNORECASE)
    text = re.sub(r"\bCtrl\+C\b", "control C", text, flags=re.IGNORECASE)
    text = re.sub(r"\bCtrl\+V\b", "control V", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+&\s+", " và ", text)

    # 4. Thay thế số thuần túy còn lại (bao gồm số phân tách bằng dấu phẩy/chấm)
    text = re.sub(r"(?<![\d\w])\d+(?:[,\.]\d+)*(?![\d\w])", lambda m: _replace_number_str(m.group(0)), text)

    return text


# ═══════════════════════════════════════════════════════════════════════════
# 3. CHUNKING — Chia nhỏ phân đoạn 500-800 ký tự
# ═══════════════════════════════════════════════════════════════════════════

def chunk_script(text: str, max_chars: int = 700) -> list[str]:
    """
    Chia kịch bản thành các phân đoạn ≤ max_chars ký tự.
    Mỗi phân đoạn PHẢI kết thúc tại ranh giới câu hoàn chỉnh.
    Nguồn: ToiUuGiongDocAI.docx - Chunking 500-800 ký tự.
    """
    if len(text) <= max_chars:
        return [text.strip()]

    sentence_pattern = re.compile(r"(?<=[.!?…])\s+")
    sentences = sentence_pattern.split(text)

    chunks: list[str] = []
    current_chunk = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        test = (current_chunk + " " + sentence).strip() if current_chunk else sentence
        if len(test) <= max_chars:
            current_chunk = test
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            if len(sentence) > max_chars:
                words = sentence.split()
                sub_chunk = ""
                for word in words:
                    if len(sub_chunk) + len(word) + 1 <= max_chars:
                        sub_chunk = (sub_chunk + " " + word).strip()
                    else:
                        if sub_chunk:
                            chunks.append(sub_chunk)
                        sub_chunk = word
                current_chunk = sub_chunk
            else:
                current_chunk = sentence

    if current_chunk:
        chunks.append(current_chunk.strip())

    return [c for c in chunks if c]


# ═══════════════════════════════════════════════════════════════════════════
# 4. SSML TAGS — Chèn thẻ break cho Multilingual v2
# ═══════════════════════════════════════════════════════════════════════════

_DRAMATIC_KEYWORDS = [
    "thất bại", "sụp đổ", "phá sản", "chết", "thảm họa", "khủng hoảng",
    "bí mật", "sự thật", "cú sốc", "bất ngờ", "kinh hoàng", "tuyệt vời",
    "kỳ diệu", "lịch sử", "triệu đô", "tỷ đô", "scandal", "tragedy",
    "collapse", "bankrupt", "disaster", "secret", "shocking", "million",
    "billion", "crisis", "failure", "comeback", "revolution"
]


def apply_dramatic_caps(text: str) -> str:
    """
    Viết hoa các từ khóa kịch tính để mô hình nhận diện trọng âm.
    Nguồn: ToiUuGiongDocAI.docx — Quy tắc viết hoa.
    """
    for keyword in _DRAMATIC_KEYWORDS:
        pattern = re.compile(r"\b" + re.escape(keyword) + r"\b", re.IGNORECASE)
        text = pattern.sub(keyword.upper(), text)
    return text


def inject_ssml_breaks_v2(text: str) -> str:
    """
    Chèn thẻ SSML <break> cho ElevenLabs Multilingual v2.
    - Sau dấu ba chấm: 0.8s pause (do dự)
    - Sau dấu gạch ngang (—): 0.5s pause (đột ngột)
    - Sau dấu chấm hỏi/chấm than: 0.3s pause (nhấn mạnh)
    Nguồn: ToiUuGiongDocAI.docx — Cơ chế kiểm soát khoảng dừng v2.
    """
    text = re.sub(r"\.\.\.", '...<break time="0.8s"/>', text)
    text = re.sub(r"—", '—<break time="0.5s"/>', text)
    text = re.sub(r"([!?])(\s)", r'\1<break time="0.3s"/>\2', text)
    return text


def inject_v3_emotion_tags(text: str) -> str:
    """
    Chèn emotion tags [dramatic], [excited], [whispers], [sighs] cho Eleven v3.
    Nguồn: ElevenLabs v3 Prompting & Audio Tags Best Practices.
    """
    whisper_triggers = ["bí mật", "thầm thì", "không ai biết", "chỉ một mình", "lén lút"]
    for trigger in whisper_triggers:
        if trigger.lower() in text.lower():
            text = re.sub(
                re.escape(trigger),
                f"[whispers] {trigger}",
                text,
                flags=re.IGNORECASE,
                count=1,
            )

    dramatic_triggers = ["thất bại", "sụp đổ", "phá sản", "khủng hoảng", "cú sốc", "bất ngờ", "kinh hoàng", "lịch sử"]
    for trigger in dramatic_triggers:
        if trigger.lower() in text.lower():
            text = re.sub(
                re.escape(trigger),
                f"[dramatic] {trigger}",
                text,
                flags=re.IGNORECASE,
                count=1,
            )

    excited_triggers = ["thành công", "tuyệt vời", "kỳ diệu", "triệu đô", "tỷ đô", "bứt phá", "kỷ lục"]
    for trigger in excited_triggers:
        if trigger.lower() in text.lower():
            text = re.sub(
                re.escape(trigger),
                f"[excited] {trigger}",
                text,
                flags=re.IGNORECASE,
                count=1,
            )

    text = re.sub(r"(:\s*)([A-ZÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝĂĐƠƯẠẶẤẦẨẪẮẰẲẴ])", r'\1[pause] \2', text)
    return text


# ═══════════════════════════════════════════════════════════════════════════
# 5. MAIN PREPROCESS API
# ═══════════════════════════════════════════════════════════════════════════

VIDEO_GENRE_MODEL_MAP = {
    "documentary": "eleven_v3",   # Eleven v3 hỗ trợ Tiếng Việt + Audio Tags biểu cảm nhất
    "storytelling": "eleven_v3",  # True-crime, tài liệu điện ảnh TikTok
    "explainer": "eleven_v3",     # Giải thích kiến thức sâu lắng
    "tutorial": "eleven_flash_v2_5", # Hướng dẫn kỹ thuật nhanh
    "promo": "eleven_flash_v2_5",    # Quảng cáo, bán hàng
}

ELEVENLABS_PARAMS_MAP = {
    "eleven_v3": {
        "stability": 0.42,         # Cân bằng hoàn hảo: vừa có dải tần biểu cảm, vừa không méo tiếng
        "similarity_boost": 0.82,  # Giữ giọng Adam sắc nét, rõ ràng chuẩn TikTok
        "style": 0.38,             # Khuếch đại kịch tính kiểu TikTok creator
        "use_speaker_boost": True,
    },
    "eleven_multilingual_v2": {
        "stability": 0.58,
        "similarity_boost": 0.82,
        "style": 0.05,
        "use_speaker_boost": True,
    },
    "eleven_flash_v2_5": {
        "stability": 0.50,
        "similarity_boost": 0.80,
        "style": 0.20,
        "use_speaker_boost": True,
    },
}


def preprocess_for_elevenlabs(
    text: str,
    model_id: str = "eleven_v3",
    apply_emotional_tags: bool = True,
) -> list[str]:
    """
    Pipeline tiền xử lý đầy đủ trước khi gửi đến ElevenLabs API.
    Nguồn: ToiUuGiongDocAI.docx — Chiến thuật Định dạng Văn bản.
    """
    print(f"[ScriptPreprocessor] Bắt đầu tiền xử lý. Model={model_id}, chars={len(text)}")

    text = normalize_numbers_and_symbols(text)
    print(f"[ScriptPreprocessor] ✅ Bước 1: Chuẩn hóa số/ký tự → {len(text)} chars")

    text = apply_dramatic_caps(text)
    print(f"[ScriptPreprocessor] ✅ Bước 2: Viết hoa từ khóa kịch tính")

    if apply_emotional_tags:
        if model_id == "eleven_v3":
            text = inject_v3_emotion_tags(text)
            print(f"[ScriptPreprocessor] ✅ Bước 3: Chèn emotion tags (Eleven v3)")
        elif model_id in ("eleven_multilingual_v2", "eleven_flash_v2_5"):
            text = inject_ssml_breaks_v2(text)
            print(f"[ScriptPreprocessor] ✅ Bước 3: Chèn SSML break tags")

    chunks = chunk_script(text, max_chars=700)
    print(f"[ScriptPreprocessor] ✅ Bước 4: Chunking → {len(chunks)} phân đoạn")

    return chunks


def get_elevenlabs_params(model_id: str) -> dict:
    """Lấy tham số ElevenLabs tối ưu theo model."""
    return ELEVENLABS_PARAMS_MAP.get(model_id, ELEVENLABS_PARAMS_MAP["eleven_v3"])


def resolve_model_for_genre(genre: str) -> str:
    """Chọn model ElevenLabs phù hợp theo thể loại nội dung."""
    return VIDEO_GENRE_MODEL_MAP.get(genre.lower(), "eleven_v3")
