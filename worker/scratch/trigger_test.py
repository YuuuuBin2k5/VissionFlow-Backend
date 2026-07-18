import os
import sys
import json
import pymysql
import subprocess
import datetime
from pathlib import Path

# Thêm thư mục gốc vào path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from worker.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, BASE_DIR

def trigger_e2e_test():
    print("==================================================================")
    print("[*] BAT DAU KICH HOAT RUN E2E TEST")
    print("==================================================================")

    # 1. Kết nối database
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
        
        # 2. Tìm hoặc tạo Campaign thử nghiệm
        cursor.execute("SELECT id FROM channels_campaign LIMIT 1")
        row = cursor.fetchone()
        if row:
            campaign_id = row["id"]
            print(f"[+] Su dung Campaign co san: ID #{campaign_id}")
        else:
            sql_camp = """
            INSERT INTO channels_campaign (topic, target_audience, status)
            VALUES (%s, %s, %s)
            """
            cursor.execute(sql_camp, ("Triết lý cuộc sống", "Người trẻ", "ACTIVE"))
            campaign_id = conn.insert_id()
            print(f"[+] Da tao Campaign moi: ID #{campaign_id}")

        # 3. Tạo Video Pipeline Job mới cho E2E
        douyin_url = "https://www.douyin.com/jingxuan/vlog?modal_id=7642655249337011456"
        metadata = {
            "render_mode": "translate_dub",
            "dub_source_url": douyin_url,
            "voice_gender": "female",
            "aspect_ratio": "original",
            "burn_subtitles": True,
            "mute_original_audio": False
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
            "[DUB] E2E Douyin Video Test",
            json.dumps(metadata, ensure_ascii=False),
            "QUEUED"
        ))
        job_id = conn.insert_id()
        print(f"[+] Da tao Video Pipeline Job moi thanh cong: ID #{job_id}")
        
    finally:
        conn.close()

    # 4. Thực thi main.py RENDER cho Job này
    print("\n==================================================================")
    print(f"[*] KICH HOAT LENTH CHAY PIPELINE RENDER CHO JOB #{job_id}...")
    print("==================================================================")
    
    python_path = str(Path(BASE_DIR) / "venv" / "Scripts" / "python.exe")
    if not os.path.exists(python_path):
        python_path = sys.executable  # Fallback
        
    main_py_path = str(Path(BASE_DIR) / "worker" / "main.py")
    
    cmd = [python_path, main_py_path, "--job-id", str(job_id), "--type", "RENDER"]
    
    # Chạy và stream stdout/stderr trực tiếp
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
    
    # Đọc và in ra log từng dòng thời gian thực
    while True:
        line = process.stdout.readline()
        if not line and process.poll() is not None:
            break
        if line:
            print(line.strip())
            
    rc = process.poll()
    print("\n==================================================================")
    if rc == 0:
        print(f"[+] E2E TEST THANH CONG TOT DEP! Job ID #{job_id} da hoan thanh. ✅")
    else:
        print(f"[-] E2E TEST THAT BAI! exit code: {rc} ❌")
    print("==================================================================")

if __name__ == "__main__":
    trigger_e2e_test()
