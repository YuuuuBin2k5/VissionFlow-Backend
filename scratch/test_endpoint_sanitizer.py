import sys, os
from urllib.parse import urlparse

endpoints_to_test = [
    "https://ec302240fdb8cad9ae6c9b685f14eeec.r2.cloudflarestorage.com/vision-flow",
    "https://ec302240fdb8cad9ae6c9b685f14eeec.r2.cloudflarestorage.com/vision-flow/",
    "https://ec302240fdb8cad9ae6c9b685f14eeec.r2.cloudflarestorage.com",
    "https://ec302240fdb8cad9ae6c9b685f14eeec.r2.cloudflarestorage.com/",
]

bucket = "vision-flow"

def sanitize_s3_endpoint(endpoint: str, bucket: str) -> str:
    ep = endpoint.rstrip("/")
    parsed = urlparse(ep)
    # R2/S3 endpoint must be root scheme + netloc (host) without bucket path
    return f"{parsed.scheme}://{parsed.netloc}"

for test_ep in endpoints_to_test:
    clean = sanitize_s3_endpoint(test_ep, bucket)
    print(f"Original: {test_ep:<75} -> Clean: {clean}")
