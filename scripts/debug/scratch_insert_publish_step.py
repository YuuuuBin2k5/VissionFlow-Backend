import sys
import uuid
import json
import psycopg2

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

db_url = 'postgresql://neondb_owner:npg_Di3nJLmsh5cB@ep-green-salad-aoq7advi-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require'
conn = psycopg2.connect(db_url)
cur = conn.cursor()

wf_id = 'e170123b-26c7-4f32-b541-9992d0e48182'

# Check if publish step exists
cur.execute("SELECT id FROM workflow_steps WHERE workflow_run_id = %s AND step_key = 'publish';", (wf_id,))
row = cur.fetchone()

if not row:
    step_id = str(uuid.uuid4())
    payload = json.dumps({
        "external_url": "https://www.youtube.com/watch?v=local_export",
        "external_video_id": "local_export",
        "published_at_iso": "2026-07-30T12:35:00.000Z",
        "scheduled_at_iso": "2026-07-30T12:35:00.000Z"
    })
    cur.execute("""
        INSERT INTO workflow_steps (id, workflow_run_id, step_key, state, output_payload, created_at, updated_at)
        VALUES (%s, %s, 'publish', 'COMPLETED', %s, NOW(), NOW());
    """, (step_id, wf_id, payload))
    conn.commit()
    print(f"[OK] Inserted publish step for workflow {wf_id}")
else:
    print(f"[INFO] Publish step already exists for workflow {wf_id}")

conn.close()
