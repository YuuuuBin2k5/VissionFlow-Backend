import pymysql
from pymysql.cursors import DictCursor

# Database connection settings (matching worker/.env)
config = {
    'host': 'localhost',
    'port': 3307,
    'user': 'root',
    'password': '091005aE@',
    'database': 'tiktok_agent_automation_db',
    'cursorclass': DictCursor
}

try:
    conn = pymysql.connect(**config)
    cursor = conn.cursor()
    
    # 1. Reset state
    cursor.execute(
        "UPDATE video_pipeline_jobs SET pipeline_state = 'QUEUED' WHERE id = 148"
    )
    conn.commit()
    print("[SUCCESS] Successfully reset Job #148 state to QUEUED in database!")
    
    # 2. Query and print fields
    cursor.execute("SELECT id, pipeline_state, video_title_idea, topic, audio_file_path FROM video_pipeline_jobs WHERE id = 148")
    job = cursor.fetchone()
    print("Job Info:", job)
    
    cursor.close()
    conn.close()
except Exception as e:
    print("Failed to reset Job #148:", str(e))
