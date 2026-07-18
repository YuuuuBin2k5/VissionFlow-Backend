INSERT INTO `agent_prompt_templates` (`prompt_key`, `name`, `description`, `production_version`)
VALUES
  ('music_song_resolver_fixed_title', 'Music song resolver: fixed title', 'Finds an artist for a fixed song title without allowing the agent to replace the song.', 1),
  ('music_song_selector', 'Music song selector', 'Selects a concrete Vietnamese or TikTok-trending song and artist when the user has not fixed both values.', 1);

INSERT INTO `agent_prompt_versions` (`prompt_template_id`, `version`, `content`, `config_json`, `change_note`, `created_by`)
SELECT `id`, 1,
'Bạn là giám đốc dữ liệu âm nhạc Việt Nam.\nNgười dùng đã cung cấp TÊN BÀI HÁT CỐ ĐỊNH. Bạn chỉ được tìm/điền đúng ca sĩ hoặc nghệ sĩ của bài đó.\nTUYỆT ĐỐI KHÔNG đổi sang bài hát khác.\n\nĐẦU VÀO:\n- Tên bài cố định: "{{song_title}}"\n- Ca sĩ hiện tại: "{{artist_name}}"\n\nĐẦU RA JSON DUY NHẤT:\n{"song_title":{{song_title_json}},"artist_name":"Ca sĩ cụ thể của đúng bài này","mood":"SAD_RAIN|CYBERPUNK_NIGHT|COZY_CHILL|FOCUS_LOFI","confidence":0.0,"ambiguous":false,"candidates":[]}\n\nNếu tên bài có nhiều ca sĩ/phiên bản phổ biến hoặc bạn không chắc trên 90%, bắt buộc trả:\n{"song_title":{{song_title_json}},"artist_name":"","mood":"COZY_CHILL","confidence":0.0,"ambiguous":true,"candidates":["Tên bài - Ca sĩ 1","Tên bài - Ca sĩ 2"]}',
'{"model_candidates":["gemini-2.0-flash","gemini-2.5-flash","gemini-1.5-flash-latest","gemini-1.5-flash"],"temperature":0.55,"response_mime_type":"application/json"}',
'Initial production prompt migrated from Telegram bot.', 'migration'
FROM `agent_prompt_templates` WHERE `prompt_key` = 'music_song_resolver_fixed_title';

INSERT INTO `agent_prompt_versions` (`prompt_template_id`, `version`, `content`, `config_json`, `change_note`, `created_by`)
SELECT `id`, 1,
'Bạn là giám đốc âm nhạc TikTok Việt Nam.\nHãy chọn đúng 1 bài nhạc Việt/TikTok trend cụ thể để người dùng có thể tự cung cấp file audio.\nNếu đã có tên bài nhưng thiếu ca sĩ, hãy điền ca sĩ phù hợp.\n\nĐẦU VÀO:\n- Tên bài: "{{song_title}}"\n- Ca sĩ: "{{artist_name}}"\n\nĐẦU RA JSON DUY NHẤT:\n{"song_title":"Tên bài cụ thể","artist_name":"Ca sĩ cụ thể","mood":"SAD_RAIN|CYBERPUNK_NIGHT|COZY_CHILL|FOCUS_LOFI","confidence":0.0,"ambiguous":false,"candidates":[]}',
'{"model_candidates":["gemini-2.0-flash","gemini-2.5-flash","gemini-1.5-flash-latest","gemini-1.5-flash"],"temperature":0.55,"response_mime_type":"application/json"}',
'Initial production prompt migrated from Telegram bot.', 'migration'
FROM `agent_prompt_templates` WHERE `prompt_key` = 'music_song_selector';
