import os
import sys
import json
import pymysql
import subprocess
import datetime
from pathlib import Path

# Ensure stdout/stderr use UTF-8 on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
if sys.stderr.encoding != 'utf-8':
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Add workspace root to python path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from worker.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, BASE_DIR

def run_job():
    print("==================================================================")
    print("[*] STARTING REAL JOB FOR LONG_CHILL_MULTI_ACTION (SPLIT-SCREEN)")
    print("==================================================================")

    # 1. Connect to MySQL database
    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )
    
    try:
        cursor = conn.cursor()
        
        # 2. Get/Update or Create Campaign
        campaign_topic = "Thấy bình yên từ lòng biết ơn những điều nhỏ mình từng xem là hiển nhiên"
        target_audience = "Người thích chiêm nghiệm và tìm kiếm sự bình yên"
        
        # Try to find a campaign topic first
        cursor.execute("SELECT id FROM channels_campaign WHERE topic = %s LIMIT 1", (campaign_topic,))
        row = cursor.fetchone()
        
        if row:
            campaign_id = row["id"]
            print(f"[+] Found existing Campaign by topic: ID #{campaign_id}")
        else:
            # Try to grab any campaign to update it (to reuse telegram_chat_id etc.)
            cursor.execute("SELECT id FROM channels_campaign LIMIT 1")
            any_camp = cursor.fetchone()
            if any_camp:
                campaign_id = any_camp["id"]
                print(f"[+] Updating existing Campaign ID #{campaign_id} with topic: '{campaign_topic}'")
                cursor.execute(
                    "UPDATE channels_campaign SET topic = %s, target_audience = %s WHERE id = %s",
                    (campaign_topic, target_audience, campaign_id)
                )
            else:
                # If no campaign exists at all, try to insert one
                print("[+] Creating a completely new Campaign...")
                sql_camp = """
                INSERT INTO channels_campaign (topic, target_audience, status, telegram_chat_id)
                VALUES (%s, %s, %s, %s)
                """
                cursor.execute(sql_camp, (campaign_topic, target_audience, "ACTIVE", "123456789"))
                campaign_id = conn.insert_id()
                print(f"[+] Created new Campaign: ID #{campaign_id}")

        # 3. Create Video Pipeline Job
        metadata = {
            "render_mode": "split_screen_short",
            "content_format": "split_screen_life_philosophy",
            "format_preset": "cooking_philosophy",
            "top_visual_type": "cooking",
            "top_asset_strategy": "local_first_long_process",
            "top_min_duration_seconds": 60,
            "bottom_visual_type": "daily_life",
            "bottom_asset_strategy": "local_first_motion_background",
            "bottom_content_type": "philosophy_voiceover",
            "subtitle_strategy": "tts_timestamp_with_estimated_fallback",
            "tone": "healing",
            "platform_targets": ["tiktok", "youtube"],
            "split_mode": "LONG_CHILL_MULTI_ACTION"
        }
        
        sql_job = """
        INSERT INTO video_pipeline_jobs (campaign_id, day_number, scheduled_post_time, video_title_idea, scenes_layout_json, pipeline_state)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        now = datetime.datetime.now()
        cursor.execute(sql_job, (
            campaign_id,
            1,
            now,
            campaign_topic,
            json.dumps(metadata, ensure_ascii=False),
            "QUEUED"
        ))
        job_id = conn.insert_id()
        print(f"[+] Created new Video Pipeline Job: ID #{job_id}")
        
    finally:
        conn.close()

    # 4. Execute main.py RENDER for this Job
    print("\n==================================================================")
    print(f"[*] EXECUTING PIPELINE RENDER FOR JOB #{job_id}...")
    print("==================================================================")
    
    # Try to find python.exe inside AgentTiktok/venv/Scripts/python.exe
    python_path = str(Path(BASE_DIR) / "AgentTiktok" / "venv" / "Scripts" / "python.exe")
    if not os.path.exists(python_path):
        python_path = str(Path(BASE_DIR) / "venv" / "Scripts" / "python.exe")
    if not os.path.exists(python_path):
        python_path = sys.executable  # Fallback
        
    main_py_path = str(Path(BASE_DIR) / "worker" / "main.py")
    
    cmd = [python_path, main_py_path, "--job-id", str(job_id), "--type", "RENDER"]
    
    # Run and stream logs
    process = subprocess.Popen(
        cmd,
        cwd=str(BASE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="ignore"
    )
    
    while True:
        line = process.stdout.readline()
        if not line and process.poll() is not None:
            break
        if line:
            print(line.strip())
            
    rc = process.poll()
    print("\n==================================================================")
    if rc == 0:
        print(f"[+] Render run completed successfully! exit code: {rc} ✅")
    else:
        print(f"[-] Render run failed! exit code: {rc} ❌")
        sys.exit(rc)
    print("==================================================================")

    # 5. Fetch updated job state and metadata from database
    print("\n[+] Fetching final job state from database...")
    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )
    
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM video_pipeline_jobs WHERE id = %s", (job_id,))
        job = cursor.fetchone()
        
        if not job:
            print(f"[-] Error: Job #{job_id} not found in database.")
            sys.exit(1)
            
        print(f"Final State in DB: {job['pipeline_state']}")
        print(f"Final Video Output Path: {job['video_output_path']}")
        
        seo_meta = {}
        if job['seo_tags_metadata']:
            try:
                seo_meta = json.loads(job['seo_tags_metadata']) if isinstance(job['seo_tags_metadata'], str) else job['seo_tags_metadata']
            except Exception as e:
                print(f"[-] Error parsing seo_tags_metadata: {e}")
                
        bottom_meta = seo_meta.get("bottom_asset_metadata") or {}
        
        # In log cuối cùng theo yêu cầu:
        print("\n==================================================================")
        print("FINAL VERIFICATION LOG REPORT:")
        print("==================================================================")
        print(f"bottom_video_path:          {bottom_meta.get('path') or job.get('bottom_video_path') or 'N/A'}")
        print(f"duration:                   {bottom_meta.get('duration') or 'N/A'}s")
        print(f"width:                      {bottom_meta.get('width') or 'N/A'}")
        print(f"height:                     {bottom_meta.get('height') or 'N/A'}")
        print(f"source_url:                 {bottom_meta.get('source_url') or 'N/A'}")
        print(f"license:                    {bottom_meta.get('license') or 'N/A'}")
        print(f"asset_score:                {bottom_meta.get('asset_score') or 0}")
        print(f"quality_warning:            {seo_meta.get('quality_warning') or 'None'}")
        
        yt_titles = seo_meta.get("youtube_title_options") or []
        yt_title = yt_titles[0] if yt_titles else "N/A"
        print(f"youtube title:              {yt_title}")
        
        yt_description = seo_meta.get("youtube_scannable_description") or ""
        print(f"youtube description length: {len(yt_description)}")
        print("==================================================================")
        
    finally:
        conn.close()

if __name__ == "__main__":
    run_job()
