import os

import psycopg2

db_url = os.environ["DATABASE_URL"]
conn = psycopg2.connect(db_url)
cur = conn.cursor()
wf_id = 'e170123b-26c7-4f32-b541-9992d0e48182'
cur.execute("SELECT id, object_key, media_kind FROM media_assets WHERE workflow_run_id = %s;", (wf_id,))
print(cur.fetchall())
conn.close()
