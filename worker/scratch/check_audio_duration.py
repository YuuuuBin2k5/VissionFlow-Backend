import json
import pymysql
import os
import subprocess
from pymysql.cursors import DictCursor

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
    cursor.execute("SELECT id, audio_file_path, scenes_layout_json FROM video_pipeline_jobs WHERE id = 148")
    job = cursor.fetchone()
    
    print("Job ID:", job['id'])
    print("Audio Path:", job['audio_file_path'])
    
    if job['audio_file_path'] and os.path.exists(job['audio_file_path']):
        # Get duration using ffprobe
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", job['audio_file_path']
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(res.stdout)
        dur = float(data.get("format", {}).get("duration", 0.0))
        print("Audio File Duration:", dur)
    else:
        print("Audio file does not exist or path is empty.")
        
    if job['scenes_layout_json']:
        meta = json.loads(job['scenes_layout_json'])
        print("Selected Viral Segment:", meta.get("selected_viral_segment"))
        print("Viral Segment Audio Path:", meta.get("viral_segment_audio_path"))
        
    cursor.close()
    conn.close()
except Exception as e:
    print("Error:", str(e))
