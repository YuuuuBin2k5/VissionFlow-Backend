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

try:
    issuer = PrivateObjectPreviewIssuer.from_env()
    key = "visionflow/9897b8e6-2d1d-48da-b9d0-87384cc1f58d/exports/final.mp4"
    meta = issuer._client.head_object(Bucket=issuer._bucket, Key=key)
    print("SUCCESS! R2 Head Object Size:", meta.get("ContentLength"), "bytes")
except Exception as e:
    print("FAIL Head Object:", e)
