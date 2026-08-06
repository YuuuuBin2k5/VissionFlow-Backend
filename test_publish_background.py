import sys
import os
import uuid
sys.path.insert(0, "services/control-plane")

# Load .env
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
from app.infrastructure.models import WorkflowRun, VideoProject, PublisherConnection, PublicationAttempt
from app.routers.workflows import _process_publication_attempt_in_background

wf_id = uuid.UUID("9897b8e6-2d1d-48da-b9d0-87384cc1f58d")
engine = create_engine(os.environ["DATABASE_URL"])

with Session(engine) as session:
    wf = session.scalar(select(WorkflowRun).where(WorkflowRun.id == wf_id))
    print("Workflow state:", wf.state if wf else "None")
    project = session.scalar(select(VideoProject).where(VideoProject.id == wf.project_id))
    org_id = project.organization_id
    print("Organization ID:", org_id)
    
    conn = session.scalar(
        select(PublisherConnection).where(
            PublisherConnection.organization_id == org_id,
            PublisherConnection.status == "active",
        )
    )
    print("Active publisher connection:", conn.id if conn else "None")

    if conn:
        # Reset attempt so it can run
        attempt = session.scalar(
            select(PublicationAttempt).where(
                PublicationAttempt.workflow_run_id == wf_id,
            ).order_by(PublicationAttempt.attempt_number.desc())
        )
        if attempt:
            attempt.state = "pending"
            session.commit()
            print("Reset publication attempt state to pending:", attempt.id)

        print("Testing _process_publication_attempt_in_background locally...")
        try:
            _process_publication_attempt_in_background(
                workflow_run_id=wf_id,
                organization_id=org_id,
                publisher_connection_id=conn.id,
            )
            print("Publication attempt finished successfully!")
        except Exception as e:
            print("Publication attempt failed with error:", e)
            import traceback
            traceback.print_exc()

with Session(engine) as session:
    wf = session.scalar(select(WorkflowRun).where(WorkflowRun.id == wf_id))
    print("\nFinal Workflow state:", wf.state)
    attempt = session.scalar(
        select(PublicationAttempt)
        .where(PublicationAttempt.workflow_run_id == wf_id)
        .order_by(PublicationAttempt.attempt_number.desc())
    )
    if attempt:
        print("Final Attempt State:", attempt.state)
        print("External Video ID:", attempt.external_video_id)
        print("External URL:", attempt.external_url)
        print("Failure code:", attempt.failure_code)
