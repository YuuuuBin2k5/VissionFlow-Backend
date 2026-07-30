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
org_id = '7b91598c-6c3e-4e5d-8247-d3efa203984a'

# Check if MediaAsset exists
cur.execute("SELECT id FROM media_assets WHERE workflow_run_id = %s AND media_kind = 'final_export';", (wf_id,))
row = cur.fetchone()

if not row:
    asset_id = str(uuid.uuid4())
    object_key = f"exports/{wf_id}/final.mp4"
    meta = json.dumps({})
    cur.execute("""
        INSERT INTO media_assets (id, organization_id, workflow_run_id, media_kind, object_key, content_type, byte_size, checksum_sha256, metadata_json, created_at, updated_at)
        VALUES (%s, %s, %s, 'final_export', %s, 'video/mp4', 9394362, 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', %s, NOW(), NOW());
    """, (asset_id, org_id, wf_id, object_key, meta))
    conn.commit()
    print(f"✅ MediaAsset inserted for workflow {wf_id}")
else:
    print(f"ℹ️ MediaAsset already exists for workflow {wf_id}")

conn.close()
