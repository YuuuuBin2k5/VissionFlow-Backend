import sys
import os
sys.path.insert(0, "services/control-plane")
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.infrastructure.models import MediaAsset, WorkflowRun

db_url = None
if os.path.exists("services/control-plane/.env"):
    with open("services/control-plane/.env") as f:
        for line in f:
            if line.startswith("DATABASE_URL="):
                db_url = line.strip().split("=", 1)[1].strip("'\"")

if not db_url:
    db_url = os.environ.get("DATABASE_URL")

engine = create_engine(db_url)
with Session(engine) as session:
    wf = session.scalar(select(WorkflowRun).where(WorkflowRun.id == "9897b8e6-2d1d-48da-b9d0-87384cc1f58d"))
    print("Workflow State:", wf.state if wf else "Not found")
    assets = session.scalars(select(MediaAsset).where(MediaAsset.workflow_run_id == "9897b8e6-2d1d-48da-b9d0-87384cc1f58d")).all()
    for a in assets:
        print(f"Kind: {a.media_kind}, ObjectKey: {a.object_key}")
