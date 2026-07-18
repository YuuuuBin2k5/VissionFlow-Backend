import os
import sys
from pathlib import Path

# Thêm thư mục gốc vào path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

import pymysql
import json
from worker.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

def query_logs():
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
        
        # Lấy video job mới nhất
        cursor.execute("SELECT * FROM video_pipeline_jobs ORDER BY id DESC LIMIT 1")
        job = cursor.fetchone()
        print("=== LATEST VIDEO PIPELINE JOB ===")
        if job:
            print(f"Job ID: {job['id']}")
            print(f"Title: {job['video_title_idea']}")
            print(f"State: {job['pipeline_state']}")
            print(f"Error: {job['error_log_trace']}")
            print(f"Output path: {job['video_output_path']}")
        else:
            print("No jobs found.")
            return
            
        print("\n=== REAL-TIME PROGRESS LOGS ===")
        cursor.execute("SELECT * FROM process_realtime_logs WHERE job_id = %s ORDER BY id ASC", (job['id'],))
        rows = cursor.fetchall()
        for r in rows:
            print(f"[{r['status_level']}] {r['execution_step']}: {r['log_message']}")
            
        if not rows:
            # Nếu không tìm thấy log theo job_id cụ thể, lấy 20 log mới nhất
            print("\n(No logs found for this job ID, showing latest 20 global logs)")
            cursor.execute("SELECT * FROM process_realtime_logs ORDER BY id DESC LIMIT 20")
            rows = sorted(cursor.fetchall(), key=lambda x: x['id'])
            for r in rows:
                print(f"[{r['status_level']}] [Job #{r['job_id']}] {r['execution_step']}: {r['log_message']}")
                
    finally:
        conn.close()

if __name__ == "__main__":
    query_logs()
