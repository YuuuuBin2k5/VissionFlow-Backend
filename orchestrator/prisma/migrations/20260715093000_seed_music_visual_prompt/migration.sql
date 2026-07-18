INSERT INTO `agent_prompt_templates` (`prompt_key`, `name`, `description`, `production_version`)
VALUES ('music_visual_suggestions', 'Music visual suggestions', 'Suggests visual and remix settings for a music-based TikTok video.', 1);

INSERT INTO `agent_prompt_versions` (`prompt_template_id`, `version`, `content`, `config_json`, `change_note`, `created_by`)
SELECT `id`, 1,
'Bạn là giám đốc sáng tạo kênh âm nhạc TikTok hàng đầu Việt Nam. Phân tích bài hát và đề xuất thông số kỹ thuật phù hợp nhất.\n\nBÀI HÁT: "{{song_title}}"\nNGHỆ SĨ: "{{artist_name}}"\n\nChỉ trả về JSON hợp lệ: {"mood":"SAD_RAIN|CYBERPUNK_NIGHT|COZY_CHILL|FOCUS_LOFI","remix_style":"trend_bass|deep_house|lofi_chill","bpm":"70-140","caption":"caption tiếng Việt dưới 80 ký tự","visual_keywords":"3 từ khóa tiếng Anh","rationale":"lý do ngắn"}.',
'{"model":"gemini-1.5-flash","temperature":0.3,"response_mime_type":"application/json"}',
'Initial production prompt migrated from Telegram bot.', 'migration'
FROM `agent_prompt_templates` WHERE `prompt_key` = 'music_visual_suggestions';
