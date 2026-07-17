#!/bin/sh

echo "==> Checking MIGRATION_DATABASE_URL..."
if [ -z "$MIGRATION_DATABASE_URL" ]; then
    echo "WARN: MIGRATION_DATABASE_URL is not set — skipping alembic migration."
    echo "     Set MIGRATION_DATABASE_URL on Render to enable automatic migrations."
else
    echo "==> Running database migrations (alembic upgrade head)..."
    alembic upgrade head
    if [ $? -ne 0 ]; then
        echo "ERROR: alembic upgrade head failed. Check MIGRATION_DATABASE_URL and DB connectivity."
        exit 1
    fi
    echo "==> Migrations complete."
fi

echo "==> Starting control-plane server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
