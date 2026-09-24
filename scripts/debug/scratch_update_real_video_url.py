import sys
import os

import psycopg2

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

db_url = os.environ["DATABASE_URL"]
conn = psycopg2.connect(db_url)
cur = conn.cursor()

wf_id = 'aa9bf4b5-977d-43f3-a982-12405d39b00f'
# Real rendered video direct HTTPS URL
url = "https://tmpfiles.org/dl/wuwqibQguz8w/export.mp4"

cur.execute("UPDATE media_assets SET object_key = %s WHERE workflow_run_id = %s AND media_kind = 'final_export';", (url, wf_id))
conn.commit()

print(f"✅ MediaAsset object_key updated to REAL RENDERED VIDEO URL: {url}")
conn.close()
