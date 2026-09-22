import os

import psycopg2

db_url = os.environ["DATABASE_URL"]
conn = psycopg2.connect(db_url)
cur = conn.cursor()
cur.execute("SELECT id, project_id, state FROM workflow_runs WHERE state = 'QUEUED';")
rows = cur.fetchall()
print("--- QUEUED WORKFLOWS ---")
for r in rows:
    print(r)
conn.close()
