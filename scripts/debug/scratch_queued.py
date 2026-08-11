import psycopg2

db_url = 'postgresql://neondb_owner:npg_Di3nJLmsh5cB@ep-green-salad-aoq7advi-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require'
conn = psycopg2.connect(db_url)
cur = conn.cursor()
cur.execute("SELECT id, project_id, state FROM workflow_runs WHERE state = 'QUEUED';")
rows = cur.fetchall()
print("--- QUEUED WORKFLOWS ---")
for r in rows:
    print(r)
conn.close()
