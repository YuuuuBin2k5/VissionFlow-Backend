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

from app.infrastructure.overlay_uploads import PrivateObjectPreviewIssuer

issuer = PrivateObjectPreviewIssuer.from_env()

# Check vision-flow/ prefix (old path)
WF_ID = "449367dc-c6ba-4d40-9314-79ea813c74a4"
print("=== Searching in vision-flow/ (old path) ===")
response = issuer._client.list_objects_v2(
    Bucket=issuer._bucket,
    Prefix=f"vision-flow/{WF_ID}"
)
contents = response.get("Contents", [])
if contents:
    for obj in contents:
        print(f"  FOUND: {obj['Key']} ({obj['Size']} bytes)")
else:
    print(f"  Not found in vision-flow/{WF_ID}")

# Check vision-flow/visionflow/
print("\n=== Searching in vision-flow/visionflow/ (double path) ===")
response2 = issuer._client.list_objects_v2(
    Bucket=issuer._bucket,
    Prefix=f"vision-flow/visionflow/{WF_ID}"
)
contents2 = response2.get("Contents", [])
if contents2:
    for obj in contents2:
        print(f"  FOUND: {obj['Key']} ({obj['Size']} bytes)")
else:
    print(f"  Not found in vision-flow/visionflow/{WF_ID}")

# Now check all workflow IDs in DB vs R2
print("\n=== All approved workflows in DB vs R2 ===")
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.infrastructure.models import MediaAsset, WorkflowRun

engine = create_engine(os.environ["DATABASE_URL"])
with Session(engine) as session:
    assets = session.scalars(
        select(MediaAsset).where(
            MediaAsset.media_kind == "final_export"
        )
    ).all()
    for a in assets:
        wf_id_str = str(a.workflow_run_id)
        # try to head_object
        try:
            issuer._client.head_object(Bucket=issuer._bucket, Key=f"visionflow/{wf_id_str}/exports/final.mp4")
            print(f"  OK   wf={wf_id_str}")
        except Exception:
            print(f"  MISS wf={wf_id_str} (db_key={a.object_key[:60] if a.object_key else None})")
