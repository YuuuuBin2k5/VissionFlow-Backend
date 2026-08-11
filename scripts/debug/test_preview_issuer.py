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

from app.infrastructure.overlay_uploads import PrivateObjectPreviewIssuer, OverlayUploadIssuer

print("Endpoint:", os.getenv("VISIONFLOW_OBJECT_STORE_ENDPOINT"))
print("Bucket:", os.getenv("VISIONFLOW_OBJECT_STORE_BUCKET"))
print("Access Key ID:", os.getenv("VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID"))

wf_id = uuid.UUID("9897b8e6-2d1d-48da-b9d0-87384cc1f58d")
key = "visionflow/9897b8e6-2d1d-48da-b9d0-87384cc1f58d/exports/final.mp4"

try:
    issuer = PrivateObjectPreviewIssuer.from_env()
    preview = issuer.issue_final_export(workflow_run_id=wf_id, object_key=key)
    print("SUCCESS! Presigned URL generated:")
    print(preview.download_url[:120])
except Exception as e:
    print("FAILED with error:", e)
    import traceback
    traceback.print_exc()
