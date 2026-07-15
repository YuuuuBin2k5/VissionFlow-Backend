import json

from worker.config import SCHEDULE_TIMEZONE, POSTING_SCHEDULE_PRESET, MIN_HOURS_BETWEEN_POSTS
from worker.domain.job_metadata import infer_split_screen_metadata_from_text, parse_voice_flag
from worker.domain.scheduling import build_safe_campaign_schedule, get_daily_posting_slots
from worker.infrastructure.database import get_db_connection, log_realtime_progress


async def handle_planning(campaign_id: int):
    """
    Tác vụ PLANNING:
    1. Đọc thông tin chiến dịch.
    2. Gọi LLM lên kế hoạch 30 ngày.
    3. Thêm 30 dòng công việc (Jobs) vào MySQL ở trạng thái QUEUED.
    """
    log_realtime_progress(None, "LLM_PLANNING", "INFO", f"Bắt đầu phân tích chủ đề chiến dịch Campaign #{campaign_id}...")

    conn = get_db_connection()
    campaign = None
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM channels_campaign WHERE id = %s", (campaign_id,))
            campaign = cursor.fetchone()
    finally:
        conn.close()

    if not campaign:
        raise Exception(f"Không tìm thấy chiến dịch Campaign #{campaign_id}")

    raw_topic = campaign["topic"]
    audience = campaign["target_audience"] or "Mọi đối tượng"

    # Bóc tách cờ --voice nếu có và gán giọng đọc cho toàn bộ chiến dịch
    topic, voice_code = parse_voice_flag(raw_topic)
    print(f"[Planning Engine] ✅ Parsed campaign topic: '{topic}' | Selected voice: '{voice_code}'")
    split_screen_campaign_metadata = infer_split_screen_metadata_from_text(f"{topic} {audience}")

    # Gọi LLM sinh 30 ngày
    from worker.services.llm_service import LLMService

    llm = LLMService()
    plan = llm.generate_30_day_plan(topic, audience)

    log_realtime_progress(None, "LLM_PLANNING", "INFO", f"Đã sinh thành công kế hoạch 30 ngày cho chiến dịch. Đang nạp vào database...")

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Cập nhật chiến dịch sang trạng thái RUNNING
            cursor.execute("UPDATE channels_campaign SET status = 'RUNNING' WHERE id = %s", (campaign_id,))

            # Thêm 30 Jobs vào bảng video_pipeline_jobs
            safe_schedule = build_safe_campaign_schedule(len(plan))
            slots_text = ", ".join(get_daily_posting_slots())
            log_realtime_progress(
                None,
                "SCHEDULER",
                "INFO",
                f"Áp dụng lịch đăng {POSTING_SCHEDULE_PRESET} ({slots_text}), timezone {SCHEDULE_TIMEZONE}, giãn cách tối thiểu {MIN_HOURS_BETWEEN_POSTS} giờ."
            )
            for idx, day_plan in enumerate(plan):
                day_num = day_plan.get("day_number", idx + 1)
                title = day_plan.get("video_title_idea", f"Ý tưởng ngày {day_num}")

                # Lập lịch đăng bài: tối đa 2 video/ngày, mặc định 11:30 và 19:30.
                scheduled_time = safe_schedule[idx]

                # Ghi nhận các cấu hình được LLM sinh ra từ bước Planning vào scenes_layout_json làm metadata
                metadata = {
                    "music_mood": day_plan.get("music_mood", "educational"),
                    "content_category": "split_screen_philosophy" if split_screen_campaign_metadata else day_plan.get("content_category", ""),
                    "primary_goal": day_plan.get("primary_goal", "VIEWS"),
                    "concept_description": day_plan.get("concept_description", ""),
                    "voice_code": voice_code,  # Lưu mã giọng đọc vào metadata
                    **split_screen_campaign_metadata,
                }
                if split_screen_campaign_metadata:
                    metadata["is_long_philosophy"] = True
                    metadata["original_philosophy"] = topic

                sql = """
                INSERT INTO video_pipeline_jobs (campaign_id, day_number, scheduled_post_time, video_title_idea, scenes_layout_json, pipeline_state)
                VALUES (%s, %s, %s, %s, %s, 'QUEUED')
                """
                cursor.execute(sql, (campaign_id, day_num, scheduled_time, title, json.dumps(metadata, ensure_ascii=False)))

        log_realtime_progress(None, "LLM_PLANNING", "SUCCESS", f"Hoàn thành khởi tạo chuỗi 30 video cho Campaign #{campaign_id}! 🚀")
    finally:
        conn.close()
