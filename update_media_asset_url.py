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

from app.infrastructure.overlay_uploads import PrivateObjectPreviewIssuer
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.infrastructure.models import MediaAsset

wf_id = uuid.UUID("9897b8e6-2d1d-48da-b9d0-87384cc1f58d")
key = "visionflow/9897b8e6-2d1d-48da-b9d0-87384cc1f58d/exports/final.mp4"

issuer = PrivateObjectPreviewIssuer.from_env()
ticket = issuer.issue_final_export(workflow_run_id=wf_id, object_key=key)
print("Presigned URL:", ticket.download_url)

engine = create_engine(os.environ["DATABASE_URL"])
with Session(engine) as session:
    asset = session.scalar(select(MediaAsset).where(MediaAsset.workflow_run_id == wf_id, MediaAsset.media_kind == "final_export"))
    if asset:
        asset.object_key = ticket.download_url
        session.commit()
        print("Updated MediaAsset object_key in DB to presigned URL!")
