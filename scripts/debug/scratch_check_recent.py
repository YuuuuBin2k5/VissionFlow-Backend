import sys
import os

import psycopg2

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

db_url = os.environ["DATABASE_URL"]
conn = psycopg2.connect(db_url)
cur = conn.cursor()

cur.execute("""
    SELECT wr.id, wr.state, vp.organization_id, vp.title 
    FROM workflow_runs wr 
    LEFT JOIN video_projects vp ON wr.project_id = vp.id 
    ORDER BY wr.id DESC LIMIT 15;
""")
print("=== LATEST 15 WORKFLOW RUNS ===")
for r in cur.fetchall():
    print(f"ID: {r[0]} | State: {r[1]} | Org: {r[2]} | Title: {r[3]}")

conn.close()
