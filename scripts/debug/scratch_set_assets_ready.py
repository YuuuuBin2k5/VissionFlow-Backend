import sys
import os

import psycopg2

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

db_url = os.environ["DATABASE_URL"]
conn = psycopg2.connect(db_url)
cur = conn.cursor()
cur.execute("UPDATE workflow_runs SET state = 'PUBLISHED' WHERE id = 'e170123b-26c7-4f32-b541-9992d0e48182';")
conn.commit()
print("[OK] DB State Updated to PUBLISHED!")
conn.close()
