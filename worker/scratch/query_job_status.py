import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

import pymysql
from worker.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

def query_status():
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
        cursor.execute("SELECT pipeline_state, error_log_trace FROM video_pipeline_jobs WHERE id = 227")
        job = cursor.fetchone()
        print("=== JOB 227 LIVE STATE ===")
        if job:
            print(f"State: {job['pipeline_state']}")
            trace = job['error_log_trace'] or ""
            print(f"Error Log Trace Length: {len(trace)}")
        else:
            print("Job #227 not found.")
            
        print("\n=== LATEST 10 PROCESS LOGS ===")
        cursor.execute("SELECT * FROM process_realtime_logs WHERE job_id = 227 ORDER BY id DESC LIMIT 10")
        rows = reversed(cursor.fetchall())
        for r in rows:
            msg = f"[{r['status_level']}] {r['execution_step']}: {r['log_message']}"
            print(msg.encode('ascii', 'ignore').decode('ascii'))
    finally:
        conn.close()

if __name__ == "__main__":
    query_status()
