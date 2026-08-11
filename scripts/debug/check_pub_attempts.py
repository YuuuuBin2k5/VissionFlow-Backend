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
from app.infrastructure.models import PublicationAttempt, WorkflowRun

wf_id = uuid.UUID("9897b8e6-2d1d-48da-b9d0-87384cc1f58d")
engine = create_engine(os.environ["DATABASE_URL"])

with Session(engine) as session:
    attempts = session.scalars(
        select(PublicationAttempt)
        .where(PublicationAttempt.workflow_run_id == wf_id)
        .order_by(PublicationAttempt.attempt_number.desc())
    ).all()
    print(f"Total publication attempts: {len(attempts)}")
    for att in attempts:
        print(f"\nAttempt #{att.attempt_number} | State: {att.state}")
        print(f"  ID: {att.id}")
        print(f"  Failure code: {att.failure_code}")
        print(f"  External video ID: {getattr(att, 'external_video_id', None)}")
        print(f"  External URL: {getattr(att, 'external_url', None)}")
        print(f"  Created: {getattr(att, 'created_at', None)}")

    wf = session.scalar(select(WorkflowRun).where(WorkflowRun.id == wf_id))
    print(f"\nWorkflow state: {wf.state}")
