import os
import sys
import uuid
import requests

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

os.environ["ENVIRONMENT"] = "development"
os.environ["DATABASE_URL"] = "postgresql://neondb_owner:npg_Di3nJLmsh5cB@ep-green-salad-aoq7advi-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
os.environ["VISIONFLOW_CONTROL_PLANE_URL"] = "https://visionflow-control-plane-free.onrender.com"
os.environ["VISIONFLOW_ORGANIZATION_ID"] = "7b91598c-6c3e-4e5d-8247-d3efa203984a"
os.environ["VISIONFLOW_WORKER_CLIENT_ID"] = "worker-service"
os.environ["VISIONFLOW_WORKER_CLIENT_SECRET"] = "worker-secret"
os.environ["VISIONFLOW_AUTH_AUDIENCE"] = "visionflow-control-plane"

sys.path.insert(0, os.path.abspath("services/control-plane"))

from sqlalchemy.orm import Session
from app.infrastructure.database import get_engine
from app.infrastructure.models import VideoProject, WorkflowRun

wf_id = "e170123b-26c7-4f32-b541-9992d0e48182"
org_id = "7b91598c-6c3e-4e5d-8247-d3efa203984a"
base_url = "https://visionflow-control-plane-free.onrender.com"

engine = get_engine()
with Session(engine) as session:
    wf = session.get(WorkflowRun, wf_id)
    proj = session.get(VideoProject, wf.project_id) if wf else None
    
    print(f"Target Workflow: {wf_id}")
    print(f"Current State: {wf.state if wf else 'None'}")
    print(f"Project Title: {proj.title if proj else 'None'}")

    if wf and wf.state == "QUEUED":
        print("\n--> Advancing QUEUED -> PLANNING...")
        # Call control plane advance endpoint directly or update DB state
        wf.state = "PLANNING"
        session.commit()
        print("✓ Workflow state updated to PLANNING in Database!")
