#!/bin/sh
set -eu

TAILSCALE_SOCKET=/tmp/visionflow-tailscaled.sock
TAILSCALE_HOME=${TAILSCALE_HOME:-/tmp/visionflow-tailscale}
TAILSCALE_STATE=${TAILSCALE_STATE_PATH:-mem:}

mkdir -p "$TAILSCALE_HOME"
export HOME="$TAILSCALE_HOME"
if [ "$TAILSCALE_STATE" != "mem:" ]; then
    mkdir -p "$(dirname "$TAILSCALE_STATE")"
fi

cleanup() {
    [ -n "${BRIDGE_PID:-}" ] && kill "$BRIDGE_PID" 2>/dev/null || true
    [ -n "${TAILSCALED_PID:-}" ] && kill "$TAILSCALED_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if [ "${VISIONFLOW_TAILSCALE_ENABLED:-false}" = "true" ]; then
    : "${TAILSCALE_AUTHKEY:?TAILSCALE_AUTHKEY is required when VISIONFLOW_TAILSCALE_ENABLED=true}"
    : "${VISIONFLOW_TAILSCALE_DB_HOST:?VISIONFLOW_TAILSCALE_DB_HOST is required when Tailscale is enabled}"

    echo "==> Starting Tailscale userspace network..."
    tailscaled \
        --tun=userspace-networking \
        --socks5-server=127.0.0.1:1055 \
        --state="$TAILSCALE_STATE" \
        --socket="$TAILSCALE_SOCKET" &
    TAILSCALED_PID=$!

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
    BRIDGE_PID=$!
    echo "==> Tailscale database tunnel process started."
fi

echo "==> Checking MIGRATION_DATABASE_URL..."
if [ -z "$MIGRATION_DATABASE_URL" ]; then
    echo "WARN: MIGRATION_DATABASE_URL is not set — skipping alembic migration."
    echo "     Set MIGRATION_DATABASE_URL on Render to enable automatic migrations."
else
    echo "==> Waiting for PostgreSQL through the Tailscale tunnel..."
    python scripts/wait_for_database.py \
        --url-env MIGRATION_DATABASE_URL \
        --timeout "${VISIONFLOW_DB_STARTUP_TIMEOUT_SECONDS:-180}"

    echo "==> Running database migrations (alembic upgrade head)..."
    migration_attempt=1
    migration_max_attempts=${VISIONFLOW_MIGRATION_MAX_ATTEMPTS:-5}
    until alembic upgrade head; do
        if [ "$migration_attempt" -ge "$migration_max_attempts" ]; then
            echo "ERROR: Database migration failed after $migration_attempt attempts."
            exit 1
        fi
        migration_delay=$((migration_attempt * 3))
        echo "WARN: Migration attempt $migration_attempt failed; retrying in ${migration_delay}s."
        sleep "$migration_delay"
        python scripts/wait_for_database.py \
            --url-env MIGRATION_DATABASE_URL \
            --timeout "${VISIONFLOW_DB_RETRY_TIMEOUT_SECONDS:-60}"
        migration_attempt=$((migration_attempt + 1))
    done
    echo "==> Migrations complete."
fi

echo "==> Starting control-plane server..."
trap - EXIT INT TERM
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
