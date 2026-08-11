import sys
import os
import uuid
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

import boto3

client = boto3.client(
    "s3",
    endpoint_url=os.environ["VISIONFLOW_OBJECT_STORE_ENDPOINT"],
    region_name=os.environ.get("VISIONFLOW_OBJECT_STORE_REGION", "auto"),
    aws_access_key_id=os.environ["VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY"],
)
bucket = os.environ["VISIONFLOW_OBJECT_STORE_BUCKET"]
wf_id = "9897b8e6-2d1d-48da-b9d0-87384cc1f58d"

# List all objects under this workflow prefix
print(f"=== Listing all objects in s3://{bucket}/visionflow/{wf_id}/ ===")
paginator = client.get_paginator("list_objects_v2")
found_any = False
for page in paginator.paginate(Bucket=bucket, Prefix=f"visionflow/{wf_id}/"):
    for obj in page.get("Contents", []):
        found_any = True
        print(f"  Key: {obj['Key']}, Size: {obj['Size']} bytes, LastModified: {obj['LastModified']}")

if not found_any:
    print(f"  (No objects found under prefix visionflow/{wf_id}/)")

# Also verify specific final.mp4
print("\n=== Testing HeadObject for final.mp4 ===")
try:
    resp = client.head_object(Bucket=bucket, Key=f"visionflow/{wf_id}/exports/final.mp4")
    print("EXISTS:", resp["ContentType"], resp["ContentLength"], "bytes")
except Exception as e:
    print("NOT FOUND:", e)
