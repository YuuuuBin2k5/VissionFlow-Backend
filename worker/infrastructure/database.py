import pymysql
from pymysql.cursors import DictCursor

from worker.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME
from worker.services.cockpit_bridge import dispatch_log_to_cockpit


def get_db_connection():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset='utf8mb4',
        cursorclass=DictCursor,
        autocommit=True
    )

def log_realtime_progress(job_id, step, level, message):
    """Ghi nhận tiến trình thời gian thực vào bảng process_realtime_logs"""
    print(f"[{level}] {step}: {message}")

    # Hook Giai đoạn 2: Điều hướng log trực tiếp lên Cockpit Gateway
    try:
        cockpit_level = level
        if level == "ERROR":
            cockpit_level = "CRITICAL"
        dispatch_log_to_cockpit(cockpit_level, f"[{step}] {message}")
    except Exception as log_err:
        print(f"[Cockpit Bridge Logging Error] {log_err}")

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = """
            INSERT INTO process_realtime_logs (job_id, execution_step, status_level, log_message)
            VALUES (%s, %s, %s, %s)
            """
            cursor.execute(sql, (job_id, step, level, message))
        conn.close()
    except Exception as e:
        print(f"[DB Log Error] Failed to write log: {e}")
