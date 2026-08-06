import sys, os
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

with Session(engine) as session:
    assets = session.scalars(select(MediaAsset).order_by(MediaAsset.created_at.desc()).limit(10)).all()
    print(f"Latest 10 media assets in DB:")
    for a in assets:
        print(f"WF: {a.workflow_run_id} | Kind: {a.media_kind} | Key: {a.object_key}")
