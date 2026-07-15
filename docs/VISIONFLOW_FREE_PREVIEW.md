# VisionFlow Free Preview

Use this profile for personal development, demo, and early validation. It is
not a production SLA profile.

## Free topology

| Component | Free option | Responsibility |
| --- | --- | --- |
| Console | Vercel Hobby, personal/non-commercial only | UI and operator login |
| Control Plane | Render Free Web Service | API, PostgreSQL state, self-managed Auth |
| PostgreSQL | Neon Free | VisionFlow relational state |
| Queue | Upstash Redis Free | durable Redis-compatible stream for low-volume testing |
| Media storage | Cloudflare R2 free allowance | assets and exports |
| Render worker + relay | Your own machine with Docker | CPU/FFmpeg/video generation |

Deploy Render from `render.free.yaml`, not `render.yaml`. Keep the existing
`render.yaml` for staging/production where the relay and worker run on Render.

## Required limits

- A Render Free web service spins down after 15 idle minutes. The first request
  after idle can take about a minute.
- Render Free is unsuitable for a persistent worker; it is intentionally not
  included in this profile.
- Vercel Hobby is only for personal, non-commercial use.
- Neon, Upstash and R2 free tiers have usage limits. Stop large batch jobs and
  delete old exports before their allowances are exhausted.

## Deploy API at zero cost

1. Create a Render Blueprint using `render.free.yaml` and choose the **Free**
   instance type.
2. Add the values documented in `VISIONFLOW_RENDER_DEPLOYMENT.md`, using a
   Neon pooled URL for `DATABASE_URL`, a Neon direct URL for
   `MIGRATION_DATABASE_URL`, and an Upstash Redis TLS URL for `REDIS_URL`.
3. Set `VISIONFLOW_AUTH_ISSUER` to the Render HTTPS Control Plane URL.
4. Deploy, confirm `/api/v1/health`, then bootstrap the organization and the
   `service|visionflow-intelligence-worker` service membership.
5. Configure Vercel with the deployed Control Plane API URL and organization
   UUID, then redeploy the Console.

## Run rendering locally when needed

On the computer that has Docker, FFmpeg, provider credentials, and sufficient
disk space, set the same `REDIS_URL`, `VISIONFLOW_CONTROL_PLANE_URL`, worker
client credentials, organization UUID, R2 variables, and AI/TTS variables.

Run separate processes:

```powershell
docker build -f worker/Dockerfile -t visionflow-worker .
docker run --rm --env-file worker/.env visionflow-worker

docker build -f services/control-plane/Dockerfile -t visionflow-control-plane .
docker run --rm --env-file services/control-plane/.env visionflow-control-plane `
  python scripts/relay_outbox.py --limit 50
```

Avoid building these images on drive C when it is nearly full. Docker uses a
large build cache and FFmpeg dependencies; use a drive with sufficient space.
