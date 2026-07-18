# Oracle ARM64 Deploy Notes

## Recommended VM

Use one Oracle Ampere A1 instance for the first production deploy:

- Shape: `VM.Standard.A1.Flex`
- CPU/RAM: `4 OCPU / 24 GB RAM`
- OS: Ubuntu 22.04 or 24.04 ARM64
- Disk: 150-200 GB boot volume

Keep the app as one modular monolith on this server:

- Node orchestrator
- Python worker
- MySQL
- Redis
- Playwright Chromium
- persistent TikTok browser profile

## Browser Strategy

Oracle Ampere A1 is ARM64. Do not depend on Google Chrome x86 packages.

The worker now supports three browser modes:

1. Default: bundled Playwright Chromium.
2. System Chromium: set `BROWSER_EXECUTABLE_PATH=/usr/bin/chromium-browser` or `/usr/bin/chromium`.
3. Desktop Chrome channel: set `BROWSER_CHANNEL=chrome` only on non-ARM machines where Chrome is installed.

For Oracle ARM64, leave `BROWSER_CHANNEL` empty.

Recommended production `.env` browser values:

```env
BROWSER_CHANNEL=
BROWSER_EXECUTABLE_PATH=
BROWSER_EXTRA_ARGS=
```

If bundled Playwright Chromium has dependency issues, install system Chromium and use:

```env
BROWSER_EXECUTABLE_PATH=/usr/bin/chromium-browser
```

## Server Install Checklist

Install base packages:

```bash
sudo apt update
sudo apt install -y git curl build-essential python3 python3-venv python3-pip ffmpeg
```

Install Node.js LTS and project dependencies.

Install Python dependencies:

```bash
cd worker
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
python -m playwright install-deps chromium
```

If `install-deps` cannot install everything on ARM64, install Chromium from apt:

```bash
sudo apt install -y chromium-browser || sudo apt install -y chromium
```

Then set `BROWSER_EXECUTABLE_PATH` in `worker/.env`.

## TikTok Login/Profile

TikTok publishing uses a persistent browser profile:

```text
worker/chrome_profile/
```

On first login, run the publisher in headful mode on a machine where you can complete QR login.
After login, preserve and back up `worker/chrome_profile/` privately. Never commit it to Git.

## Smoke Tests

Run this after deployment:

```bash
python -c "from worker.services.browser_runtime import describe_browser_runtime; print(describe_browser_runtime())"
python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(headless=True); print(b.version); b.close(); p.stop()"
```

Expected result:

- The first command says `playwright-chromium` or your configured executable path.
- The second command prints a Chromium version without crashing.

## Fallback Plan

If TikTok Studio is unstable on Oracle ARM64:

1. Keep Oracle for orchestrator, queue, database, render, and YouTube upload.
2. Move only TikTok browser publishing to a small x86 VPS or local Windows machine.
3. Keep the same database/queue contract so the architecture does not change.
