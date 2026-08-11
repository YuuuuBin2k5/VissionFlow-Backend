import sys, os, uuid
sys.path.insert(0, "services/control-plane")

env_path = "services/control-plane/.env"
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip("'\"")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.infrastructure.models import WorkflowRun, PublicationAttempt

engine = create_engine(os.environ["DATABASE_URL"])
wf_id = uuid.UUID("9897b8e6-2d1d-48da-b9d0-87384cc1f58d")

with Session(engine) as session:
    wf = session.scalar(select(WorkflowRun).where(WorkflowRun.id == wf_id))
    attempts = session.scalars(select(PublicationAttempt).where(PublicationAttempt.workflow_run_id == wf_id)).all()
    print("Workflow state:", wf.state if wf else "NOT FOUND")
    for a in attempts:
        print(f"Attempt {a.attempt_number}: state={a.state}, conn_id={a.publisher_connection_id}")
