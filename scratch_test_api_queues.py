import os
import sys
import requests
import json

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

base = "https://visionflow-control-plane-free.onrender.com"
token_resp = requests.post(
    f"{base}/api/v1/auth/token",
    data={
        "grant_type": "client_credentials",
        "client_id": "worker-service",
        "client_secret": "worker-secret",
        "audience": "https://visionflow.controlplane.local",
    },
    timeout=15,
)
token_resp.raise_for_status()
token = token_resp.json()["access_token"]
print(f"✅ Auth token obtained successfully!")

headers = {"Authorization": f"Bearer {token}"}
org_id = "7b91598c-6c3e-4e5d-8247-d3efa203984a"
v1 = f"{base}/api/v1"

print("\n=== 1. REVIEW QUEUE (/review-queue) ===")
r1 = requests.get(f"{v1}/organizations/{org_id}/review-queue", headers=headers)
print(f"Status: {r1.status_code}")
print(json.dumps(r1.json(), indent=2, ensure_ascii=False))

print("\n=== 2. PUBLICATION QUEUE (/publication-queue) ===")
r2 = requests.get(f"{v1}/organizations/{org_id}/publication-queue", headers=headers)
print(f"Status: {r2.status_code}")
print(json.dumps(r2.json(), indent=2, ensure_ascii=False))

print("\n=== 3. PUBLICATION HISTORY (/publication-history) ===")
r3 = requests.get(f"{v1}/organizations/{org_id}/publication-history", headers=headers)
print(f"Status: {r3.status_code}")
print(json.dumps(r3.json(), indent=2, ensure_ascii=False))
