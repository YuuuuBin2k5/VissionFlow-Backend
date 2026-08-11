import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

os.environ["ENVIRONMENT"] = "development"
os.environ["DATABASE_URL"] = "postgresql://neondb_owner:npg_Di3nJLmsh5cB@ep-green-salad-aoq7advi-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

sys.path.insert(0, os.path.abspath("services/control-plane"))

from sqlalchemy.orm import Session
from app.infrastructure.database import get_engine
from app.infrastructure.models import CreativeSession, WorkflowRun

engine = get_engine()
with Session(engine) as session:
    wf = session.get(WorkflowRun, "e170123b-26c7-4f32-b541-9992d0e48182")
    if wf:
        session_id = wf.input_payload.get("session_id")
        cs = session.get(CreativeSession, session_id) if session_id else None
        if cs:
            print("CS attrs:", [a for a in dir(cs) if not a.startswith('_') and not callable(getattr(cs, a))])
            print("Creation spec:", cs.creation_spec)
            print("Revision:", cs.revision)
            print("Workflow run id:", cs.workflow_run_id)
