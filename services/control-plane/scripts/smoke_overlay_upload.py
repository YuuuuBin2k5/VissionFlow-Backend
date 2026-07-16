"""Exercise the production signed-overlay upload path without exposing secrets.

Run from a trusted workstation after deploying Control Plane and configuring
R2 CORS. The script needs a short-lived operator access token and a real image
file; it never reads or prints object-store credentials.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path


def _request(url: str, *, method: str, headers: dict[str, str], body: bytes | None = None) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, response.read()


def main() -> int:
    parser = argparse.ArgumentParser(description="VisionFlow signed overlay upload smoke test")
    parser.add_argument("--api-url", required=True, help="Control Plane API URL ending in /api/v1")
    parser.add_argument("--organization-id", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--access-token", required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()

    try:
        uuid.UUID(args.organization_id); uuid.UUID(args.workflow_run_id)
    except ValueError:
        parser.error("organization-id and workflow-run-id must be UUIDs")
    image = Path(args.image)
    if not image.is_file():
        parser.error("image must be an existing file")
    content_type = mimetypes.guess_type(image.name)[0]
    if content_type not in {"image/png", "image/jpeg", "image/webp"}:
        parser.error("image must be PNG, JPEG, or WebP")
    payload = json.dumps({"organization_id": args.organization_id, "filename": image.name, "content_type": content_type, "byte_size": image.stat().st_size}).encode()
    endpoint = f"{args.api_url.rstrip('/')}/workflows/{args.workflow_run_id}/composition/overlay-uploads"
    try:
        status, response = _request(endpoint, method="POST", headers={"Authorization": f"Bearer {args.access_token}", "Content-Type": "application/json", "Accept": "application/json"}, body=payload)
        if status != 201:
            raise RuntimeError(f"ticket endpoint returned {status}")
        ticket = json.loads(response)
        with image.open("rb") as stream:
            put_status, _ = _request(ticket["upload_url"], method="PUT", headers=ticket["required_headers"], body=stream.read())
        if not 200 <= put_status < 300:
            raise RuntimeError(f"R2 PUT returned {put_status}")
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"[FAIL] Overlay upload smoke test failed: {exc}", file=sys.stderr)
        return 1
    print(f"[OK] Uploaded overlay object: {ticket['object_key']}")
    print("[NEXT] Add this overlay in Composition Studio, Save, then Lock & render to exercise HeadObject verification.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
