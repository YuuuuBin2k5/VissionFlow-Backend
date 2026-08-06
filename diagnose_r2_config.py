"""
Check what endpoint + bucket production is using vs. what actually works.
Run this on production to compare.
"""
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

print("=== Object Store Configuration ===")
for key in ["VISIONFLOW_OBJECT_STORE_ENDPOINT", "VISIONFLOW_OBJECT_STORE_BUCKET",
            "VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID", "VISIONFLOW_OBJECT_STORE_REGION"]:
    val = os.environ.get(key, "NOT SET")
    if "KEY" in key:
        val = val[:8] + "..." if val != "NOT SET" else "NOT SET"
    print(f"  {key}: {val}")

# Test if file exists using these credentials
from app.infrastructure.overlay_uploads import PrivateObjectPreviewIssuer
import uuid

try:
    issuer = PrivateObjectPreviewIssuer.from_env()
    ticket = issuer.issue_final_export(
        workflow_run_id=uuid.UUID("9897b8e6-2d1d-48da-b9d0-87384cc1f58d"),
        object_key="visionflow/9897b8e6-2d1d-48da-b9d0-87384cc1f58d/exports/final.mp4"
    )
    print("\n✅ File EXISTS in R2 with these credentials")
    print("   URL:", ticket.download_url[:80])
except Exception as e:
    print(f"\n❌ FAILED: {e}")
