# Render to home PostgreSQL through Tailscale

This is the supported production path for keeping the VisionFlow backend on
Render while PostgreSQL runs on the owner's Windows PC. PostgreSQL is never
published to the public Internet.

## 1. Prepare the Windows host

1. Reserve the PC's LAN address in the router and enable **Restore on AC Power
   Loss** in BIOS/UEFI.
2. In Windows power settings, disable automatic sleep while plugged in.
3. Install Docker Desktop, enable start at sign-in, and verify Linux containers
   start after a reboot.
4. Install Tailscale, sign in to the production tailnet, rename this device to
   `visionflow-db`, and enable **Run unattended**.
5. Do **not** configure router port forwarding or expose TCP 5432 publicly.

Get the PC's Tailscale IPv4 address with `tailscale ip -4`; this is the address
Render targets. Keep `VISIONFLOW_POSTGRES_BIND_IP=127.0.0.1` and
`VISIONFLOW_POSTGRES_PORT=55432` inside `deploy/postgres/.env`. Docker Desktop
on Windows cannot reliably bind directly to the Tailscale adapter. After
PostgreSQL starts, expose it only inside the tailnet with:

```powershell
tailscale serve --bg --tcp=5432 tcp://127.0.0.1:55432
tailscale serve status
```

Never use `0.0.0.0` and never enable Tailscale Funnel for this port.

The PC, Docker Desktop, Tailscale, and Internet connection must remain online.
If any of them stops, the Render API remains alive but database operations fail.

## 2. Create credentials and start PostgreSQL

From the repository root in PowerShell:

```powershell
Copy-Item deploy/postgres/.env.example deploy/postgres/.env
```

Replace all three placeholder passwords with different random values of at
least 32 characters. Keep `.env` local; it is gitignored. Set the data and
backup paths to absolute paths on a reliable SSD, then run:

```powershell
docker compose --env-file deploy/postgres/.env -f deploy/postgres/compose.yaml config
docker compose --env-file deploy/postgres/.env -f deploy/postgres/compose.yaml up -d
docker compose --env-file deploy/postgres/.env -f deploy/postgres/compose.yaml ps
docker exec visionflow-postgres pg_isready -U postgres -d visionflow
```

## 3. Restrict network access

Tag the Windows database node as `tag:visionflow-db`. Create a reusable,
ephemeral, pre-approved Tailscale auth key tagged `tag:visionflow-render` (or a
tag-scoped OAuth client for long-term operation). Store the credential only in
Render. Configure Tailscale grants so the Render tag can reach only the database
tag on TCP 5432. A minimal policy shape is:

```json
{
  "tagOwners": {
    "tag:visionflow-render": ["autogroup:admin"],
    "tag:visionflow-db": ["autogroup:admin"]
  },
  "grants": [
    {
      "src": ["tag:visionflow-render"],
      "dst": ["tag:visionflow-db"],
      "ip": ["tcp:5432"]
    }
  ]
}
```

Merge this into the existing tailnet policy; do not replace unrelated rules.
In Windows Defender Firewall, allow inbound TCP 5432 only from the Tailscale
address range/interface. Confirm from another tailnet device that the port is
reachable, and confirm it is not reachable from the public Internet.

## 4. Move existing data

Before cutover, stop writes or put the application in maintenance mode. Export
the current Neon database with `pg_dump --format=custom`, copy the dump to the
PC, then restore it into `visionflow`. Run Alembic afterward:

```powershell
$env:VISIONFLOW_ALLOW_INSECURE_DB='true'
$env:MIGRATION_DATABASE_URL='postgresql+psycopg://visionflow_migrator:YOUR_PASSWORD@127.0.0.1:5432/visionflow'
Set-Location services/control-plane
../../venv/Scripts/alembic.exe upgrade head
Remove-Item Env:VISIONFLOW_ALLOW_INSECURE_DB
Remove-Item Env:MIGRATION_DATABASE_URL
Set-Location ../..
```

Use URL encoding for special characters in passwords embedded in connection
URLs. Keep the Neon project available until the new path has passed smoke tests.

## 5. Configure Render

Deploy the repository version containing the Tailscale-enabled Dockerfile and
entrypoint. Set these secret/environment values on the Render web service:

```text
VISIONFLOW_TAILSCALE_ENABLED=true
VISIONFLOW_TRUST_LOCAL_DB_PROXY=true
TAILSCALE_AUTHKEY=<ephemeral tagged auth key>
TAILSCALE_HOSTNAME=visionflow-render
TAILSCALE_TAGS=tag:visionflow-render
VISIONFLOW_TAILSCALE_DB_HOST=visionflow-db
VISIONFLOW_TAILSCALE_DB_PORT=5432
DATABASE_URL=postgresql+psycopg://visionflow_app:<encoded password>@127.0.0.1:15432/visionflow
MIGRATION_DATABASE_URL=postgresql+psycopg://visionflow_migrator:<encoded password>@127.0.0.1:15432/visionflow
```

Do not set `VISIONFLOW_ALLOW_INSECURE_DB` on Render. The database URLs are local
to the Render container; the Tailscale leg is encrypted. The entrypoint brings
up Tailscale and the TCP bridge before running Alembic and starting Uvicorn.

## 6. Cut over and verify

1. Deploy Render and watch logs for Tailscale connection, successful Alembic
   migration, and Uvicorn startup.
2. Call `/api/v1/health`, log in, and exercise one read and one reversible write.
3. Verify the new row on the PC database and inspect Render for connection
   errors for at least 15 minutes.
4. Run `deploy/postgres/backup.ps1`, copy the dump off the PC, and test a restore
   before treating the setup as production-ready.
5. Only after stable operation, remove Neon URLs from Render and rotate the old
   Neon credentials that were previously present in repository history.

## Rollback

Pause writes, restore the previous Neon `DATABASE_URL` and
`MIGRATION_DATABASE_URL`, set `VISIONFLOW_TAILSCALE_ENABLED=false`, and redeploy.
Any rows written only to the PC after cutover must be migrated back before Neon
is made writable, otherwise data will diverge.
