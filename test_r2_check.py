import sys
import os
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

from app.infrastructure.overlay_uploads import PrivateObjectPreviewIssuer
import uuid

wf_id = uuid.UUID("9897b8e6-2d1d-48da-b9d0-87384cc1f58d")
key = "visionflow/9897b8e6-2d1d-48da-b9d0-87384cc1f58d/exports/final.mp4"

try:
    issuer = PrivateObjectPreviewIssuer.from_env()
    ticket = issuer.issue_final_export(workflow_run_id=wf_id, object_key=key)
    print("SUCCESS: Presigned URL generated:", ticket.download_url)
except Exception as e:
    print("ERROR checking R2 object:", type(e), e)
    import traceback
    traceback.print_exc()
