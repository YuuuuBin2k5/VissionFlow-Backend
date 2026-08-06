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
from app.infrastructure.models import Organization, VideoProject, WorkflowRun, MediaAsset

engine = create_engine(os.environ["DATABASE_URL"])
with Session(engine) as session:
    org = session.scalars(select(Organization)).first()
    print("Default Org ID:", org.id if org else "None", "Name:", org.name if org else "None")
