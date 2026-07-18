import json
import pymysql
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
    
    # 1. Fetch current scenes_layout_json
    cursor.execute("SELECT scenes_layout_json FROM video_pipeline_jobs WHERE id = 148")
    row = cursor.fetchone()
    
    metadata = {}
    if row and row['scenes_layout_json']:
        try:
            metadata = json.loads(row['scenes_layout_json'])
        except Exception:
            metadata = {}
            
    # Remove cached elements to force re-evaluation
    metadata.pop('selected_viral_segment', None)
    metadata.pop('caption_timeline', None)
    metadata.pop('viral_segment_audio_path', None)
    metadata.pop('caption_mode', None)
    
    metadata['visual_template'] = 'lofi_anime'
    metadata['music_video_template'] = 'lofi_anime'
    metadata['auto_select_viral_segment'] = True
    metadata['requires_user_audio'] = True
    
    # 2. Save back and reset status
    cursor.execute(
        "UPDATE video_pipeline_jobs SET scenes_layout_json = %s, pipeline_state = 'QUEUED' WHERE id = 148",
        (json.dumps(metadata, ensure_ascii=False),)
    )
    conn.commit()
    print("[SUCCESS] Successfully purged cache and queued Job #148 for Lofi Anime 60s render!")
    
    cursor.close()
    conn.close()
except Exception as e:
    print("Failed to configure Job #148:", str(e))
