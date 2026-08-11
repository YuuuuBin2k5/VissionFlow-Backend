import psycopg2

db_url = 'postgresql://neondb_owner:npg_Di3nJLmsh5cB@ep-green-salad-aoq7advi-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require'
conn = psycopg2.connect(db_url)
cur = conn.cursor()
wf_id = 'e170123b-26c7-4f32-b541-9992d0e48182'
cur.execute("SELECT id, object_key, media_kind FROM media_assets WHERE workflow_run_id = %s;", (wf_id,))
print(cur.fetchall())
conn.close()
