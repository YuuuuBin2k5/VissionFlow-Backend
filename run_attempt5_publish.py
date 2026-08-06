"""
Script trigger publish lại workflow 9897b8e6 thông qua API trực tiếp.
"""
import sys, os, uuid, json
import io

# Fix encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Load .env từ control-plane
env_path = os.path.join(os.path.dirname(__file__), "services/control-plane/.env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))

sys.path.insert(0, "services/control-plane")

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from app.infrastructure.models import WorkflowRun, VideoProject, PublicationAttempt, PublisherConnection
from app.domain.workflow import WorkflowState

engine = create_engine(os.environ["DATABASE_URL"])
wf_id = uuid.UUID("9897b8e6-2d1d-48da-b9d0-87384cc1f58d")
conn_id = uuid.UUID("95a928dc-fe24-4c5b-9cb3-2afef3e6fc09")

with Session(engine) as session:
    wf = session.scalar(select(WorkflowRun).where(WorkflowRun.id == wf_id))
    project = session.scalar(select(VideoProject).where(VideoProject.id == wf.project_id))
    connection = session.scalar(select(PublisherConnection).where(PublisherConnection.id == conn_id))
    org_id = project.organization_id
    
    print(f"Workflow state: {wf.state}")
    print(f"Organization ID: {org_id}")
    print(f"Publisher connection status: {connection.status}")
    
    # List existing publication attempts
    attempts = session.scalars(
        select(PublicationAttempt).where(PublicationAttempt.workflow_run_id == wf_id)
        .order_by(PublicationAttempt.attempt_number)
    ).all()
    print(f"\nExisting attempts: {len(attempts)}")
    for a in attempts:
        print(f"  #{a.attempt_number}: state={a.state}, video_id={a.external_video_id}")

# Reset pending attempt #5 và set workflow -> PUBLISHING
print("\n=== Setting workflow to PUBLISHING and checking attempt #5 ===")
with Session(engine) as session:
    wf = session.scalar(select(WorkflowRun).where(WorkflowRun.id == wf_id))
    project = session.scalar(select(VideoProject).where(VideoProject.id == wf.project_id))
    org_id = project.organization_id
    
    # Reset workflow sang PUBLISHING
    wf.state = WorkflowState.PUBLISHING
    
    # Kiểm tra attempt #5 có tồn tại chưa
    att5 = session.scalar(
        select(PublicationAttempt).where(
            PublicationAttempt.workflow_run_id == wf_id,
            PublicationAttempt.attempt_number == 5
        )
    )
    if att5:
        print(f"  Found attempt #5 (state={att5.state}), resetting to 'pending'")
        att5.state = "pending"
        att_id = att5.id
    else:
        att = PublicationAttempt(
            workflow_run_id=wf_id,
            attempt_number=5,
            publisher_connection_id=conn_id,
            requested_by_subject="user:admin",
            state="pending",
        )
        session.add(att)
        session.flush()
        att_id = att.id
        print(f"  Created new attempt #5 (id={att_id})")
    
    session.commit()
    print(f"  Workflow state -> PUBLISHING, attempt state -> pending")
    print(f"  org_id: {org_id}")

# Gọi background function trực tiếp
print("\n=== Starting upload to YouTube (UNLISTED) ===")
from app.routers.workflows import _process_publication_attempt_in_background

_process_publication_attempt_in_background(
    workflow_run_id=wf_id,
    organization_id=org_id,
    publisher_connection_id=conn_id,
    scheduled_at_iso=None,
)

# Kiểm tra kết quả
print("\n=== Checking final state ===")
with Session(engine) as session:
    wf = session.scalar(select(WorkflowRun).where(WorkflowRun.id == wf_id))
    attempts = session.scalars(
        select(PublicationAttempt).where(PublicationAttempt.workflow_run_id == wf_id)
        .order_by(PublicationAttempt.attempt_number)
    ).all()
    print(f"Workflow final state: {wf.state}")
    for a in list(attempts):
        print(f"  #{a.attempt_number}: state={a.state}, video_id={a.external_video_id}, url={a.external_url}")
