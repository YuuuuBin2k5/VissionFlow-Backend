import sys
import os

import psycopg2

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

db_url = os.environ["DATABASE_URL"]
conn = psycopg2.connect(db_url)
cur = conn.cursor()

# Set workflows to APPROVAL_PENDING so user can review them on Web UI
cur.execute("UPDATE workflow_runs SET state = 'APPROVAL_PENDING' WHERE id IN ('0b26b772-43a7-4e94-bdb3-f5414eaa2fba', 'e170123b-26c7-4f32-b541-9992d0e48182');")
conn.commit()

print("✅ Workflows updated to APPROVAL_PENDING for User Review on Web UI!")
conn.close()
