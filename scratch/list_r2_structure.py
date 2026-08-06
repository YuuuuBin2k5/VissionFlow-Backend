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

# List all top-level prefixes in the bucket
print("=== Top-level prefixes in bucket ===")
response = issuer._client.list_objects_v2(
    Bucket=issuer._bucket,
    Delimiter="/",
    MaxKeys=50
)
for p in response.get("CommonPrefixes", []):
    print(" ", p["Prefix"])
for obj in response.get("Contents", []):
    print("  FILE:", obj["Key"])

# List all visionflow/ contents
print("\n=== visionflow/ prefix ===")
paginator = issuer._client.get_paginator("list_objects_v2")
count = 0
for page in paginator.paginate(Bucket=issuer._bucket, Prefix="visionflow/", Delimiter="/"):
    for prefix in page.get("CommonPrefixes", []):
        print(" ", prefix["Prefix"])
        count += 1
    if count >= 20:
        print("... (truncated)")
        break
