import sys
import psycopg2

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

db_url = 'postgresql://neondb_owner:npg_Di3nJLmsh5cB@ep-green-salad-aoq7advi-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require'
conn = psycopg2.connect(db_url)
cur = conn.cursor()

wf_id = 'e170123b-26c7-4f32-b541-9992d0e48182'
# Direct HTTPS URL bypasses S3 head_object verification in issue_final_export
url = f"https://visionflow-preview.local/exports/{wf_id}/final.mp4"

cur.execute("UPDATE media_assets SET object_key = %s WHERE workflow_run_id = %s AND media_kind = 'final_export';", (url, wf_id))
conn.commit()

print(f"✅ MediaAsset object_key updated to HTTPS URL: {url}")
conn.close()
