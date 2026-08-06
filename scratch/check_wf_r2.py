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
from app.infrastructure.models import MediaAsset, WorkflowRun
from app.infrastructure.overlay_uploads import PrivateObjectPreviewIssuer

WF_ID = "449367dc-c6ba-4d40-9314-79ea813c74a4"

# 1. Check DB
engine = create_engine(os.environ["DATABASE_URL"])
with Session(engine) as session:
    wf = session.scalar(select(WorkflowRun).where(WorkflowRun.id == WF_ID))
    print("Workflow State:", wf.state if wf else "Not found")
    assets = session.scalars(select(MediaAsset).where(MediaAsset.workflow_run_id == WF_ID)).all()
    for a in assets:
        print(f"Kind: {a.media_kind}, ObjectKey: {a.object_key[:120] if a.object_key else None}")

# 2. List all objects in R2 for this workflow prefix
print("\n--- Searching R2 for this workflow ---")
issuer = PrivateObjectPreviewIssuer.from_env()
prefix = f"visionflow/{WF_ID}/"
response = issuer._client.list_objects_v2(Bucket=issuer._bucket, Prefix=prefix)
contents = response.get("Contents", [])
if contents:
    for obj in contents:
        print(f"  FOUND: {obj['Key']} ({obj['Size']} bytes)")
else:
    print("  No objects found with prefix:", prefix)

# Also search without 'visionflow/' prefix
print("\n--- Searching R2 with workflow id only ---")
response2 = issuer._client.list_objects_v2(Bucket=issuer._bucket, Prefix=WF_ID)
contents2 = response2.get("Contents", [])
if contents2:
    for obj in contents2:
        print(f"  FOUND: {obj['Key']} ({obj['Size']} bytes)")
else:
    print("  No objects found with prefix:", WF_ID)
