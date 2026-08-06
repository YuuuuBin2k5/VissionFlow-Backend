"""
File final.mp4 for workflow 449367dc is stored at:
  vision-flow/visionflow/449367dc-c6ba-4d40-9314-79ea813c74a4/exports/final.mp4

But backend looks at:
  visionflow/449367dc-c6ba-4d40-9314-79ea813c74a4/exports/final.mp4

=> The files uploaded by the WORKER use a different bucket layout:
   The WORKER endpoint_url includes the bucket name in the path: 
   https://.../vision-flow  →  boto3 path mode = /vision-flow/<key> = vision-flow/<key>

=> All the "MISS" workflows were uploaded BEFORE the fix.
=> The 10 "OK" workflows are those uploaded by the OLD code using correct separate bucket config.

Strategy: For _normalize_key, also try "vision-flow/visionflow/<wf_id>/..." as fallback.
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

from app.infrastructure.overlay_uploads import PrivateObjectPreviewIssuer

issuer = PrivateObjectPreviewIssuer.from_env()
WF_ID = "449367dc-c6ba-4d40-9314-79ea813c74a4"

# Verify the actual key
actual_key = f"vision-flow/visionflow/{WF_ID}/exports/final.mp4"
try:
    meta = issuer._client.head_object(Bucket=issuer._bucket, Key=actual_key)
    print(f"CONFIRMED: {actual_key} exists, size={meta['ContentLength']} bytes")
except Exception as e:
    print(f"ERROR: {e}")
