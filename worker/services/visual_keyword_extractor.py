import re
import random
from typing import List

try:
    from google import genai
except ImportError:
    try:
        import google.generativeai as genai
    except ImportError:
        genai = None

from worker.config import GEMINI_API_KEYS


class VisualKeywordExtractor:
    """
    Thông minh hóa câu lệnh tìm kiếm B-Roll:
    Tự động biến các câu kịch bản AI dài (ví dụ: 'Cappy Para ngồi bên đống lửa trên bờ biển đêm...')
    thành 2-3 bộ từ khóa tiếng Anh ngắn gọn, súc tích chuẩn các trang stock Pexels/Pixabay.
    """

    # Danh sách từ dừng (Stop words) & từ thừa về Mascot/style không có trong kho stock video
    NOISE_WORDS = {
        "cappy", "para", "boni", "duck", "scholar", "robe", "mascot", "3d", "anime", "ghibli",
        "pixar", "render", "character", "godfather", "looking", "camera", "standing", "sitting",
        "holding", "wearing", "style", "cozy", "cinematic", "dramatic", "highly", "detailed",
        "4k", "8k", "hd", "wallpaper", "masterpiece", "concept", "art", "illustration"
    }

    # Bảng quy đổi chủ đề thông dụng sang từ khóa stock sắc nét
    TOPIC_STOCK_MAP = {
        "ship": ["burning ship ocean", "ancient sailing ship", "sea galleon twilight"],
        "fire": ["campfire night beach", "dramatic bonfire flames", "cozy fire light"],
        "forest": ["misty pine forest aerial", "deep woods sunlight", "foggy forest trees"],
        "ocean": ["dramatic ocean waves", "stormy sea sunset", "dark beach twilight"],
        "city": ["city night lights aerial", "rainy city street night", "tokyo neon lights"],
        "crowd": ["crowd walking city street", "blurred people walking", "busy urban sidewalk"],
        "money": ["money counting cash", "gold coins glowing", "financial growth chart"],
        "space": ["starry night sky milkyway", "deep space nebula", "glowing stars galaxy"],
        "rain": ["rain drops window night", "rainy street reflections", "stormy rain forest"],
        "mountain": ["majestic mountain peaks", "foggy mountain sunrise", "snowy mountain aerial"],
    }

    def __init__(self):
        self.api_keys = [k for k in GEMINI_API_KEYS if k and k != "YOUR_GEMINI_API_KEY_HERE"]
        self.client = None
        if self.api_keys and genai is not None:
            try:
                self.client = genai.Client(api_key=self.api_keys[0])
            except Exception as exc:
                print(f"[VisualKeywordExtractor Warning] Gemini Client init fallback: {exc}")

    def extract_keywords(self, prompt: str, scene_index: int = 1) -> List[str]:
        """
        Trích xuất 2-3 bộ từ khóa tìm kiếm B-Roll chất lượng cao.
        Ưu tiên dùng Gemini AI, nếu offline sẽ dùng Heuristic NLP Fallback.
        """
        prompt_clean = str(prompt or "").strip()
        if not prompt_clean:
            return ["aesthetic vertical", "nature vertical", "abstract vertical"]

        # 1. Thử dùng Gemini AI để sinh từ khóa stock chuẩn
        if self.client:
            try:
                ai_keywords = self._extract_with_gemini(prompt_clean)
                if ai_keywords:
                    print(f"[VisualKeywordExtractor Gemini] Scene #{scene_index} -> {ai_keywords}")
                    return ai_keywords
            except Exception as err:
                print(f"[VisualKeywordExtractor Warning] Gemini AI extraction failed: {err}")

        # 2. Heuristic NLP Fallback
        heuristic_keywords = self._extract_with_heuristics(prompt_clean)
        print(f"[VisualKeywordExtractor Heuristic] Scene #{scene_index} -> {heuristic_keywords}")
        return heuristic_keywords

    def _extract_with_gemini(self, prompt: str) -> List[str]:
        """Sử dụng Gemini AI để trích xuất 2-3 cụm từ khóa tìm kiếm video stock tiếng Anh ngắn."""
        system_instruction = (
            "You are a professional video editor and B-Roll researcher for Stock Video APIs (Pexels/Pixabay).\n"
            "Given a scene visual description or script snippet, extract 3 distinct, concise English search queries (2-4 words each).\n"
            "Focus strictly on real-world visual subjects, environments, lighting, and mood (e.g. 'burning ship ocean', 'foggy pine forest', 'rainy city night').\n"
            "DO NOT include fictional character names (Cappy, Boni), 3D render styles, or meta tags.\n"
            "Return JSON format: [\"query1\", \"query2\", \"query3\"]"
        )

        response = self.client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"Extract 3 stock video search queries for this scene:\n\"{prompt}\"",
            config={"response_mime_type": "application/json"}
        )

        if response and response.text:
            text = response.text.strip()
            data = json.loads(text)
            if isinstance(data, list) and len(data) > 0:
                cleaned = [re.sub(r'[^a-zA-Z0-9\s]', '', str(q)).strip() for q in data if q]
                return [q for q in cleaned if q][:3]

        return []

    def _extract_with_heuristics(self, prompt: str) -> List[str]:
        """Tách từ thông minh loại bỏ từ rác và tra cứu Topic Map."""
        words = re.findall(r'\b[a-zA-Z]{3,}\b', prompt.lower())
        meaningful_words = [w for w in words if w not in self.NOISE_WORDS]

        # Kiểm tra Topic Map
        matched_topics = []
        for word in meaningful_words:
            for topic_key, topic_queries in self.TOPIC_STOCK_MAP.items():
                if topic_key in word:
                    matched_topics.extend(topic_queries)

        if matched_topics:
            # Chọn ngẫu nhiên 3 chủ đề không lặp
            sampled = list(dict.fromkeys(matched_topics))
            random.shuffle(sampled)
            return sampled[:3]

        # Nếu không khớp topic, ghép 2-3 từ ý nghĩa nhất thành cụm từ khóa
        if len(meaningful_words) >= 2:
            query1 = " ".join(meaningful_words[:3])
            query2 = " ".join(meaningful_words[1:4]) if len(meaningful_words) >= 3 else f"{meaningful_words[0]} vertical"
            query3 = f"{meaningful_words[0]} aesthetic vertical"
            return list(dict.fromkeys([query1, query2, query3]))

        return ["aesthetic nature vertical", "dramatic lighting vertical", "atmospheric background vertical"]
