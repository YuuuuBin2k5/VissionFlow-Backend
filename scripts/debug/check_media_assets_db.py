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
from app.infrastructure.models import MediaAsset

engine = create_engine(os.environ["DATABASE_URL"])
wf_id = uuid.UUID("9897b8e6-2d1d-48da-b9d0-87384cc1f58d")

with Session(engine) as session:
    assets = session.scalars(
        select(MediaAsset)
        .where(MediaAsset.workflow_run_id == wf_id)
    ).all()
    print(f"Total media assets for {wf_id}: {len(assets)}")
    for a in assets:
        print(f"Asset ID: {a.id} | Kind: {a.media_kind}")
        print(f"  Object Key: {a.object_key}")
