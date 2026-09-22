#!/bin/sh
set -eu

TAILSCALE_SOCKET=/tmp/visionflow-tailscaled.sock

if [ "${VISIONFLOW_TAILSCALE_ENABLED:-false}" = "true" ]; then
    : "${TAILSCALE_AUTHKEY:?TAILSCALE_AUTHKEY is required when VISIONFLOW_TAILSCALE_ENABLED=true}"
    : "${VISIONFLOW_TAILSCALE_DB_HOST:?VISIONFLOW_TAILSCALE_DB_HOST is required when Tailscale is enabled}"

    echo "==> Starting Tailscale userspace network..."
    tailscaled \
        --tun=userspace-networking \
        --socks5-server=127.0.0.1:1055 \
        --state=mem: \
        --socket="$TAILSCALE_SOCKET" &

    attempts=0
    while [ ! -S "$TAILSCALE_SOCKET" ]; do
        attempts=$((attempts + 1))
        if [ "$attempts" -ge 30 ]; then
            echo "ERROR: Tailscale daemon did not become ready."
            exit 1
        fi
        sleep 1
    done

    tailscale --socket="$TAILSCALE_SOCKET" up \
        --auth-key="$TAILSCALE_AUTHKEY" \
        --hostname="${TAILSCALE_HOSTNAME:-visionflow-render}" \
        --advertise-tags="${TAILSCALE_TAGS:-tag:visionflow-render}"

    python scripts/tailscale_tcp_bridge.py &
    echo "==> Tailscale database tunnel is configured."
fi

echo "==> Checking MIGRATION_DATABASE_URL..."
if [ -z "$MIGRATION_DATABASE_URL" ]; then
    echo "WARN: MIGRATION_DATABASE_URL is not set — skipping alembic migration."
    echo "     Set MIGRATION_DATABASE_URL on Render to enable automatic migrations."
else
    echo "==> Running database migrations (alembic upgrade head)..."
    alembic upgrade head
    echo "==> Migrations complete."
fi

echo "==> Starting control-plane server..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
