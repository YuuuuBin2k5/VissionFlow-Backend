import os

import psycopg2

db_url = os.environ["DATABASE_URL"]
conn = psycopg2.connect(db_url)
cur = conn.cursor()
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public';")
print([r[0] for r in cur.fetchall()])
conn.close()
