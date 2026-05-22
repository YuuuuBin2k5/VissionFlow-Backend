import os
import json
import re
import random
import google.generativeai as genai
from worker.config import GEMINI_API_KEY

# ============================================================
# CHIẾN LƯỢC HOOK - Rút ra từ promtai.txt (Prompt #3)
# Ưu tiên: Gây bất ngờ | Tạo tò mò | Đánh đúng cảm xúc | Thách thức | Gây mâu thuẫn
# ============================================================
HOOK_STYLES = [
    "gây bất ngờ và sốc nhẹ với con số thực tế hoặc sự thật ít ai biết",
    "đặt câu hỏi gây tò mò, khiến người xem bắt buộc phải biết câu trả lời",
    "kể một tình huống thực tế mà người xem có thể đồng cảm ngay lập tức",
    "thách thức quan niệm thông thường để gây ra mâu thuẫn nhận thức",
    "hứa hẹn tiết lộ một bí quyết hoặc thông tin nội bộ mà 99% chưa biết",
]

# ============================================================
# CTA CUỐI VIDEO - Rút ra từ promtvideo.txt (Prompt #6)
# Mục tiêu: Tăng follow bền vững, tự nhiên, không ép buộc
# ============================================================
CTA_TEMPLATES = [
    "Lưu video này lại để xem lại khi cần nhé! Và nếu bạn muốn những mẹo hay hơn, theo dõi kênh mình đi nào!",
    "Comment xuống dưới nếu bạn đã từng gặp tình huống này nhé! Mình đọc hết bình luận của mọi người đó!",
    "Chia sẻ video này cho bạn bè cần nghe điều này nha! Follow để không bỏ lỡ video tiếp theo!",
    "Phần 2 của chủ đề này sẽ còn hay hơn nhiều! Follow ngay để nhận thông báo nhé!",
    "Tag ngay một người bạn cần xem điều này! Hẹn gặp lại bạn ở video kế tiếp!",
]

# ============================================================
# MOOD NHẠC NỀN - Rút ra từ promtvideo.txt (Prompt #2)
# ============================================================
MUSIC_MOOD_MAP = {
    "motivational": "Truyền cảm hứng, nhịp điệu vừa phải, lofi uplift",
    "educational": "Nhẹ nhàng tập trung, lofi study, không gây xao nhãng",
    "trending": "Sôi động, nhịp nhanh, bắt trend TikTok hiện tại",
    "emotional": "Cảm xúc, piano nhẹ hoặc acoustic, tạo kết nối",
    "action": "Energetic, hype, tạo cảm giác urgent và kích thích hành động",
}

# ============================================================
# PHÂN LOẠI NỘI DUNG 30 NGÀY - Rút ra từ promtai.txt (Prompt #1 + #7)
# Phân tán đều, không trùng lặp, không giống nhau liên tiếp
# ============================================================
CONTENT_CATEGORIES_30_DAYS = [
    # Tuần 1: Gây tò mò, xây dựng nhận diện kênh
    "Sự thật bất ngờ & Con số gây sốc",        # Ngày 1
    "Câu chuyện cá nhân dễ đồng cảm",           # Ngày 2
    "Bí quyết thực chiến #1",                    # Ngày 3
    "Thách thức quan niệm thông thường",          # Ngày 4
    "Mẹo nhanh trong 30 giây",                   # Ngày 5
    "So sánh: Đúng vs Sai",                      # Ngày 6
    "Hỏi đáp / Giải đáp thắc mắc phổ biến",    # Ngày 7
    # Tuần 2: Xây dựng giá trị & giáo dục
    "Hướng dẫn từng bước (Step-by-step)",        # Ngày 8
    "Lỗi phổ biến cần tránh",                    # Ngày 9
    "Case study / Ví dụ thực tế",                # Ngày 10
    "Công cụ / Tài nguyên hữu ích",              # Ngày 11
    "Sự thật ít người biết #2",                  # Ngày 12
    "Chia sẻ hành trình cá nhân",               # Ngày 13
    "Recap / Tổng kết tuần trước",               # Ngày 14
    # Tuần 3: Tăng tương tác & cộng đồng
    "Thách thức / Challenge cộng đồng",          # Ngày 15
    "Phản bác quan niệm sai",                    # Ngày 16
    "Bí quyết thực chiến #2 (nâng cao)",         # Ngày 17
    "Behind the scenes / Hậu trường thực tế",   # Ngày 18
    "Top danh sách (Top 3, Top 5...)",            # Ngày 19
    "Câu chuyện truyền cảm hứng",               # Ngày 20
    "Q&A từ bình luận người xem",                # Ngày 21
    # Tuần 4: Giữ chân & xây dựng follow lâu dài
    "Chiến lược dài hạn & Tư duy đúng",         # Ngày 22
    "Mẹo nâng cao ít ai chia sẻ",               # Ngày 23
    "Thay đổi nhỏ - Kết quả lớn",               # Ngày 24
    "Chia sẻ tài nguyên miễn phí",              # Ngày 25
    "Cảnh báo: Điều cần tránh ngay",            # Ngày 26
    "Câu chuyện thành công từ cộng đồng",       # Ngày 27
    "Bí quyết thực chiến cuối cùng #3",         # Ngày 28
    "Nhìn lại hành trình 30 ngày",              # Ngày 29
    "Video kêu gọi cộng đồng & Định hướng tiếp theo", # Ngày 30
]


class LLMService:
    def __init__(self):
        api_key = GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY", "")
        if api_key:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel("gemini-3.5-flash")
            self.api_available = True
            print("[LLMService] Gemini AI initialized successfully ✅ (Using gemini-3.5-flash)")
        else:
            print("[LLMService] WARNING: GEMINI_API_KEY is not set. Using Mock Generator fallback.")
            self.api_available = False

    def _call_gemini_with_fallback(self, prompt: str, fallback_func) -> str:
        """Thực hiện gọi API với cơ chế tự phục hồi"""
        if not self.api_available:
            return fallback_func()
        try:
            response = self.model.generate_content(prompt)
            if response and response.text:
                return response.text
            raise Exception("Empty response from Gemini")
        except Exception as e:
            print(f"[LLMService Error] Gemini call failed: {e}. Falling back to mock...")
            return fallback_func()

    # ================================================================
    # PHƯƠNG THỨC 1: LẬP KẾ HOẠCH 30 NGÀY
    # Cải tiến từ: promtai.txt Prompt #1, #7
    # - Phân tán thể loại không trùng lặp theo tuần
    # - Mỗi video có mục tiêu rõ ràng (tăng view / tăng follow / tăng tương tác)
    # - Ưu tiên chủ đề dễ đồng cảm và dễ chia sẻ
    # ================================================================
    def generate_30_day_plan(self, topic: str, target_audience: str) -> list:
        """Sinh chuỗi kế hoạch 30 ngày với phân tán thể loại thông minh"""

        # Xây dựng hướng dẫn phân tán thể loại từ CONTENT_CATEGORIES_30_DAYS
        categories_guide = "\n".join([
            f"  - Ngày {i+1}: Thể loại → [{cat}]"
            for i, cat in enumerate(CONTENT_CATEGORIES_30_DAYS)
        ])

        prompt = f"""
Bạn là chuyên gia chiến lược nội dung TikTok hàng đầu Việt Nam, chuyên xây kênh từ 0 lên 100,000 follow.

CHỦ ĐỀ KÊNH: "{topic}"
ĐỐI TƯỢNG MỤC TIÊU: "{target_audience}"

NHIỆM VỤ: Lập kế hoạch nội dung 30 ngày theo đúng KHUNG THỂ LOẠI bên dưới. Mỗi ngày phải bám sát thể loại được chỉ định để đảm bảo sự đa dạng và không trùng lặp.

KHUNG THỂ LOẠI 30 NGÀY:
{categories_guide}

QUY TẮC VIẾT TIÊU ĐỀ (Theo công thức viral):
✅ Ngắn gọn dưới 60 ký tự
✅ Gây tò mò hoặc bất ngờ ngay từ đầu
✅ Ưu tiên con số cụ thể (Ví dụ: "3 bí quyết", "90% người không biết")
✅ Phù hợp với thể loại ngày đó
✅ Dễ chia sẻ và dễ đồng cảm với {target_audience}
❌ Không viết tiêu đề quá chung chung hoặc giống nhau giữa các ngày

QUY TẮC MỤC TIÊU VIDEO:
- Ngày 1-7: Mục tiêu TĂNG VIEWS (thu hút người mới)
- Ngày 8-14: Mục tiêu TĂNG THEO DÕI (giữ chân người xem)
- Ngày 15-21: Mục tiêu TĂNG TƯƠNG TÁC (bình luận, chia sẻ)
- Ngày 22-30: Mục tiêu XÂY CỘNG ĐỒNG (gắn kết, loyal viewers)

ĐẦU RA: Trả về ĐÚNG định dạng JSON array, không có bất kỳ văn bản nào khác:
[
  {{
    "day_number": 1,
    "content_category": "Thể loại video hôm nay",
    "video_title_idea": "Tiêu đề viral theo công thức",
    "concept_description": "Mô tả cụ thể về thông điệp, cảm xúc và hình ảnh truyền tải",
    "primary_goal": "VIEWS | FOLLOW | ENGAGEMENT | COMMUNITY",
    "music_mood": "motivational | educational | trending | emotional | action"
  }}
]

LƯU Ý: CHỈ TRẢ VỀ JSON HỢP LỆ. KHÔNG CÓ KÝ TỰ MARKDOWN.
"""
        def get_mock_plan():
            mock_plan = []
            for i in range(30):
                cat = CONTENT_CATEGORIES_30_DAYS[i]
                goals = ["VIEWS"] * 7 + ["FOLLOW"] * 7 + ["ENGAGEMENT"] * 7 + ["COMMUNITY"] * 9
                moods = list(MUSIC_MOOD_MAP.keys())
                mock_plan.append({
                    "day_number": i + 1,
                    "content_category": cat,
                    "video_title_idea": f"[{cat}] {topic} - Ngày {i+1}",
                    "concept_description": f"Video thể loại '{cat}' về chủ đề {topic} dành cho {target_audience}.",
                    "primary_goal": goals[i],
                    "music_mood": moods[i % len(moods)]
                })
            return json.dumps(mock_plan, ensure_ascii=False)

        raw_response = self._call_gemini_with_fallback(prompt, get_mock_plan)
        cleaned = self._clean_json_string(raw_response)
        try:
            return json.loads(cleaned)
        except Exception as e:
            print(f"[LLMService Error] Failed to parse 30-day plan JSON: {e}")
            return json.loads(get_mock_plan())

    # ================================================================
    # PHƯƠNG THỨC 2: SINH CHI TIẾT KỊCH BẢN VIDEO
    # Cải tiến từ: promtai.txt Prompt #2, #3, #4, #5 + promtvideo.txt Prompt #1, #5, #6
    # - Hook theo 5 phong cách tâm lý học (random mỗi lần sinh)
    # - Kịch bản tự nhiên như nói chuyện thật, không giống quảng cáo
    # - Phân cảnh có "text animation overlay" cho ý chính
    # - CTA cuối video tự nhiên, đa dạng, kêu gọi hành động thật sự
    # - Gợi ý mood nhạc nền phù hợp
    # ================================================================
    def generate_video_details(self, day_number: int, topic: str, title_idea: str,
                               audience: str, music_mood: str = "educational",
                               content_category: str = "") -> dict:
        """Sinh kịch bản hoàn chỉnh với Hook đa dạng, phân cảnh chuyên nghiệp và CTA tự nhiên"""

        # Random hook style để tránh lặp lại giữa các video
        hook_style = random.choice(HOOK_STYLES)
        # Random CTA để tránh nhàm chán
        cta_hint = random.choice(CTA_TEMPLATES)
        # Mood nhạc phù hợp
        music_description = MUSIC_MOOD_MAP.get(music_mood, MUSIC_MOOD_MAP["educational"])

        prompt = f"""
Bạn là chuyên gia viết kịch bản video TikTok viral, có khả năng giữ người xem đến hết video 90% thời gian.

THÔNG TIN VIDEO:
- Chủ đề kênh: "{topic}"
- Thể loại hôm nay: "{content_category}"
- Ý tưởng tiêu đề (Ngày {day_number}): "{title_idea}"
- Đối tượng người xem: "{audience}"
- Mood nhạc nền gợi ý: {music_description}

NHIỆM VỤ: Viết kịch bản video TikTok dọc 9:16, thời lượng 50-60 giây.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
QUY TẮC VIẾT HOOK 3 GIÂY ĐẦU (QUAN TRỌNG NHẤT):
Phong cách hook hôm nay: {hook_style}
→ Hook phải: Ngắn (dưới 15 từ), mạnh, khiến người xem KHÔNG THỂ lướt qua
→ Hook KHÔNG được: Giới thiệu bản thân, dùng "Xin chào", "Hôm nay mình sẽ..."
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

QUY TẮC VIẾT KỊCH BẢN (FULL SCRIPT):
✅ Viết như đang nói chuyện thật ngoài đời, không phải đọc văn bản
✅ Câu ngắn, 5-8 từ một câu. Ngắt nghỉ tự nhiên.
✅ Dùng từ cảm xúc: "thật ra", "bạn có biết không", "điều này đã thay đổi mình"
✅ Có cấu trúc rõ: Hook → Vấn đề → Giải pháp → Kết quả → CTA
✅ Phần CTA cuối tự nhiên, không ép buộc:
   Gợi ý CTA hôm nay: "{cta_hint}"
❌ Không dùng: "Hãy subscribe", "Like và share ngay", "Bấm vào link bio"
❌ Không viết như bài luận hoặc bài giới thiệu sản phẩm

QUY TẮC PHÂN CẢNH (SCENES LAYOUT):
- Cảnh 1 (3-4 giây): Chứa HOOK - Video nền phải bắt mắt ngay
- Cảnh 2-N (3-5 giây/cảnh): Triển khai nội dung chính
- Cảnh cuối (3-4 giây): CTA tự nhiên
- Overlay text mỗi cảnh: Chọn từ/cụm từ quan trọng nhất của cảnh đó (tối đa 5 từ)
- Từ khóa Pexels: Phải có 'vertical' hoặc 'portrait', cụ thể và dễ tìm thấy

ĐẦU RA: Trả về ĐÚNG JSON sau, không có văn bản khác:
{{
  "video_title_idea": "Tiêu đề SEO cuốn hút dưới 60 ký tự",
  "hook_text_3s": "Câu hook 3 giây đầu mạnh mẽ, ngắn gọn",
  "full_voice_script": "Toàn bộ kịch bản đọc tự nhiên như nói chuyện, khoảng 110-140 từ tiếng Việt",
  "music_mood": "{music_mood}",
  "music_description": "{music_description}",
  "cta_text": "Câu kêu gọi hành động cuối video tự nhiên",
  "seo_tags_metadata": {{
    "title": "Tiêu đề TikTok Studio tối ưu",
    "hashtags": ["hashtag1", "hashtag2", "hashtag3", "hashtag4", "hashtag5"]
  }},
  "scenes_layout_json": [
    {{
      "scene_id": 1,
      "duration": 4,
      "visual_search_keywords": "keyword specific vertical",
      "overlay_text": "Từ khóa nổi bật cảnh này"
    }}
  ]
}}

LƯU Ý: CHỈ TRẢ VỀ JSON HỢP LỆ. KHÔNG CÓ KÝ TỰ MARKDOWN.
"""
        def get_mock_details():
            mock_data = {
                "video_title_idea": title_idea,
                "hook_text_3s": "90% người làm điều này sai hoàn toàn!",
                "full_voice_script": (
                    f"Dừng lại! Bạn có đang mắc lỗi này không? "
                    f"Đây là điều hầu hết mọi người không biết về {topic}. "
                    f"Mình đã mất rất nhiều thời gian để nhận ra điều này. "
                    f"Thật ra chỉ cần thay đổi một thói quen nhỏ mỗi ngày. "
                    f"Áp dụng điều này liên tục trong hai tuần. "
                    f"Kết quả sẽ khiến bạn ngạc nhiên đấy! "
                    f"{cta_hint}"
                ),
                "music_mood": music_mood,
                "music_description": music_description,
                "cta_text": cta_hint,
                "seo_tags_metadata": {
                    "title": f"Bí quyết {topic} mà 99% không biết",
                    "hashtags": [
                        re.sub(r'\s+', '', topic.lower()),
                        "learnontiktok", "tiktokvietnam", "viral", "trending"
                    ]
                },
                "scenes_layout_json": [
                    {"scene_id": 1, "duration": 4, "visual_search_keywords": "surprised person vertical", "overlay_text": "Dừng lại!"},
                    {"scene_id": 2, "duration": 5, "visual_search_keywords": "thinking problem solution vertical", "overlay_text": "Lỗi 90% mắc phải"},
                    {"scene_id": 3, "duration": 5, "visual_search_keywords": "success achievement vertical", "overlay_text": "Bí quyết thực sự"},
                    {"scene_id": 4, "duration": 4, "visual_search_keywords": "happy result vertical", "overlay_text": "Kết quả bất ngờ!"},
                ]
            }
            return json.dumps(mock_data, ensure_ascii=False)

        raw_response = self._call_gemini_with_fallback(prompt, get_mock_details)
        cleaned = self._clean_json_string(raw_response)
        try:
            return json.loads(cleaned)
        except Exception as e:
            print(f"[LLMService Error] Failed to parse video details JSON: {e}")
            return json.loads(get_mock_details())

    # ================================================================
    # PHƯƠNG THỨC 3 (MỚI): PHÂN TÍCH VIDEO VIRAL & TÁI TẠO
    # Cải tiến từ: promtai.txt Prompt #6
    # - Phân tích công thức thành công của video viral
    # - Tái tạo phiên bản mới theo phong cách riêng của kênh
    # ================================================================
    def analyze_viral_and_recreate(self, viral_script: str, topic: str, audience: str) -> dict:
        """Phân tích kịch bản video viral và tái tạo phiên bản độc đáo cho kênh"""
        prompt = f"""
Bạn là chuyên gia phân tích nội dung TikTok viral.

KỊCH BẢN VIDEO VIRAL CẦN PHÂN TÍCH:
---
{viral_script}
---

CHỦ ĐỀ KÊNH CỦA TÔI: "{topic}"
ĐỐI TƯỢNG: "{audience}"

NHIỆM VỤ:
1. Phân tích ngắn gọn TẠI SAO video này viral (Hook, cảm xúc, cấu trúc, nhịp điệu)
2. Tái tạo phiên bản mới với PHONG CÁCH RIÊNG cho kênh "{topic}" - giữ nguyên các điểm mạnh nhưng thay đổi nội dung hoàn toàn

ĐẦU RA JSON:
{{
  "viral_analysis": {{
    "hook_formula": "Công thức hook video gốc sử dụng",
    "emotion_trigger": "Cảm xúc chính được kích hoạt (tò mò / bất ngờ / sợ bỏ lỡ / đồng cảm)",
    "retention_technique": "Kỹ thuật giữ người xem đến cuối",
    "key_strengths": ["Điểm mạnh 1", "Điểm mạnh 2", "Điểm mạnh 3"]
  }},
  "recreated_script": {{
    "hook_text_3s": "Hook mới áp dụng công thức tương tự",
    "full_voice_script": "Kịch bản mới hoàn toàn cho chủ đề của kênh",
    "video_title_idea": "Tiêu đề mới viral"
  }}
}}

LƯU Ý: CHỈ TRẢ VỀ JSON HỢP LỆ. KHÔNG CÓ KÝ TỰ MARKDOWN.
"""
        def fallback():
            return json.dumps({
                "viral_analysis": {
                    "hook_formula": "Dùng con số gây sốc + mâu thuẫn nhận thức",
                    "emotion_trigger": "tò mò + sợ bỏ lỡ",
                    "retention_technique": "Hứa hẹn câu trả lời từ đầu, tiết lộ dần",
                    "key_strengths": ["Hook mạnh 3 giây đầu", "Cấu trúc rõ ràng", "CTA tự nhiên"]
                },
                "recreated_script": {
                    "hook_text_3s": f"Điều này về {topic} sẽ thay đổi cách bạn nghĩ!",
                    "full_voice_script": f"Kịch bản mẫu về {topic} cho {audience}...",
                    "video_title_idea": f"Sự thật ít ai biết về {topic}"
                }
            }, ensure_ascii=False)

        raw = self._call_gemini_with_fallback(prompt, fallback)
        cleaned = self._clean_json_string(raw)
        try:
            return json.loads(cleaned)
        except Exception:
            return json.loads(fallback())

    # ================================================================
    # PHƯƠNG THỨC 4 (MỚI): SINH LOẠT HOOK ĐA DẠNG
    # Cải tiến từ: promtai.txt Prompt #3
    # - 20 hook theo 5 phong cách tâm lý học khác nhau
    # - Mạnh mẽ, tự nhiên, không giống quảng cáo
    # ================================================================
    def generate_hook_bank(self, topic: str, audience: str, count: int = 20) -> list:
        """Sinh ngân hàng hook đa dạng để dùng luân phiên trong chuỗi video"""
        prompt = f"""
Bạn là copywriter TikTok hàng đầu, chuyên viết câu hook 3 giây đầu video.

CHỦ ĐỀ: "{topic}"
ĐỐI TƯỢNG: "{audience}"

NHIỆM VỤ: Tạo đúng {count} câu hook khác nhau. Phân bổ đều theo 5 phong cách:
1. BẤT NGỜ/SỐC: Sự thật hoặc con số gây sốc nhẹ (4 câu)
2. TÒ MÒ: Đặt câu hỏi khiến người xem PHẢI biết câu trả lời (4 câu)
3. ĐỒNG CẢM: Tình huống quen thuộc người xem đã trải qua (4 câu)
4. MÂU THUẪN: Thách thức quan niệm thông thường (4 câu)
5. BÍ MẬT: Hứa hẹn tiết lộ thông tin nội bộ/ít ai biết (4 câu)

QUY TẮC:
✅ Mỗi hook dưới 12 từ
✅ Mạnh mẽ và tự nhiên
✅ Không giống quảng cáo
✅ Không dùng "Xin chào", "Hôm nay mình"
✅ Không trùng lặp ý tưởng giữa các hook

ĐẦU RA JSON array:
[
  {{"style": "BẤT NGỜ", "hook": "Câu hook bất ngờ về {topic}"}},
  ...
]

LƯU Ý: CHỈ TRẢ VỀ JSON HỢP LỆ. KHÔNG CÓ KÝ TỰ MARKDOWN.
"""
        def fallback():
            hooks = []
            styles = ["BẤT NGỜ", "TÒ MÒ", "ĐỒNG CẢM", "MÂU THUẪN", "BÍ MẬT"]
            for i in range(count):
                hooks.append({
                    "style": styles[i % len(styles)],
                    "hook": f"Hook mẫu #{i+1} về {topic}"
                })
            return json.dumps(hooks, ensure_ascii=False)

        raw = self._call_gemini_with_fallback(prompt, fallback)
        cleaned = self._clean_json_string(raw)
        try:
            return json.loads(cleaned)
        except Exception:
            return json.loads(fallback())

    def analyze_music_mood(self, song_title: str, artist_name: str) -> dict:
        """Phân tích cảm xúc bài hát và đề xuất mood cùng visual keywords tương thích"""
        prompt = f"""
        Bạn là chuyên gia phân tích nhạc lý và hình ảnh nghệ thuật. Hãy phân tích bài hát sau:
        BÀI HÁT: "{song_title}"
        NGHỆ SĨ: "{artist_name}"

        NHIỆM VỤ:
        1. Phân loại cảm xúc chủ đạo (Mood) của bài hát này và khớp vào đúng 1 trong 4 nhãn dưới đây:
           - SAD_RAIN: Nhạc buồn, lofi trầm, mưa rơi hoài niệm.
           - CYBERPUNK_NIGHT: Nhạc remix, EDM sôi động, bass đập căng, thành phố neon rực rỡ.
           - COZY_CHILL: Nhạc acoustic, nhẹ nhàng, quán cafe ấm áp, thư giãn.
           - FOCUS_LOFI: Nhạc lofi học bài, không lời sâu lắng, bàn học ban đêm.
        2. Viết 1 câu Caption (dưới 80 ký tự) cực kỳ lôi cuốn, mang tính deep, nghệ thuật, hợp tâm trạng bài hát (tiếng Việt, không suồng sã).
        3. Đề xuất đúng 3 từ khóa tiếng Anh về cảnh phim dọc (Ví dụ: "rainy night window portrait", "neon city cyberpunk") để tìm kiếm Pexels video nền.

        ĐẦU RA JSON DUY NHẤT:
        {{
          "mood": "SAD_RAIN / CYBERPUNK_NIGHT / COZY_CHILL / FOCUS_LOFI",
          "caption": "Câu caption tiếng Việt",
          "visual_keywords": "visual search keywords for pexels"
        }}
        LƯU Ý: CHỈ TRẢ VỀ JSON HỢP LỆ. KHÔNG CÓ KÝ TỰ MARKDOWN.
        """

        def fallback():
            return json.dumps({
                "mood": "COZY_CHILL",
                "caption": f"Lắng nghe nhịp điệu bình yên từ {song_title}...",
                "visual_keywords": "cozy room warm lights portrait"
            }, ensure_ascii=False)

        try:
            raw = self._call_gemini_with_fallback(prompt, fallback)
            cleaned = self._clean_json_string(raw)
            return json.loads(cleaned)
        except Exception as e:
            print(f"[LLMService Error] Failed to analyze music mood: {e}. Using fallback...")
            return json.loads(fallback())

    def _clean_json_string(self, text: str) -> str:
        """Làm sạch chuỗi trả về từ LLM để đảm bảo chỉ có chuỗi JSON hợp lệ"""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```json") or lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        match = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', text)
        if match:
            text = match.group(0)
        return text
