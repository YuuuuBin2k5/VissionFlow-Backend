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
token = token_resp.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}
org_id = "7b91598c-6c3e-4e5d-8247-d3efa203984a"
wf_id = "e170123b-26c7-4f32-b541-9992d0e48182"

print("\n=== TEST REVIEW ARTIFACT ENDPOINT ===")
url = f"{base}/api/v1/workflows/{wf_id}/review-artifact?organization_id={org_id}"
r = requests.get(url, headers=headers)
print(f"Status Code: {r.status_code}")
print(json.dumps(r.json(), indent=2, ensure_ascii=False))
