# VisionFlow R2 Overlay Staging Gate

This runbook activates the signed-overlay upload path introduced in Control
Plane and consumed by the VisionFlow worker. It is intentionally limited to
short-lived browser `PUT` uploads of PNG, JPEG, and WebP images. The ticket
endpoint limits declared uploads to 15 MiB; worker-side object verification is
the next hardening gate before treating an uploaded object as render input.

## 1. Provision a private bucket

Create a private bucket named `visionflow-assets`. Create an R2 S3 API token
scoped only to that bucket with Object Read and Object Write. Do not create a
public bucket or place this token in Vercel.

Set these secrets on the **Control Plane** and **intelligence worker** Render
services:

```text
VISIONFLOW_OBJECT_STORE_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
VISIONFLOW_OBJECT_STORE_BUCKET=visionflow-assets
VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID=<r2-access-key-id>
VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY=<r2-secret-access-key>
VISIONFLOW_OBJECT_STORE_REGION=auto
```

## 2. Configure R2 CORS

Set this bucket CORS policy, replacing the origin only when the production
Console domain changes. Do not use `*`.

```json
[
  {
    "AllowedOrigins": ["https://vision-flow-console.vercel.app"],
    "AllowedMethods": ["PUT"],
    "AllowedHeaders": ["Content-Type"],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 300
  }
]
```

## 3. Deploy order

1. Deploy Control Plane commit `c595bdc` or later and confirm `/api/v1/health`.
2. Deploy Console commit `5765084` or later.
3. Deploy the worker commit `367e155` or later (plus the caption commits).
4. Create a short workflow, open Composition Studio, choose **Upload overlay**,
   then Save, Lock and render.

## Acceptance evidence

- Browser network shows a `201` Control Plane ticket request then a direct R2
  `PUT` with `Content-Type` matching the file.
- Saved composition contains a key beginning with
  `visionflow/<workflow-run-id>/uploads/`.
- The worker downloads that key into its isolated workspace and exports an MP4.
- The final artifact is reviewed visually: overlay timing, position, opacity,
  caption readability, and no audio regression.

If R2 responds with a CORS error, verify the exact Vercel origin, `PUT`, and
the `Content-Type` header before changing application code.

## Repeatable smoke test

After signing in as an organization producer/admin, obtain the short-lived
access token from the browser session and run this from a trusted workstation:

```powershell
python services/control-plane/scripts/smoke_overlay_upload.py `
  --api-url https://your-control-plane.onrender.com/api/v1 `
  --organization-id <organization-uuid> `
  --workflow-run-id <workflow-run-uuid> `
  --access-token <short-lived-access-token> `
  --image C:\path\to\overlay.png
```

The script intentionally prints only the uploaded object key, never a token
or storage credential. Use a fresh test workflow because the next Lock action
will validate the object with R2 `HeadObject` before the composition becomes
immutable.
