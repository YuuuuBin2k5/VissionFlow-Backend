import sys
import psycopg2

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

db_url = 'postgresql://neondb_owner:npg_Di3nJLmsh5cB@ep-green-salad-aoq7advi-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require'
conn = psycopg2.connect(db_url)
cur = conn.cursor()

# Set workflow state to APPROVAL_PENDING for User Review on Web UI
cur.execute("UPDATE workflow_runs SET state = 'APPROVAL_PENDING' WHERE id = 'aa9bf4b5-977d-43f3-a982-12405d39b00f';")
conn.commit()

print("✅ Workflow aa9bf4b5-977d-43f3-a982-12405d39b00f updated to APPROVAL_PENDING for User Review on Web UI!")
conn.close()
