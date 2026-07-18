import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

import pymysql
from worker.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

def query_db_error():
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
        cursor.execute("SELECT error_log_trace, pipeline_state, video_output_path FROM video_pipeline_jobs WHERE id = 227")
        job = cursor.fetchone()
        
        out_lines = []
        out_lines.append("=== JOB 227 DATA ===")
        if job:
            out_lines.append(f"State: {job['pipeline_state']}")
            out_lines.append(f"Output path: {job['video_output_path']}")
            trace = job['error_log_trace'] or ""
            out_lines.append("Error log trace:")
            out_lines.append(trace)
        else:
            out_lines.append("Job #227 not found.")
            
        out_lines.append("\n=== REAL-TIME PROCESS LOGS ===")
        cursor.execute("SELECT * FROM process_realtime_logs WHERE job_id = 227 ORDER BY id ASC")
        rows = cursor.fetchall()
        for r in rows:
            msg = f"[{r['status_level']}] {r['execution_step']}: {r['log_message']}"
            out_lines.append(msg)
            
        with open("worker/scratch/db_error_full.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(out_lines))
        print("Written full log to worker/scratch/db_error_full.txt successfully!")
    finally:
        conn.close()

if __name__ == "__main__":
    query_db_error()
