import os

import psycopg2

db_url = os.environ["DATABASE_URL"]
conn = psycopg2.connect(db_url)
cur = conn.cursor()
cur.execute("SELECT id, email FROM auth_users;")
print(cur.fetchall())
conn.close()
