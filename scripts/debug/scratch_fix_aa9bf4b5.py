import sys
import os

import psycopg2

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

db_url = os.environ["DATABASE_URL"]
conn = psycopg2.connect(db_url)
cur = conn.cursor()

# Set workflow state to APPROVAL_PENDING for User Review on Web UI
cur.execute("UPDATE workflow_runs SET state = 'APPROVAL_PENDING' WHERE id = 'aa9bf4b5-977d-43f3-a982-12405d39b00f';")
conn.commit()

print("✅ Workflow aa9bf4b5-977d-43f3-a982-12405d39b00f updated to APPROVAL_PENDING for User Review on Web UI!")
conn.close()
