#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Checking Node build..."
cd "$ROOT_DIR/orchestrator"
npm run build

echo "Checking Prisma migration status..."
npx prisma migrate status

echo "Checking Python imports..."
cd "$ROOT_DIR"
python3 -m py_compile \
  worker/config.py \
  worker/main.py \
  worker/services/browser_runtime.py \
  worker/services/publisher_service.py \
  worker/services/browser_render_service.py

echo "Checking Playwright Chromium..."
python3 - <<'PY'
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    print(browser.version)
    browser.close()
PY

echo "Checking app health endpoint..."
curl -fsS http://127.0.0.1:3000/health || true

echo "Smoke test complete."
