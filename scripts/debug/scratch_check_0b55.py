import os

import psycopg2
db_url = os.environ["DATABASE_URL"]
conn = psycopg2.connect(db_url)
cur = conn.cursor()
cur.execute("SELECT id, state FROM workflow_runs WHERE id = '0b551143-eaac-407a-9e44-8d0c7fd9c744';")
print(cur.fetchall())
conn.close()
