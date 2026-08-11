import sys
import psycopg2

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

db_url = 'postgresql://neondb_owner:npg_Di3nJLmsh5cB@ep-green-salad-aoq7advi-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require'
conn = psycopg2.connect(db_url)
cur = conn.cursor()

wf_id = 'aa9bf4b5-977d-43f3-a982-12405d39b00f'
# Real rendered video direct HTTPS URL
url = "https://tmpfiles.org/dl/wuwqibQguz8w/export.mp4"

cur.execute("UPDATE media_assets SET object_key = %s WHERE workflow_run_id = %s AND media_kind = 'final_export';", (url, wf_id))
conn.commit()

print(f"✅ MediaAsset object_key updated to REAL RENDERED VIDEO URL: {url}")
conn.close()
