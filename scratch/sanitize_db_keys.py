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
    assets = session.scalars(select(MediaAsset).where(MediaAsset.object_key.like("%X-Amz-%"))).all()
    print("Found assets with presigned URL as object_key:", len(assets))
    for a in assets:
        old = a.object_key
        clean = old.split("?")[0]
        if "visionflow/" in clean:
            a.object_key = "visionflow/" + clean.split("visionflow/", 1)[1]
            print(f"Updated MediaAsset {a.id}: {a.object_key}")
    session.commit()
