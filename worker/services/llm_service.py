import os
import json
import re
import random
import time
from google import genai
from worker.config import GEMINI_API_KEYS


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
    "Mật mã thức tỉnh nằm ở bình luận ghim...",
    "Tôi đã ghim bài học xương máu ở phần bình luận...",
    "Sự thật tàn nhẫn nhất được ghim ngay bên dưới...",
    "Đọc bình luận ghim để lấy chìa khóa bứt phá...",
    "Bí ẩn đằng sau câu chuyện này đã được ghim dưới phần bình luận...",
    "Câu trả lời cho câu hỏi lớn nhất của bạn đã được ghim bên dưới...",
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
        from worker.config import GROQ_API_KEY, OPENROUTER_API_KEY
        self.gemini_keys = GEMINI_API_KEYS
        self.groq_key = GROQ_API_KEY
        self.openrouter_key = OPENROUTER_API_KEY
        
        self.api_available = len(self.gemini_keys) > 0 or bool(self.groq_key) or bool(self.openrouter_key)
        
        if self.gemini_keys:
            self.model = genai.Client(api_key=self.gemini_keys[0])
            print(f"[LLMService] Gemini AI initialized successfully with {len(self.gemini_keys)} keys [OK]")
        elif self.groq_key:
            print("[LLMService] Groq AI initialized as primary LLM (Gemini keys unavailable) [OK]")
        elif self.openrouter_key:
            print("[LLMService] OpenRouter AI initialized as primary LLM (Gemini/Groq keys unavailable) [OK]")
        else:
            print("[LLMService] ERROR: No LLM API keys set. Production generation is blocked.")

    def _call_llm(self, prompt: str) -> str:
        """Gọi LLM với cơ chế tự phục hồi, xoay vòng nhiều key + model Gemini và failover sang Groq / OpenRouter"""
        errors = []
        
        # Danh sách các mô hình Gemini hỗ trợ (xoay vòng khi bị 429 quota per-model)
        models_to_try = [
            os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
        ]
        # Xóa bớt trùng lặp nhưng giữ thứ tự
        seen = set()
        models_to_try = [m for m in models_to_try if not (m in seen or seen.add(m))]

        # 1. Thử gọi các key Gemini kết hợp xoay vòng models
        for idx, api_key in enumerate(self.gemini_keys):
            try:
                client = genai.Client(api_key=api_key)
                for model_name in models_to_try:
                    try:
                        response = client.models.generate_content(
                            model=model_name,
                            contents=prompt,
                        )
                        if response and getattr(response, "text", None):
                            self.model = client
                            print(f"[LLMService] Success using Gemini (Key {api_key[:6]}..., Model {model_name}) ✅")
                            return response.text
                        print(f"[LLMService Warning] Response text empty from Gemini model {model_name}")
                    except Exception as m_err:
                        m_err_str = str(m_err)
                        errors.append(f"Gemini (Key {api_key[:6]}..., Model {model_name}): {m_err_str}")
                        if "429" in m_err_str or "RESOURCE_EXHAUSTED" in m_err_str:
                            print(f"[LLMService Warning] 429 Rate Limit on model {model_name}. Switching to next Gemini model...")
                            continue
                        else:
                            # Lỗi khác (không phải 429), thử model tiếp theo
                            continue
            except Exception as e:
                errors.append(f"Gemini (Key {api_key[:6]}...): {e}")
                
        # 2. Thử gọi Groq
        if self.groq_key:
            try:
                import requests
                url = "https://api.groq.com/openai/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {self.groq_key}",
                    "Content-Type": "application/json"
                }
                body = {
                    "model": "llama-3.3-70b-versatile",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7
                }
                response = requests.post(url, headers=headers, json=body, timeout=30)
                if response.status_code == 200:
                    res_data = response.json()
                    content = res_data["choices"][0]["message"]["content"]
                    if content:
                        print("[LLMService] Failover success using Groq (Llama-3.3-70B-Versatile) ✅")
                        return content
                errors.append(f"Groq API error {response.status_code}: {response.text}")
            except Exception as e:
                errors.append(f"Groq exception: {e}")

        # 3. Thử gọi OpenRouter
        if self.openrouter_key:
            try:
                import requests
                url = "https://openrouter.ai/api/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {self.openrouter_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/YuuuBin2k5/YuuuBin_Agent_Bot",
                    "X-Title": "YuuuBin Agent Bot"
                }
                body = {
                    "model": "google/gemini-2.5-flash:free",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7
                }
                response = requests.post(url, headers=headers, json=body, timeout=30)
                if response.status_code == 200:
                    res_data = response.json()
                    content = res_data["choices"][0]["message"]["content"]
                    if content:
                        print("[LLMService] Failover success using OpenRouter (Gemini-2.5-Flash-Free) ✅")
                        return content
                errors.append(f"OpenRouter API error {response.status_code}: {response.text}")
            except Exception as e:
                errors.append(f"OpenRouter exception: {e}")

        raise RuntimeError("Tất cả nhà cung cấp LLM (Gemini, Groq, OpenRouter) đều thất bại. Chi tiết lỗi: " + " | ".join(errors))

    def _call_gemini_with_fallback(self, prompt: str, fallback_func=None) -> str:
        """Call a real LLM provider or fail the job; never manufacture production content."""
        if not self.api_available:
            raise RuntimeError("No LLM provider is configured for production generation.")
        try:
            return self._call_llm(prompt)
        except Exception as e:
            raise RuntimeError(f"All configured LLM providers failed: {e}") from e

    def call_gemini_direct(self, prompt: str) -> str:
        """Gọi trực tiếp các LLM theo chuỗi dự phòng và ném lỗi nếu tất cả thất bại (dùng cho dịch thuật cốt lõi)"""
        if not self.api_available:
            raise RuntimeError("Không có API Key nào được thiết lập hoặc cấu hình lỗi.")
        return self._call_llm(prompt)


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
            raise RuntimeError(f"LLM returned invalid JSON for the 30-day plan: {e}") from e

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
                               content_category: str = "", is_long_philosophy: bool = False,
                               video_language: str = "vi") -> dict:
        """Sinh kịch bản hoàn chỉnh với Hook đa dạng, phân cảnh chuyên nghiệp, CTA tự nhiên và bộ công cụ 2026 YouTube & TikTok SEO tối ưu"""

        # Random hook style để tránh lặp lại giữa các video
        hook_style = random.choice(HOOK_STYLES)
        # Random CTA để tránh nhàm chán
        cta_hint = random.choice(CTA_TEMPLATES)
        # Mood nhạc phù hợp
        music_description = MUSIC_MOOD_MAP.get(music_mood, MUSIC_MOOD_MAP["educational"])

        if is_long_philosophy:
            prompt = f"""
Bạn là một diễn giả triết học truyền cảm hứng hàng đầu thế giới, nhà tâm lý học hành vi và chuyên gia sáng tạo kịch bản video viral triệu views trên TikTok, YouTube Shorts.
Khán giả của bạn khao khát được nghe những bài diễn thuyết sâu lắng, lay động lòng người, định nghĩa lại tư duy và thôi thúc họ đứng dậy hành động.

CHỦ ĐỀ/CÂU NÓI TRIẾT LÝ GỐC: "{topic}"
Ý TƯỞNG TIÊU ĐỀ: "{title_idea}"
ĐỐI TƯỢNG NGƯỜI XEM MỤC TIÊU: "{audience}"
MOOD NHẠC NỀN GỢI Ý: {music_description}

NHIỆM VỤ: Hãy dựng lên một kịch bản nói (speech script) mang sắc thái truyền cảm hứng sâu sắc, đánh mạnh vào cảm xúc của {audience}, có cấu trúc nhịp điệu trầm bổng rõ rệt và BẮT BUỘC phải liên hệ trực tiếp với một HÀNH ĐỘNG CỤ THỂ, hình ảnh đời thường mang tính biểu tượng cao để tạo tính trực quan (visual) mạnh mẽ cho người nghe.

ĐỘ DÀI & ĐỊNH DẠNG YÊU CẦU:
1. ĐỘ DÀI KỊCH BẢN (full_voice_script): Đạt từ 140 đến 180 từ tiếng Việt (Súc tích, cô đọng, bỏ hết các từ thừa thãi như "nhé", "nha", "đấy", "hoàn toàn", "thực sự" để đảm bảo tốc độ thuyết minh sâu lắng mà vẫn khớp với thời lượng vàng hoàn hảo dưới 60 giây).
2. ĐỊNH DẠNG GIỌNG ĐỌC (MỘT ĐOẠN DUY NHẤT - CỰC KỲ QUAN TRỌNG): 
   - Toàn bộ kịch bản thuyết minh phải viết liền mạch thành MỘT ĐOẠN VĂN DUY NHẤT (a single continuous paragraph block).
   - Tuyệt đối không chứa bất kỳ tiêu đề phân đoạn nào như "[Mở đầu]", "[Nội dung chính]", "[Cao trào]", "[Kết luận]", hay các thẻ phân cảnh trong kịch bản nói.
   - Tuyệt đối không sử dụng các từ chuyển ý khô khan như "Thứ nhất", "Thứ hai", "Hơn nữa", "Tóm lại". Hãy kết nối tự nhiên bằng dòng cảm xúc trôi chảy.
3. QUY TẮC NỘI DUNG & KIẾN TRÚC THẨM MỸ RETENTION:
   - NGHỆ THUẬT NHẤN ÂM GIỌNG ĐỌC ELEVENLABS V3 (BẮT BUỘC):
      • Hãy chủ động chèn các Audio Tags biểu cảm trong ngoặc vuông như [dramatic], [excited], [whispers] ở các bước ngoặt cảm xúc để giọng AI đọc nhập vai tự nhiên nhất.
      • VIẾT HOA các từ trọng tâm kịch tính (ví dụ: SỰ THẬT, THẤT BẠI, SỤP ĐỔ, QUYẾT ĐỊNH) để công cụ ElevenLabs v3 tự động nâng tông và nhấn giọng đanh thép.
      • Sử dụng dấu ba chấm (...) ở các đoạn tĩnh lặng suy ngẫm, dấu gạch ngang (—) ở các đoạn ngắt nhịp thở đột ngột, và ngắt câu ngắn 4-8 từ bằng dấu phẩy (,) để phụ đề karaoke nhảy nhịp nhàng.
   - DYNAMIC CONTRARIAN HOOK (3 Giây Đầu — BẮT BUỘC TUYỆT ĐỐI):
      ❌ KHAI TỬ HOÀN TOÀN — CẤM TUYỆT ĐỐI dùng bất kỳ mẫu câu hỏi sáo rỗng sau:
         • "Bạn có biết..."          • "Bạn có đang mắc lỗi này không?"
         • "Có bao giờ bạn..."       • "Hôm nay mình sẽ chia sẻ..."
         • "Chào các bạn..."         • "Bạn có bao giờ tự hỏi..."
         • Bất kỳ câu hỏi Yes/No nào mở đầu bằng "Bạn có..."
     ✅ Hook phải là một TUYÊN NGÔN TRIẾT LÝ NGƯỢC DÒNG: Đưa thẳng sự thật tàn nhẫn hoặc
        nghịch lý gây sốc lên đầu câu. Độ dài: 8–12 từ tiếng Việt. Không chào, không hỏi,
        không giải thích — chỉ khẳng định đanh thép làm người xem giật mình dừng ngón tay.
   - CẤU TRÚC VÒNG LẶP VÔ TẬN (Seamless Loop): Hãy tính toán sao cho CÂU CUỐI CÙNG của kịch bản kết thúc bằng một vế câu mở (lửng lơ) và câu này khi đọc nối tiếp lại với CÂU ĐẦU TIÊN (Hook) của video sẽ tạo thành một câu văn hoàn chỉnh, logic và mượt mà về mặt ngữ nghĩa, khiến người xem xem lại liên tục mà không nhận ra video đã kết thúc.
   - RÀNG BUỘC ĐỘ DÀI TỪ VỰNG SÚC TÍCH: Loại bỏ hoàn toàn tất cả các từ đệm thừa thãi (nhé, nha, đấy, hoàn toàn, quả thực...). Câu nói phải súc tích, giàu hình ảnh, nhịp điệu đanh thép.
   - Giai đoạn 1 (Chạm nỗi đau): Nói về sự thất bại, cô độc, bất lực khi nỗ lực đổ sông đổ biển, chạm vào mong muốn buông xuôi của {audience}.
   - Giai đoạn 2 (Hành động cụ thể): Liên hệ trực tiếp và mô tả sống động một HÀNH ĐỘNG đời thường, cụ thể, mang tính biểu tượng của một con người khi vấp ngã (ví dụ: thắt chặt lại dây giày thể thao cũ kỹ lúc 5h sáng, lau vệt nước mắt bước ra ngoài trời giông bão, bặm môi bám víu vào cạnh bàn đứng lên...).
   - Giai đoạn 3 (Cao trào cảm xúc): Định nghĩa lại vinh quang thực sự. Khẳng định vinh quang không nằm ở chiến thắng, mà nằm ở khoảnh khắc lý trí thét lên "không được bỏ cuộc" khi đầu gối khuỵu xuống. Vết sẹo trên đầu gối chính là huy chương cho lòng dũng cảm.
   - Giai đoạn 4 (Đúc kết & Kêu gọi / CTA): Tuyệt đối nghiêm cấm các câu kêu gọi sáo rỗng như "Hãy follow kênh nhé", "Bấm tim nếu thấy hay". AI BẮT BUỘC phải sinh CTA (cta_text) kích thích người xem dừng lại đọc bình luận (Comment Dwelling Time) để tăng thời gian giữ chân, gợi sự tò mò cao độ về bình luận ghim. Sử dụng hoặc biến tấu sâu sắc từ các mẫu: "Mật mã thức tỉnh nằm ở bình luận ghim...", "Tôi đã ghim bài học xương máu ở phần bình luận...", "Sự thật tàn nhẫn nhất được ghim ngay bên dưới...", "Đọc bình luận ghim để lấy chìa khóa bứt phá...".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DƯỚI ĐÂY LÀ VÍ DỤ MẪU HOÀN HẢO ĐỂ BẠN HỌC THEO (FEW-SHOT LEARNING):
Câu trích dẫn gốc: "Vinh quang lớn nhất trong cuộc sống không nằm ở việc không bao giờ vấp ngã mà nằm ở việc đứng dậy sau mỗi lần vấp ngã." - Nelson Mandela

Kịch bản đầu ra mong đợi (full_voice_script):
"Đừng bao giờ chấp nhận nằm lại nơi bóng tối ngay cả khi mọi nỗ lực đổ sông đổ biển. Cố tổng thống Nelson Mandela từng nói vinh quang lớn nhất không nằm ở việc không bao giờ vấp ngã, mà nằm ở việc đứng dậy sau mỗi lần đổ vỡ, thế nhưng hai từ đứng dậy chưa bao giờ là dễ dàng khi bạn đang rệu rã dưới đáy vực sâu. Tôi từng chứng kiến một người bạn phá sản ở tuổi ba mươi, khóc thẫn thờ giữa căn phòng trống đầy giấy nợ; nhưng ngay lúc năm giờ sáng hôm sau, với đôi bàn tay run rẩy, cậu ấy đã cúi xuống, thắt chặt lại sợi dây giày thể thao cũ kỹ và bước ra ngoài trời giông bão. Hành động cúi xuống buộc dây giày nhỏ bé ấy chính là vinh quang nhất, bởi vinh quang không phải là ánh pháo hoa rực rỡ khi chiến thắng, mà là lúc bạn cô độc nhất, đầu gối khuỵu xuống vì cú tát của cuộc đời nhưng lý trí vẫn thét lên không được bỏ cuộc để bặm môi đứng dậy. Vết sẹo trên đầu gối bạn không phải là biểu tượng của sự thất bại, nó là tấm huy chương cho lòng dũng cảm; vì vậy nếu ngày hôm nay bạn mang một trái tim trầy xước, ngày mai khi mặt trời lên, hãy cứ cúi xuống buộc lại dây giày để bước tiếp, bởi từ chối nằm lại nơi bóng tối chính là lúc vinh quang bắt đầu."
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

QUY TẮC PHÂN CẢNH (SCENES LAYOUT):
- BẮT BUỘC TUYỆT ĐỐI: Phải phân tách kịch bản thuyết minh dài thành một mảng JSON chứa từ 5 đến 7 scene độc lập, mỗi scene tối đa 40 từ. Nghiêm cấm gộp toàn bộ thành 1 scene duy nhất chạy suốt video.
- Phân cảnh phải tương ứng với tiến trình câu chuyện, mỗi cảnh kéo dài 4-5 giây. Tổng số cảnh phải từ 10 đến 15 phân cảnh để phủ hết thời lượng 45-60 giây của video.
- Mỗi cảnh phải có 'overlay_text' là từ/cụm từ cực kỳ sâu sắc hoặc thông điệp cốt lõi của phân cảnh đó (tối đa 4-5 từ).
- Từ khóa Pexels: Phải có 'vertical' hoặc 'portrait', mô tả cảnh quay sâu lắng, tĩnh lặng và mô tả sinh động các hành động cụ thể trong bài phát biểu (Ví dụ: "hands tying shoelaces vertical", "lonely person walking morning portrait", "sunlight breaking through trees vertical").

ĐẦU RA: Trả về ĐÚNG JSON sau, không có văn bản khác:
{{
  "video_title_idea": "Tiêu đề triết học sâu sắc dưới 60 ký tự",
  "hook_text_3s": "Câu hook/trích dẫn triết lý mở đầu ngắn gọn",
  "full_voice_script": "Toàn bộ kịch bản thuyết minh triết lý dài 180-240 từ tiếng Việt viết dưới dạng MỘT ĐOẠN VĂN DUY NHẤT liền mạch, giàu nhạc điệu ngắt nghỉ, đan xen câu chuyện hành động cụ thể, tuyệt đối không có tiêu đề phân đoạn.",
  "voice_gender": "male",
  "music_mood": "emotional",
  "music_description": "Cảm xúc sâu lắng, piano nhẹ nhàng hoài niệm",
  "cta_text": "Câu kêu gọi hành động bắt buộc kích thích người xem dừng lại đọc bình luận ghim để tăng Comment Dwelling Time",
  "seo_tags_metadata": {{
    "title": "Tiêu đề TikTok tối ưu sâu sắc",
    "hashtags": ["trietlycuocsong", "chamsocbanthan", "tuduytichcuc", "ynghiacuocsong"],
    "tiktok_cover_hook": ["Cover 1", "Cover 2", "Cover 3"],
    "tiktok_microblog_caption": "Caption micro-blog có hook + xuống dòng thân thiện, KHÔNG chứa các dấu thăng/hashtag ở cuối",
    "tiktok_pinned_comment": "Bình luận ghim chiêm nghiệm tâm đắc",
    "youtube_title_options": ["Lựa chọn tiêu đề YT 1", "Lựa chọn tiêu đề YT 2", "Lựa chọn tiêu đề YT 3"],
    "youtube_scannable_description": "Mô tả YT hoàn chỉnh phân tích triết lý sâu sắc"
  }},
  "scenes_layout_json": [
    {{
      "scene_id": 1,
      "duration": 5,
      "visual_search_keywords": "thoughtful person rain vertical",
      "overlay_text": "Trích dẫn mở đầu"
    }},
    {{
      "scene_id": 2,
      "duration": 5,
      "visual_search_keywords": "close up hands tying shoelaces cinematic moody lighting vertical",
      "overlay_text": "Hành động cụ thể"
    }},
    {{
      "scene_id": 3,
      "duration": 5,
      "visual_search_keywords": "sunlight breaking through trees vintage 35mm film look portrait",
      "overlay_text": "Vinh quang bắt đầu"
    }}
  ]
}}
LƯU Ý: CHỈ TRẢ VỀ JSON HỢP LỆ. KHÔNG CÓ KÝ TỰ MARKDOWN.
"""
        else:
            prompt = f"""
Bạn là chuyên gia viết kịch bản video TikTok viral, có khả năng giữ người xem đến hết video 90% thời gian.

THÔNG TIN VIDEO:
- Chủ đề kênh: "{topic}"
- Thể loại hôm nay: "{content_category}"
- Ý tưởng tiêu đề (Ngày {day_number}): "{title_idea}"
- Đối tượng người xem: "{audience}"
- Mood nhạc nền gợi ý: {music_description}

NHIỆM VỤ: Viết kịch bản video TikTok dọc 9:16, thời lượng 40-50 giây.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
QUY TẮC VIẾT HOOK 3 GIÂY ĐẦU — DYNAMIC CONTRARIAN HOOK (BẮT BUỘC TUYỆT ĐỐI)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

❌ KHAI TỬ HOÀN TOÀN — CẤM TUYỆT ĐỐI dùng bất kỳ mẫu câu hỏi sáo rỗng sau:
   • "Bạn có biết..."          • "Bạn có đang mắc lỗi này không?"
   • "Có bao giờ bạn..."       • "Hôm nay mình sẽ chia sẻ..."
   • "Chào các bạn..."         • "Bạn có bao giờ tự hỏi..."
   • "Xin chào, hôm nay..."    • Bất kỳ câu hỏi Yes/No nào mở đầu bằng "Bạn có..."
   Vi phạm bất kỳ điều trên → Hook bị coi là THẤT BẠI hoàn toàn.

✅ CÔNG THỨC BẮT BUỘC — DYNAMIC CONTRARIAN HOOK:
   Hook phải được tùy biến 100% dựa trên triết lý cốt lõi của video hiện tại.
   Viết theo một trong hai trường phái:
     [A] TUYÊN NGÔN NGƯỢC DÒNG (Contrarian Statement):
         Đưa thẳng một sự thật tàn nhẫn hoặc nghịch lý gây sốc lên đầu câu.
         KHÔNG chào hỏi, KHÔNG hỏi, KHÔNG giải thích — chỉ khẳng định thẳng.
     [B] GÁO NƯỚC LẠNH (Wake-up Call):
         Phá vỡ niềm tin sai lầm phổ biến nhất mà đám đông đang tin.
         Câu phải làm người xem giật mình dừng ngón tay cái lại.

   ĐỘ DÀI BẮT BUỘC: 8 đến 12 từ tiếng Việt. Không dài hơn, không ngắn hơn.
   CẤU TRÚC CÂU: Chủ ngữ + Vị ngữ mạnh + Bổ ngữ gây sốc.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FEW-SHOT EXAMPLES (Học theo chính xác — xoay vòng phong cách):

  Chủ đề: Einstein / Vòng lặp điên rồ / Thay đổi tư duy
  ✅ Hook chuẩn: "Chăm chỉ một cách mù quáng chính là sự điên rồ."
  ❌ Hook bị cấm: "Bạn có biết Einstein từng nói gì về sự điên rồ không?"

  Chủ đề: Carl Jung / Vô thức / Lặp lại hành vi
  ✅ Hook chuẩn: "Thứ bạn gọi là định mệnh, thực chất là sự lặp lại mù quáng."
  ❌ Hook bị cấm: "Có bao giờ bạn cảm thấy mình cứ lặp đi lặp lại không?"

  Chủ đề: Francis Bacon / Tri thức / Tư duy phản biện
  ✅ Hook chuẩn: "Kẻ lười tư duy đang tự biến mình thành nô lệ kiểu mới."
  ❌ Hook bị cấm: "Bạn có đang mắc lỗi này trong cuộc sống không?"

  Chủ đề: Kỹ năng / Học tập / Phát triển bản thân
  ✅ Hook chuẩn: "Đọc sách nhiều mà không hành động là tự ru ngủ bản thân."
  ❌ Hook bị cấm: "Hôm nay mình sẽ chia sẻ bí quyết học nhanh hiệu quả."

  Chủ đề: Tiền bạc / Tài chính / Thói quen chi tiêu
  ✅ Hook chuẩn: "Người nghèo không thiếu tiền, họ thiếu hệ thống tư duy tiền."
  ❌ Hook bị cấm: "Bạn có muốn biết bí quyết quản lý tài chính không?"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


QUY TẮC VIẾT KỊCH BẢN (FULL SCRIPT) & CẤU TRÚC VÒNG LẶP VÔ TẬN (Seamless Loop):
✅ CẤU TRÚC VÒNG LẶP VÔ TẬN: Viết câu cuối cùng của kịch bản kết thúc bằng một vế câu mở (lửng lơ). Câu này khi đọc nối tiếp lại với CÂU ĐẦU TIÊN (Hook) của video phải tạo thành một câu văn hoàn chỉnh, logic và cực kỳ mượt mà về ngữ nghĩa, khiến người xem tự động quay lại xem tiếp mà không phát hiện ra video đã hết.
✅ RÀNG BUỘC ĐỘ DÀI TỪ VỰNG SÚC TÍCH: Giới hạn nghiêm ngặt số lượng từ tiếng Việt sinh ra. Toàn bộ kịch bản chỉ dài từ 90 đến 125 từ tiếng Việt. Dùng câu ngắn (5-8 từ). Loại bỏ hoàn toàn tất cả các từ thừa thãi thói quen nói (nhé, nha, đấy, hoàn toàn, quả thực, thực sự, tự nhiên...). Câu nói phải cực kỳ cô đọng, súc tích để đảm bảo tốc độ đọc tự nhiên khớp với thời lượng gốc và giảm tải cho bộ lọc co dãn Tempo của FFmpeg.
✅ Viết như đang nói chuyện thật ngoài đời, không phải đọc văn bản. Dùng cấu trúc rõ: Hook → Vấn đề → Giải pháp → Kết quả → CTA lửng lơ kích thích comment.
❌ Tuyệt đối nghiêm cấm các câu kêu gọi sáo rỗng như "Hãy follow kênh nhé", "Like và share ngay", "Bấm tim nếu thấy hay", "Bấm vào link bio".
✅ BẮT BUỘC sinh CTA (cta_text) theo cơ chế kích thích người xem dừng lại đọc bình luận (Comment Dwelling Time) để tăng giữ chân, gợi sự tò mò cao độ về bình luận ghim. Sử dụng hoặc biến tấu sâu sắc từ các mẫu: "Mật mã thức tỉnh nằm ở bình luận ghim...", "Tôi đã ghim bài học xương máu ở phần bình luận...", "Sự thật tàn nhẫn nhất được ghim ngay bên dưới...", "Đọc bình luận ghim để lấy chìa khóa bứt phá...".
❌ Không viết như bài luận hoặc bài giới thiệu sản phẩm

QUY TẮc PHÂN CẢNH (SCENES LAYOUT):
- Cảnh 1 (3-4 giây): Chứa HOOK - Video nền phải bắt mắt ngay
- Cảnh 2-N (3-5 giây/cảnh): Triển khai nội dung chính
- Cảnh cuối (3-4 giây): CTA tự nhiên dạng mở
- Overlay text mỗi cảnh: Chọn từ/cụm từ quan trọng nhất của cảnh đó (tối đa 5 từ)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
QUY TẮC BẮT BUỘC CHO TRƯỜNG `visual_search_keywords` (Aesthetic B-Roll Formula):
❌ TUYỆT ĐỐI CẤM: Từ khóa trừu tượng hoặc vô hình ("hối hận", "tư duy", "thành công", "cảm xúc", "niềm tin", "kinh nghiệm", "cơ hội", "hy vọng").
✅ CÔNG THỨC BẮT BUỘC — 4 thành phần nối tiếp nhau:
   [Chủ thể cụ thể] + [Hành động vật lý rõ ràng] + [CỤM PHONG CÁCH ĐIỆN ẢNH] + "vertical"

CÁC CỤM PHONG CÁCH ĐIỆN ẢNH (xoay vòng, mỗi cảnh dùng 1 cụm khác nhau):
  • "cinematic moody lighting"  → ánh sáng trầm, bóng tối nghệ thuật
  • "vintage 35mm film look"    → hạt film, màu hoài niệm
  • "dark neon aesthetics"      → neon tím/xanh trong bóng đêm đô thị
  • "grainy retro portrait"     → chân dung hạt nhỏ, retro
  • "cyberpunk color grade"     → màu tím/cam cyberpunk tương lai

Ví dụ HOÀN HẢO (học theo chính xác):
  "man walking alone rainy street dark neon aesthetics vertical"
  "close up hands typing laptop coffee shop cinematic moody lighting vertical"
  "woman staring window rain vintage 35mm film look portrait"
  "young person sitting rooftop city night cyberpunk color grade vertical"
  "close up financial chart phone screen grainy retro portrait vertical"
Ví dụ SAI (bị từ chối hoàn toàn): "success mindset" | "emotional journey" | "thought leadership" | "inspiration"
✅ Từ khóa PHẢI kết thúc bằng "vertical" hoặc "portrait".
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ĐẦU RA: Trả về ĐÚNG JSON sau, không có văn bản khác:
{{
  "video_title_idea": "Tiêu đề SEO cuốn hút dưới 60 ký tự",
  "hook_text_3s": "Câu hook 3 giây đầu mạnh mẽ, ngắn gọn",
  "full_voice_script": "Toàn bộ kịch bản đọc tự nhiên như nói chuyện dạng vòng lặp vô tận, khoảng 90-125 từ tiếng Việt",
  "music_mood": "{music_mood}",
  "music_description": "{music_description}",
  "cta_text": "Câu kêu gọi hành động bắt buộc kích thích người xem dừng lại đọc bình luận ghim để tăng Comment Dwelling Time",
  "pinned_comment": "Một câu hỏi mở sâu sắc hoặc nhận định phản biện gây tranh luận để ghím bình luận, kích nổ tương tác",
  "caption_seo": "Đoạn mô tả 3 phần: Hook phụ thị giác + Câu hỏi kích thích bình luận + Đoạn chứa từ khóa SEO",
  "seo_tags_metadata": {{
    "title": "Tiêu đề TikTok Studio tối ưu",
    "hashtags": ["hashtag_ngach_broad", "hashtag_chu_de_core", "hashtag_cu_the_1", "hashtag_cu_the_2", "#YuuBin"]
  }},
  "scenes_layout_json": [
    {{
      "scene_id": 1,
      "duration": 4,
      "visual_search_keywords": "person doing specific action vertical",
      "overlay_text": "Từ khóa nổi bật cảnh này"
    }}
  ]
}}

LƯU Ý: CHỈ TRẢ VỀ JSON HỢP LỆ. KHÔNG CÓ KÝ TỰ MARKDOWN.
"""

        def get_mock_details():
            if is_long_philosophy:
                mock_data = {
                    "video_title_idea": title_idea,
                    "hook_text_3s": f"Hãy suy ngẫm câu nói này: {topic}",
                    "full_voice_script": (
                        f"Hãy lắng nghe và chiêm nghiệm sâu sắc câu nói này: {topic}. "
                        "Trong hành trình cuộc sống, chúng ta thường vội vã chạy theo những giá trị bên ngoài, "
                        "nhưng thực ra ý nghĩa đích thực lại nằm ở sự bình yên và thấu hiểu nội tâm. "
                        "Mỗi thói quen nhỏ ta gieo trồng hôm nay sẽ định hình nên số phận ta ngày mai. "
                        "Hãy dừng lại một chút giữa bộn bề để nhìn nhận lại con đường mình đang đi. "
                        "Khi bạn thay đổi tư duy, thế giới xung quanh bạn cũng sẽ tự khắc đổi thay theo. "
                        "Hãy kiên nhẫn tích lũy từng ngày, vì sự thông thái cần có thời gian để chín muồi. "
                        "Đừng quá lo lắng về tương lai, hãy trân trọng và sống trọn vẹn trong từng khoảnh khắc hiện tại. "
                        "Đó chính là bí mật lớn nhất để đạt được hạnh phúc vững bền mà ai cũng có thể làm được."
                    ),
                    "voice_gender": "male",
                    "music_mood": "emotional",
                    "music_description": "Cảm xúc sâu lắng, piano nhẹ nhàng hoài niệm",
                    "cta_text": "Hãy trân trọng và sống trọn vẹn từng khoảnh khắc.",
                    "seo_tags_metadata": {
                        "title": f"Chiêm nghiệm triết lý: {topic[:30]}",
                        "hashtags": ["trietlycuocsong", "chamsocbanthan", "tuduytichcuc", "ynghiacuocsong"],
                        "tiktok_cover_hook": ["Triết lý cuộc sống", "Suy ngẫm sâu sắc", "Bài học đắt giá"],
                        "tiktok_microblog_caption": f"Hãy cùng suy ngẫm sâu sắc về câu nói triết lý nổi tiếng: {topic}.\n\nCuộc sống hiện đại bận rộn khiến chúng ta quên đi những giá trị tinh thần cốt lõi. Hy vọng video này sẽ giúp bạn tìm lại sự bình yên trong tâm hồn.",
                        "tiktok_pinned_comment": "Bạn tâm đắc nhất với điều gì trong câu nói triết lý này? Hãy bình luận chiêm nghiệm bên dưới nhé!",
                        "youtube_title_options": [
                            f"Ý nghĩa sâu sắc của câu nói: {topic[:30]}",
                            "Bài học cuộc sống thay đổi hoàn toàn tư duy của bạn",
                            "Triết lý sâu sắc ai cũng cần nghe ít nhất một lần"
                        ],
                        "youtube_scannable_description": "Phân tích và chiêm nghiệm sâu sắc triết lý cuộc sống...\n\nĐón xem nhiều video ý nghĩa mỗi ngày!"
                    },
                    "scenes_layout_json": [
                        {"scene_id": i + 1, "duration": 6, "visual_search_keywords": "thoughtful calm nature vertical", "overlay_text": f"Suy ngẫm bài học {i+1}"}
                        for i in range(25)
                    ]
                }
                return json.dumps(mock_data, ensure_ascii=False)

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

        output_language = "English" if video_language == "en" else "Vietnamese"
        prompt = f"""MANDATORY OUTPUT LANGUAGE: {output_language}.
Write every viewer-facing value in {output_language}, including title, hook, full_voice_script,
CTA, captions, pinned comments, hashtags, and overlay_text. Keep visual_search_keywords in English.
This rule overrides every conflicting language example or instruction below.

{prompt}"""
        raw_response = self._call_gemini_with_fallback(prompt, get_mock_details)
        cleaned = self._clean_json_string(raw_response)
        try:
            return json.loads(cleaned)
        except Exception as e:
            raise RuntimeError(f"LLM returned invalid JSON for video details: {e}") from e

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
        except Exception as e:
            raise RuntimeError(f"LLM returned invalid JSON for viral analysis: {e}") from e

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
        except Exception as e:
            raise RuntimeError(f"LLM returned invalid JSON for hook generation: {e}") from e

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
            raise RuntimeError(f"LLM failed to analyze music mood: {e}") from e

    def generate_seo_metadata_for_dub(self, vietnamese_transcript: str, original_video_title: str = None) -> dict:
        """
        Dựa trên lời thoại tiếng Việt đã dịch lồng tiếng và tiêu đề gốc của video (nếu có),
        Gemini sẽ sinh ra một tiêu đề Việt hóa cuốn hút, mô tả SEO và câu hook 3 giây tối ưu.
        """
        title_context = f"\nTIÊU ĐỀ GỐC CỦA VIDEO NƯỚC NGOÀI: \"{original_video_title}\"" if original_video_title else ""
        
        prompt = f"""
Hãy đóng vai là một chuyên gia marketing và SEO video TikTok/YouTube Shorts hàng đầu Việt Nam.
Hãy phân tích nội dung lời thoại tiếng Việt đã dịch lồng tiếng và tiêu đề gốc dưới đây để tối ưu hóa SEO và tạo ra kết quả dưới định dạng JSON block hợp lệ.
{title_context}

LỜI THOẠI TIẾNG VIỆT ĐÃ DỊCH LỒNG TIẾNG:
---
{vietnamese_transcript}
---

NHIỆM VỤ:
1. Đọc kỹ kịch bản thuyết minh tiếng Việt và tiến hành viết lại, nâng cấp toàn diện kịch bản đó dưới tên trường "video_script".
   - QUY TẮC "KHOẢNG TRỐNG TÒ MÒ" (CURIOSITY GAP): Trong kịch bản thuyết minh viết lại ("video_script"), cứ mỗi 7-10 giây (hoặc mỗi 2-3 câu thoại ngắn), AI bắt buộc phải nhúng một "Khoảng trống tò mò" bằng các cụm từ bẻ gãy tư duy tuyến tính để kích thích giữ chân người xem (ví dụ: "Nhưng sự thật lại trái ngược hoàn toàn...", "Và đây là sai lầm mà 99% mọi người đều mắc phải...", "Nhưng ít ai biết bí mật thực sự đằng sau là...", "Bí ẩn thực sự bắt đầu từ đây...").
   - Kịch bản viết lại phải đảm bảo tính tự nhiên, nhịp điệu sinh động, súc tích, cực kỳ lôi cuốn.

2. BẮT BUỘC trả về kết quả dưới định dạng JSON block hợp lệ duy nhất, tuân thủ chính xác cấu trúc schema sau:
{{
  "video_script": "Nội dung câu kịch bản/bản dịch tiếng Việt đã được viết lại, nâng cấp và chèn các Curiosity Gaps để tối ưu giữ chân người xem...",
  "caption_seo": "Đoạn văn mô tả thu hút người xem gồm 3 phần: (1) Hook phụ thị giác kích thích tò mò, (2) Câu hỏi kích thích người xem để lại bình luận tranh luận tăng tương tác, và (3) Đoạn văn ngắn chứa các từ khóa SEO ngách tự nhiên.",
  "pinned_comment": "Câu hỏi mở cực kỳ sâu sắc, lửng lơ hoặc một góc nhìn phản biện gây tranh cãi mạnh mẽ liên quan đến video hiện tại để người dùng ghim dưới mục bình luận, kích nổ cuộc chiến tranh luận sôi nổi của khán giả.",
  "hashtags": ["#tag_ngach_broad", "#tag_chu_de_core", "#YuuBin"]
}}

3. THIẾT LẬP QUY TẮC PHÂN BỔ HASHTAG CHẶT CHẼ:
- Danh sách `hashtags` chỉ được chứa từ 4 đến 5 thẻ bắt đầu bằng dấu thăng (#):
  + 1-2 thẻ ngách rộng (ví dụ: #trietlycuocsong, #phattrienbanthan, #xuhuong, #dichlongtieng)
  + 2 thẻ cụ thể sát theo nội dung của video (ví dụ: #tuduymo, #kynangsong, #baihoccuocsong)
  + 1 thẻ bắt buộc định vị thương hiệu của kênh là: #YuuBin

LƯU Ý: CHỈ TRẢ VỀ JSON HỢP LỆ VÀ ĐÚNG CẤU TRÚC SCHEMA TRÊN. KHÔNG CHỨA BẤT KỲ VĂN BẢN NÀO KHÁC NGOÀI JSON BLOCK.
"""
        def fallback():
            # Trích xuất chuỗi text thô làm video_script
            script_fallback = vietnamese_transcript or "Nội dung video thuyết minh ý nghĩa."
            
            # Cắt ngắn kịch bản để tạo caption ngắn gọn
            summary_text = script_fallback[:120] + "..." if len(script_fallback) > 120 else script_fallback
            caption_seo_fallback = (
                f"Bạn có đồng tình với góc nhìn này không? Hãy xem hết video để tìm câu trả lời nhé! "
                f"Bài học sâu sắc về cuộc sống: {summary_text}"
            )
            
            # Thêm mảng hashtags mặc định chứa #YuuBin
            hashtags_fallback = ["#trietlycuocsong", "#phattrienbanthan", "#baihoccuocsong", "#YuuBin"]
            
            pinned_comment_fallback = "Liệu bạn có nghĩ sự thật này có thực sự đúng không, hay chúng ta chỉ đang tự lừa dối mình? Hãy bình luận chiêm nghiệm của bạn ở phía dưới nhé!"
            
            # Tạo dictionary fallback đầy đủ cả trường mới và các trường tương thích ngược
            fallback_dict = {
                "video_script": script_fallback,
                "caption_seo": caption_seo_fallback,
                "pinned_comment": pinned_comment_fallback,
                "hashtags": hashtags_fallback,
                "title": original_video_title or "Video lồng tiếng mới",
                "hook_text_3s": script_fallback.split(".")[0].strip()[:60] if script_fallback else "Bí mật này sẽ khiến bạn thay đổi suy nghĩ!"
            }
            return json.dumps(fallback_dict, ensure_ascii=False)

        try:
            raw = self._call_gemini_with_fallback(prompt, fallback)
            cleaned = self._clean_json_string(raw)
            parsed_json = json.loads(cleaned)
            
            # Thêm tiêu đề và hook_text_3s tự động để tương thích ngược 100% với worker/main.py
            if "title" not in parsed_json:
                parsed_json["title"] = original_video_title or "Video lồng tiếng mới"
            if "hook_text_3s" not in parsed_json:
                # Lấy câu đầu tiên của script làm hook
                script = parsed_json.get("video_script", "")
                first_sentence = script.split(".")[0].strip() if script else ""
                parsed_json["hook_text_3s"] = first_sentence[:60]
            if "pinned_comment" not in parsed_json:
                parsed_json["pinned_comment"] = "Theo bạn thì đâu là lựa chọn đúng đắn nhất trong hoàn cảnh này? Bình luận chia sẻ suy nghĩ của bạn bên dưới nha!"
                
            return parsed_json
        except Exception as e:
            raise RuntimeError(f"LLM failed to generate SEO metadata for dubbing: {e}") from e

    def generate_philosophical_comment(self, topic: str, script: str, video_language: str = "vi") -> str:
        """
        Sinh bình luận 2-3 đoạn về chủ đề và kịch bản video để đăng tự động.
        """
        language = "en" if str(video_language).lower().startswith("en") else "vi"
        output_language = "English" if language == "en" else "Vietnamese"
        prompt = f"""
You are a thoughtful short-form content writer. Write a natural 2-3 paragraph pinned comment in {output_language}, around 80-150 words, for a TikTok/Shorts video.

CHỦ ĐỀ VIDEO: "{topic}"
KỊCH BẢN VIDEO: "{script}"

YÊU CẦU:
- Viết 2-3 đoạn văn ngắn gọn, dễ đọc, truyền tải thông điệp sâu sắc, chữa lành, hoặc đúc rút triết lý liên quan đến chủ đề trên.
- Giọng văn tự nhiên, đồng cảm, như một người bạn tri kỷ đang chiêm nghiệm cùng người xem.
- Không dùng ngôn ngữ clickbait hay kêu gọi sáo rỗng.
- Kết thúc bằng một câu hỏi mở gợi suy nghĩ hoặc kích thích thảo luận lành mạnh.
- Trả về duy nhất đoạn văn bình luận, không chứa tiêu đề hay lời giải thích nào khác.
"""
        def fallback():
            if language == "en":
                return (
                    "Peace often begins in the way we notice the small things that are still here. "
                    "On difficult days, a warm meal, a cleared desk, or one honest conversation can remind us that life has not stopped offering something worth holding onto.\n\n"
                    "What small moment helped you feel lighter today?"
                )
            return (
                "Bình yên không ở đâu xa, nó nằm ngay trong cách chúng ta trân trọng những điều nhỏ bé xung quanh mình. "
                "Có những ngày mệt mỏi, chỉ cần một bữa cơm ấm, một góc bàn sạch sẽ cũng đủ để ta nhận ra cuộc đời vẫn còn nhiều điều đáng quý.\n\n"
                "Hôm nay, điều nhỏ bé nào đã khiến bạn cảm thấy biết ơn và mỉm cười?"
            )
        return self._call_gemini_with_fallback(prompt, fallback)

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
