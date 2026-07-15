import json
import re

from worker.services.llm_service import LLMService


class ModelRouter:
    """
    Thin multi-model boundary for new pipelines.
    V1 delegates to LLMService, which already handles Gemini/Groq/OpenRouter fallback.
    """

    def __init__(self):
        self.llm = LLMService()

    def generate_json(self, prompt: str, fallback_func):
        raw = self.llm._call_gemini_with_fallback(prompt, lambda: json.dumps(fallback_func(), ensure_ascii=False))
        cleaned = self.llm._clean_json_string(raw)
        try:
            return json.loads(cleaned)
        except Exception as exc:
            print(f"[ModelRouter Warning] JSON parse failed: {exc}. Using fallback payload.")
            return fallback_func()

    @staticmethod
    def _script_quality_issues(script: str, language: str) -> list[str]:
        text = " ".join(str(script or "").split())
        words = re.findall(r"\b[\wÀ-ỹ'-]+\b", text, flags=re.UNICODE)
        sentences = [part.strip() for part in re.split(r"[.!?]+", text) if part.strip()]
        issues = []
        minimum = 95 if language == "vi" else 105
        maximum = 145 if language == "vi" else 155
        if len(words) < minimum:
            issues.append(f"Kịch bản quá ngắn ({len(words)} từ); cần {minimum}-{maximum} từ để câu chuyện đủ sức nặng.")
        if len(words) > maximum:
            issues.append(f"Kịch bản quá dài ({len(words)} từ); cần cô đọng còn {minimum}-{maximum} từ.")
        if len(sentences) < 6:
            issues.append("Nhịp kể quá ít câu; cần 6-10 câu nói tự nhiên với độ dài đan xen.")
        generic_phrases = (
            "cuộc sống là hành trình", "mọi thứ rồi sẽ ổn", "hãy yêu bản thân",
            "đừng bao giờ bỏ cuộc", "believe in yourself", "everything will be okay",
            "life is a journey", "never give up",
        )
        found = [phrase for phrase in generic_phrases if phrase in text.lower()]
        if found:
            issues.append("Có câu động lực sáo rỗng: " + ", ".join(found))
        concrete_markers = (
            "khi", "lúc", "sáng", "đêm", "căn phòng", "tin nhắn", "bàn tay", "cánh cửa",
            "when", "that night", "morning", "room", "message", "hands", "door",
        )
        if sum(marker in text.lower() for marker in concrete_markers) < 2:
            issues.append("Thiếu một khoảnh khắc đời thường cụ thể khiến người nghe nhìn thấy chính mình.")
        return issues

    def _polish_split_screen_story(self, payload: dict, topic: str, audience: str, language: str) -> dict:
        original_script = str(payload.get("full_voice_script") or "")
        issues = self._script_quality_issues(original_script, language)
        output_language = "Vietnamese" if language == "vi" else "English"
        issue_text = "\n".join(f"- {issue}" for issue in issues) or "- Bản nháp đạt độ dài nhưng vẫn cần tăng tính tự nhiên và sức thuyết phục."
        prompt = f"""
# Role: Senior Short-Video Story Editor

Rewrite only the spoken story and hooks from the draft below. The final result must sound like one
real person confiding in another, not a motivational essay. Return valid JSON only.

# Story goal
- Topic: {topic}
- Audience: {audience}
- Output language: {output_language}
- Length: 95-145 words in Vietnamese, or 105-155 words in English.
- Use this progression: disruptive hook -> recognizable private moment -> rising consequence ->
  surprising reframe -> small believable action -> emotionally earned closing line.
- Build one coherent mini-story. Each sentence must cause the next sentence; do not list advice.
- Include one concrete moment with a place, action, or object. Show it before explaining its meaning.
- Mix short sentences with medium sentences. Use spoken transitions naturally and avoid theatrical prose.
- Persuade through recognition and cause-and-effect, never commands or unsupported claims.
- The final line should echo the hook, but it must still sound complete and natural.
- Do not use celebrity quotes, fake personal testimony, generic inspiration, headings, or narration labels.

# Problems detected in the draft
{issue_text}

# Draft
hook_text_3s: {payload.get('hook_text_3s', '')}
full_voice_script: {original_script}
a_b_test_hooks: {json.dumps(payload.get('a_b_test_hooks', []), ensure_ascii=False)}

# Required JSON
{{
  "hook_text_3s": "8-14 words",
  "full_voice_script": "the polished single-paragraph story",
  "a_b_test_hooks": ["hook 1", "hook 2", "hook 3"],
  "story_beats": {{
    "recognition": "the relatable moment",
    "turn": "the change in understanding",
    "payoff": "the earned conclusion"
  }}
}}
"""

        def fallback():
            return {
                "hook_text_3s": payload.get("hook_text_3s", ""),
                "full_voice_script": original_script,
                "a_b_test_hooks": payload.get("a_b_test_hooks", []),
                "story_beats": {},
            }

        polished = self.generate_json(prompt, fallback)
        polished_script = str(polished.get("full_voice_script") or "").strip()
        if polished_script:
            payload["full_voice_script"] = polished_script
            payload["hook_text_3s"] = polished.get("hook_text_3s") or payload.get("hook_text_3s", "")
            payload["a_b_test_hooks"] = polished.get("a_b_test_hooks") or payload.get("a_b_test_hooks", [])
            payload["story_beats"] = polished.get("story_beats") or {}
        payload["script_quality_check"] = {
            "passed": not self._script_quality_issues(payload.get("full_voice_script", ""), language),
            "issues_before_polish": issues,
            "issues_after_polish": self._script_quality_issues(payload.get("full_voice_script", ""), language),
            "editorial_pass_applied": True,
        }
        return payload

    def generate_split_screen_details(self, topic: str, title_idea: str, audience: str, metadata: dict) -> dict:
        bottom_visual_type = metadata.get("bottom_visual_type") or metadata.get("top_visual_type") or "daily_life"
        tone = metadata.get("tone") or "healing"
        visual_examples = {
            "cooking": "hands chopping vegetables, brewing coffee, frying eggs, plating simple food",
            "daily_life": "walking in rain, cleaning a desk, morning commute, quiet coffee shop",
            "satisfying": "folding clothes, cleaning glass, arranging desk items, packing orders",
        }
        visual_hint = visual_examples.get(bottom_visual_type, visual_examples["daily_life"])

        language = "en" if str(metadata.get("video_language") or "vi").lower().startswith("en") else "vi"
        output_language = "English" if language == "en" else "Vietnamese"
        prompt = f"""
Bạn là biên tập viên chiến lược cho YouTube Shorts/TikTok, chuyên tạo video split-screen dọc có khả năng giữ chân cao, giọng đọc tự nhiên, sâu sắc nhưng không sáo rỗng.
Ngôn ngữ bắt buộc cho toàn bộ nội dung người xem đọc/nghe: {output_language}. Từ khóa tìm video vẫn dùng tiếng Anh.

NHIỆM VỤ:
Tạo kịch bản tiếng Việt cho video dọc 25-40 giây theo format split-screen:
- Nửa trên: B-roll triết lý/ẩn dụ, thay đổi theo từng scene, có cảm xúc, chuyển động, góc máy rõ.
- Nửa dưới: Một video lifestyle/satisfying chạy liền mạch cùng một chủ đề cụ thể, không đổi chủ đề giữa chừng.

THÔNG TIN ĐẦU VÀO:
CHỦ ĐỀ: "{topic}"
TIÊU ĐỀ GỢI Ý: "{title_idea}"
ĐỐI TƯỢNG: "{audience}"
VISUAL NỬA DƯỚI: "{bottom_visual_type}" ({visual_hint})
TONE: "{tone}"

MỤC TIÊU GIỮ CHÂN (RETENTION TIMELINE):
- 0-3 giây: tạo hook mạnh, khẳng định chắc, không hỏi yes/no, không mở đầu chậm.
- 3-8 giây: mở một vòng tò mò hoặc nỗi đau quen thuộc để người xem muốn nghe tiếp (open loop).
- 8-18 giây: lật góc nhìn bằng một insight mới, không giảng đạo (reframe).
- 18-30 giây: cụ thể hóa bằng hình ảnh đời thường, cảm xúc thật, câu ngắn (concrete insight).
- 30-40 giây: câu cuối phải loop về ý đầu để người xem có cảm giác muốn xem lại.

QUY TẮC VIẾT GIỌNG ĐỌC:
- full_voice_script dài 70-110 từ, một đoạn duy nhất.
- Viết như người thật đang nói (conversational), không giống văn nghị luận sáo rỗng.
- Mỗi câu nên ngắn, dễ đọc TTS, có nhịp ngắt tự nhiên.
- KHÔNG dùng câu sáo rỗng như: "hãy yêu bản thân", "cuộc sống là hành trình", "mọi thứ rồi sẽ ổn" nếu không có cách diễn đạt mới mẻ.
- KHÔNG dùng quote danh nhân, số liệu, nghiên cứu hoặc tên tác giả nếu không được cung cấp nguồn tin cậy.
- KHÔNG khẳng định quá mức về sức khỏe, tâm lý, tài chính, pháp lý.
- Ưu tiên hình ảnh cụ thể: căn phòng tối, ly cà phê nguội, con đường mưa, tin nhắn chưa trả lời, bàn tay run, ánh đèn khuya.
- Cần có ít nhất 1 câu tạo cảm giác "đúng là mình".
- Cần có ít nhất 1 câu lật góc nhìn.
- Cần có ít nhất 1 câu đáng để người xem bình luận hoặc lưu lại.

HOOK:
- Tạo hook 8-12 từ.
- Chọn 1 hook_type trong danh sách:
  * hard_truth
  * contrarian
  * identity
  * future_pain
  * micro_story
  * reframe
  * emotional_warning
- Hook phải rõ, mạnh, có khả năng đứng độc lập trên màn hình.

VISUAL NỬA TRÊN:
- scenes_layout_json gồm 5-7 scene.
- Mỗi scene 3-6 giây.
- visual_search_keywords phải là tiếng Anh, cụ thể, có cảm xúc, có chuyển động hoặc góc máy, kết thúc bằng "vertical".
- KHÔNG dùng keyword quá chung chung như "sad man vertical".
- Tốt hơn: "close up of man sitting alone beside rainy window cinematic vertical", "slow motion footsteps on empty street at night vertical".
- overlay_text tiếng Việt tối đa 5 từ, phải khớp với cảm xúc scene.

VISUAL NỬA DƯỚI:
- lifestyle_search_query là tiếng Anh, cụ thể, tìm được video đời sống/nấu ăn/satisfying chạy liền mạch, kết thúc bằng "vertical".
- Chủ đề nửa dưới phải nhẹ nhàng, đều nhịp, không gây rối mắt với giọng đọc.
- Ví dụ tốt: "brewing iced matcha latte aesthetic vertical", "organizing wooden desk satisfying vertical", "cooking creamy chicken curry close up vertical".

YÊU CẦU CHẤT LƯỢNG:
- Có emotional_arc rõ: tension -> realization -> release.
- Có open_loop ở đầu và loop_resolution ở cuối.
- Có retention_beats theo timeline.
- Có script_quality_check để tự đánh giá.
- Có a_b_test_hooks gồm 3 hook thay thế để hệ thống có thể test nhiều phiên bản.

# BỔ SUNG YÊU CẦU METADATA YOUTUBE SHORTS & BOTTOM ASSETS (TRẢ VỀ TẠI ROOT VÀ TRONG seo_tags_metadata):
# - Bạn phải tạo metadata riêng cho YouTube Shorts, không được dùng hook 3 giây làm mô tả mặc định.
# - QUY TẮC TIÊU ĐỀ: Tạo 5 tiêu đề trong youtube_title_options. Mỗi tiêu đề dưới 70 ký tự nếu có thể, tối đa 100 ký tự. Tiêu đề phải rõ nội dung, có cảm xúc, không giật tít sai sự thật. Không dùng title kiểu quá chung chung.
# - QUY TẮC MÔ TẢ YOUTUBE: youtube_scannable_description dài 350-800 ký tự. 2 dòng đầu phải tự nhiên, mô tả đúng nội dung video. Không lặp lại y nguyên hook_text_3s làm mô tả. Có cấu trúc dễ quét bằng mắt: Một đoạn mở đầu cảm xúc, một đoạn giải thích video, một câu CTA nhẹ, và một dòng hashtag liên quan ở cuối.
# - QUY TẮC HASHTAG: youtube_hashtags gồm 5-8 hashtag. Luôn có "Shorts". Không dùng hashtag không liên quan. Không thêm dấu # trong mảng.
# - QUY TẮC API TAGS: youtube_api_tags gồm 8-15 keyword tags. Không thêm dấu #.
# - QUY TẮC BÌNH LUẬN GHIM (pinned_comment): pinned_comment phải là một bình luận triết lý, có ý nghĩa sâu sắc dài 2-3 đoạn văn (tổng cộng 80-150 từ), đúc kết ý nghĩa của video hoặc đặt câu hỏi chiêm nghiệm để kích thích thảo luận tương tác của người xem.
# - QUY TẮC BOTTOM ASSET REQUIREMENTS (bottom_asset_requirements):
#   Chỉ định yêu cầu kỹ thuật và nội dung cho video nền nửa dưới phù hợp với mode LONG_CHILL_MULTI_ACTION theo cấu trúc JSON định sẵn bên dưới.
#
# TRẢ VỀ ĐÚNG JSON HỢP LỆ, KHÔNG MARKDOWN, KHÔNG GIẢI THÍCH:
# {{
#   "video_title_idea": "dưới 60 ký tự",
#   "content_angle": "hard_truth | mindset_shift | healing | self_respect | discipline",
#   "hook_type": "hard_truth | contrarian | identity | reframe",
#   "hook_text_3s": "hook chính 8-12 từ",
#   "a_b_test_hooks": [
#     "hook thay thế 1",
#     "hook thay thế 2",
#     "hook thay thế 3"
#   ],
#   "full_voice_script": "một đoạn voiceover tiếng Việt 70-110 từ",
#   "voice_style": {{
#     "delivery": "conversational",
#     "pace": "slow_emotional",
#     "tts_note": "đọc chậm, rõ"
#   }},
#   "bottom_asset_requirements": {{
#     "asset_type": "licensed_stock_video",
#     "min_duration_seconds": 45,
#     "preferred_duration_seconds": 60,
#     "action_density": "high",
#     "visual_style": "cozy, chill, close-up, satisfying",
#     "must_include_actions": ["preparing ingredients", "cutting or mixing", "cooking or pouring", "plating or final reveal"],
#     "avoid": ["static single-shot video", "only one repeated action", "watermark", "visible brand logo"],
#     "license_requirement": "royalty-free or free-to-use with clear license"
#   }},
#   "youtube_title_options": [
#     "tiêu đề 1",
#     "tiêu đề 2",
#     "tiêu đề 3",
#     "tiêu đề 4",
#     "tiêu đề 5"
#   ],
#   "youtube_scannable_description": "mô tả đầy đủ 350-800 ký tự, có CTA và hashtag cuối",
#   "youtube_hashtags": ["Shorts", "trietlycuocsong", "longbieton", "binhyen", "chualanh", "YuuBin"],
#   "youtube_api_tags": ["lòng biết ơn", "bình yên", "triết lý cuộc sống", "chữa lành", "biết ơn cuộc sống"],
#   "music_mood": "emotional | cozy_chill | cinematic_soft",
#   "music_description": "mô tả nhạc nền ngắn",
#   "lifestyle_search_query": "từ khóa tiếng Anh cho video nửa dưới, kết thúc bằng vertical",
#   "bottom_visual_reason": "vì sao visual nửa dưới phù hợp",
#   "cta_text": "câu CTA ngắn",
#   "pinned_comment": "bình luận ghim sâu sắc",
#   "caption_seo": "caption đăng ngắn gọn",
#   "seo_tags_metadata": {{
#     "title": "title SEO ngắn",
#     "primary_keyword": "từ khóa chính",
#     "secondary_keywords": ["từ khóa phụ 1", "từ khóa phụ 2"],
#     "youtube_title_options": ["tiêu đề 1", "tiêu đề 2", "tiêu đề 3", "tiêu đề 4", "tiêu đề 5"],
#     "youtube_description_first_lines": "2 dòng đầu mô tả",
#     "youtube_scannable_description": "mô tả đầy đủ",
#     "youtube_hashtags": ["Shorts", "trietlycuocsong"],
#     "youtube_api_tags": ["lòng biết ơn", "bình yên"]
#   }},
#   "scenes_layout_json": [
#     {{
#       "scene_id": 1,
#       "duration": 4,
#       "visual_search_keywords": "cinematic close up vertical",
#       "overlay_text": "Đừng vội gục"
#     }}
#   ]
# }}
"""

        def fallback():
            keyword_lifestyle = {
                "cooking": "cooking chicken curry vertical",
                "daily_life": "brewing espresso coffee vertical",
                "satisfying": "satisfying cleaning glass vertical",
            }.get(bottom_visual_type, "cooking chicken curry vertical")
            script = (
                "Có những ngày bạn không cần chiến thắng ai cả, chỉ cần không bỏ rơi chính mình. "
                "Người trưởng thành đôi khi vẫn nấu một bữa ăn đơn giản, dọn lại chiếc bàn bừa bộn, "
                "rồi im lặng thở ra như vừa kéo mình khỏi một vùng tối. Sự mạnh mẽ không luôn ồn ào. "
                "Nó nằm trong khoảnh khắc bạn vẫn làm một việc nhỏ tử tế cho bản thân, dù trong lòng rất mệt. "
                "Và nếu hôm nay bạn chỉ làm được một điều nhỏ, hãy xem đó là cách bạn bắt đầu lại."
            )
            return {
                "video_title_idea": title_idea or "Một điều nhỏ để bắt đầu lại",
                "content_angle": "healing",
                "hook_type": "hard_truth",
                "hook_text_3s": "Có những ngày không gục đã là mạnh mẽ.",
                "a_b_test_hooks": [
                    "Bạn không mệt vì yếu đuối. Bạn mệt vì im lặng.",
                    "Sự mạnh mẽ đôi khi chỉ là không bỏ rơi chính mình.",
                    "Một việc nhỏ tử tế cho bản thân còn hơn vạn lời khuyên."
                ],
                "full_voice_script": script,
                "voice_style": {
                    "delivery": "conversational",
                    "pace": "slow_emotional",
                    "pause_style": "short pauses after emotional lines",
                    "tts_note": "đọc chậm, rõ, không kịch"
                },
                "bottom_asset_requirements": {
                    "asset_type": "licensed_stock_video",
                    "min_duration_seconds": 45,
                    "preferred_duration_seconds": 60,
                    "action_density": "high",
                    "visual_style": "cozy, chill, close-up, satisfying",
                    "must_include_actions": ["preparing ingredients", "cutting or mixing", "cooking or pouring", "plating or final reveal"],
                    "avoid": ["static single-shot video", "only one repeated action", "watermark", "visible brand logo"],
                    "license_requirement": "royalty-free or free-to-use with clear license"
                },
                "youtube_title_options": [
                    "Thấy bình yên từ lòng biết ơn #Shorts",
                    "Biết ơn điều nhỏ, lòng sẽ nhẹ hơn",
                    "Bình yên bắt đầu từ lòng biết ơn",
                    "Khi biết ơn, ta bớt thấy đời nặng nề",
                    "Một cách rất nhẹ để tìm lại bình yên"
                ],
                "youtube_scannable_description": "Bình yên không phải lúc nào cũng đến từ việc có thêm nhiều thứ. Đôi khi, nó bắt đầu khi ta biết ơn những điều vẫn còn ở lại.\n\nVideo ngắn này là một lời nhắc nhẹ: một bữa cơm còn nóng, một người vẫn quan tâm, một ngày mình còn đủ sức bước tiếp… đều là những điều đáng quý. Khi lòng biết ơn đủ lớn, những ngày bình thường cũng có thể trở nên dịu dàng hơn.\n\nBạn biết ơn điều gì nhất hôm nay?\n\n#Shorts #trietlycuocsong #longbieton #binhyen #chualanh #YuuBin",
                "youtube_hashtags": ["Shorts", "trietlycuocsong", "longbieton", "binhyen", "chualanh", "chiemnghiem", "YuuBin"],
                "youtube_api_tags": ["lòng biết ơn", "bình yên", "bình yên nội tâm", "triết lý cuộc sống", "chữa lành", "sống chậm", "biết ơn cuộc sống", "động lực nhẹ nhàng", "suy ngẫm cuộc sống", "video truyền cảm hứng"],
                "retention_strategy": {
                    "open_loop": "lý do vì sao làm việc nhỏ lại giúp đứng dậy",
                    "emotional_arc": "tension -> realization -> release",
                    "pattern_interrupt": "câu hook đánh trúng cảm xúc",
                    "loop_resolution": "kết nối lại câu đầu để lặp lại"
                },
                "voice_timing_plan": [
                    {"start": 0, "end": 3, "purpose": "hook", "line_summary": "Có những ngày không gục đã là mạnh mẽ"},
                    {"start": 3, "end": 8, "purpose": "pain_recognition", "line_summary": "Người trưởng thành im lặng nấu ăn dọn dẹp"},
                    {"start": 8, "end": 18, "purpose": "reframe", "line_summary": "Sự mạnh mẽ nằm ở việc tử tế với chính mình"},
                    {"start": 18, "end": 30, "purpose": "concrete_insight", "line_summary": "Làm một việc nhỏ hôm nay để bắt đầu lại"},
                    {"start": 30, "end": 40, "purpose": "loop_and_cta", "line_summary": "Loop về ý đầu và kêu gọi ghim"}
                ],
                "music_mood": "emotional",
                "music_description": "ambient piano nhẹ, pad ấm, nhịp chậm",
                "lifestyle_search_query": keyword_lifestyle,
                "bottom_visual_reason": "Visual nấu ăn tạo cảm giác chữa lành, bình yên",
                "cta_text": "Tôi đã ghim một câu dành cho ngày mệt nhất.",
                "pinned_comment": "Bình yên không phải là khi cuộc sống không có bão giông, mà là khi ta biết ơn những điều giản dị vẫn còn ở lại. Một bữa cơm ấm, một ngày còn đủ sức bước tiếp... đều là những món quà tuyệt vời.\n\nHôm nay, điều nhỏ bé nào đã giúp bạn mỉm cười và cảm thấy nhẹ lòng?",
                "caption_seo": "Một lời nhắc nhẹ cho những ngày cần bắt đầu lại. #trietlycuocsong #chualanh",
                "seo_tags_metadata": {
                    "title": title_idea or "Một điều nhỏ để bắt đầu lại",
                    "primary_keyword": "lòng biết ơn",
                    "secondary_keywords": ["bình yên nội tâm", "triết lý cuộc sống", "chữa lành"],
                    "youtube_title_options": [
                        "Thấy bình yên từ lòng biết ơn #Shorts",
                        "Biết ơn điều nhỏ, lòng sẽ nhẹ hơn",
                        "Bình yên bắt đầu từ lòng biết ơn",
                        "Khi biết ơn, ta bớt thấy đời nặng nề",
                        "Một cách rất nhẹ để tìm lại bình yên"
                    ],
                    "youtube_description_first_lines": "Bình yên không phải lúc nào cũng đến từ việc có thêm nhiều thứ. Đôi khi, nó bắt đầu khi ta biết ơn những điều vẫn còn ở lại.",
                    "youtube_scannable_description": "Bình yên không phải lúc nào cũng đến từ việc có thêm nhiều thứ. Đôi khi, nó bắt đầu khi ta biết ơn những điều vẫn còn ở lại.\n\nVideo ngắn này là một lời nhắc nhẹ: một bữa cơm còn nóng, một người vẫn quan tâm, một ngày mình còn đủ sức bước tiếp… đều là những điều đáng quý. Khi lòng biết ơn đủ lớn, những ngày bình thường cũng có thể trở nên dịu dàng hơn.\n\nBạn biết ơn điều gì nhất hôm nay?\n\n#Shorts #trietlycuocsong #longbieton #binhyen #chualanh #YuuBin",
                    "youtube_hashtags": ["Shorts", "trietlycuocsong", "longbieton", "binhyen", "chualanh", "chiemnghiem", "YuuBin"],
                    "youtube_api_tags": ["lòng biết ơn", "bình yên", "bình yên nội tâm", "triết lý cuộc sống", "chữa lành", "sống chậm", "biết ơn cuộc sống", "động lực nhẹ nhàng", "suy ngẫm cuộc sống", "video truyền cảm hứng"],
                    "search_intent": "người xem đang tìm một góc nhìn nhẹ nhàng để thấy bình yên và biết trân trọng những điều nhỏ trong cuộc sống",
                    "pinned_comment_strategy": "gợi người xem bình luận một điều nhỏ họ biết ơn hôm nay",
                    "avoid_clickbait_note": "không dùng tiêu đề gây hiểu nhầm hoặc hứa hẹn chữa lành tuyệt đối"
                },
                "truth_safety": {
                    "contains_factual_claims": False,
                    "claims_to_verify": [],
                    "avoid_fake_quotes": True,
                    "sensitive_advice_level": "low"
                },
                "script_quality_check": {
                    "has_strong_hook": True,
                    "has_open_loop": True,
                    "has_specific_imagery": True,
                    "has_reframe": True,
                    "avoids_generic_motivation": True,
                    "final_line_loops_to_hook": True
                },
                "scenes_layout_json": [
                    {"scene_id": idx + 1, "duration": 5, "visual_search_keywords": kw, "overlay_text": text}
                    for idx, (kw, text) in enumerate(zip(
                        [
                            "cinematic close up of lonely man beside rainy window vertical",
                            "walking alone in rainy street vertical",
                            "raindrops sliding down window glass vertical",
                            "person silhouette sitting alone vertical",
                            "rising sun behind mountains cinematic vertical"
                        ],
                        ["Không gục", "Làm điều nhỏ", "Tự kéo mình", "Vẫn tử tế", "Bắt đầu lại"]
                    ))
                ],
            }

        payload = self.generate_json(prompt, fallback)
        return self._polish_split_screen_story(payload, topic, audience, language)
