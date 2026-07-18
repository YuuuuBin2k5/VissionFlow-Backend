# Production Deployment

This guide deploys the TikTok + YouTube bot on one VPS, such as Oracle Cloud Ampere A1.

## 1. Server Shape

Recommended first production server:

- Oracle `VM.Standard.A1.Flex`
- 4 OCPU
- 24 GB RAM
- Ubuntu 22.04 or 24.04 ARM64
- 150-200 GB disk

Use one server first. Keep the architecture as a modular monolith until usage grows.

## 2. DNS And HTTPS

Telegram bots can run with polling, so they do not require a public webhook.

YouTube OAuth does need a public redirect URL:

```text
https://your-domain.com/oauth2callback
```

Point your domain to the VPS public IP. Use Caddy or Nginx for HTTPS.

Caddy example:

```bash
sudo apt install -y caddy
sudo cp deploy/Caddyfile.example /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Update Google Cloud OAuth credentials so the authorized redirect URI matches your production URL exactly.

## 3. Install System Packages

```bash
sudo apt update
sudo apt install -y git curl build-essential python3 python3-venv python3-pip ffmpeg
```

Install Docker and Docker Compose plugin:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

Log out and log back in after adding the Docker group.

Install Node.js LTS:

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

Install PM2:

```bash
sudo npm install -g pm2
```

## 4. Clone And Prepare Repo

```bash
git clone https://github.com/YuuuuBin2k5/YuuuBin_Agent_Bot.git
cd YuuuBin_Agent_Bot
```

Create env files:

```bash
cp deploy/orchestrator.env.production.example orchestrator/.env
cp deploy/worker.env.production.example worker/.env
```

Fill real values:

```bash
nano orchestrator/.env
nano worker/.env
```

Generate `APP_SECRET_ENCRYPTION_KEY`:

```bash
openssl rand -base64 48
```

Do not change this key casually after users connect YouTube, because it encrypts stored user tokens.

## 5. Start MySQL And Redis

Create a root `.env` file for Docker Compose:

```bash
cat > .env <<'EOF'
MYSQL_ROOT_PASSWORD=CHANGE_ME
MYSQL_DATABASE=tiktok_agent_automation_db
MYSQL_USER=tiktok_user
MYSQL_PASSWORD=CHANGE_ME_TOO
EOF
```

Make sure the DB password in `orchestrator/.env` and `worker/.env` matches.

Start services:

```bash
docker compose up -d mysql redis
docker compose ps
```

## 6. Install App Dependencies

Node:

```bash
cd orchestrator
npm ci
npx prisma generate
npx prisma migrate deploy
npm run build
cd ..
```

Python:

```bash
python3 -m venv venv
. venv/bin/activate
pip install --upgrade pip
pip install -r worker/requirements.txt
python -m playwright install chromium
python -m playwright install-deps chromium
```

On Oracle ARM64, keep these defaults in `worker/.env`:

```env
BROWSER_CHANNEL=
BROWSER_EXECUTABLE_PATH=
```

## 7. Start Bot 24/7

```bash
pm2 start ecosystem.config.cjs
pm2 save
pm2 startup
```

Run the command printed by `pm2 startup`.

Useful commands:

```bash
pm2 status
pm2 logs agent-bot-orchestrator
pm2 restart agent-bot-orchestrator
```

## 8. Verify

Health:

```bash
curl http://127.0.0.1:3000/health
```

Build/browser smoke test:

```bash
bash scripts/server-smoke-test.sh
```

Telegram:

- Open TikTok bot and run `/start`.
- Open YouTube bot and run `/start`.
- In YouTube bot, press `Kết nối YouTube`.
- Complete Google OAuth.
- Return to Telegram and run `/connection`.

## 9. TikTok Login

TikTok browser automation needs a persistent profile:

```text
worker/chrome_profile/
```

The first TikTok publish should run in headful/login mode so you can scan QR/login.

If the VPS has no desktop display, use one of these options:

- temporarily run with a remote desktop/VNC session
- log in on a compatible machine and securely copy `worker/chrome_profile/` to the VPS
- later split TikTok publisher to an x86 machine while Oracle handles orchestrator/render/YouTube

Never commit `worker/chrome_profile/`.

## 10. Update Deployment

```bash
git pull
cd orchestrator
npm ci
npx prisma migrate deploy
npm run build
cd ..
. venv/bin/activate
pip install -r worker/requirements.txt
pm2 restart agent-bot-orchestrator
```

## 11. Backup

Back up these privately:

- MySQL database
- `orchestrator/.env`
- `worker/.env`
- `worker/chrome_profile/`
- important rendered output if you need to keep it

Example MySQL dump:

```bash
docker exec tiktok_mysql mysqldump -uroot -p tiktok_agent_automation_db > backup.sql
```

## 12. Minimum Required Secrets

System secrets:

- `TELEGRAM_BOT_TOKEN`
- `YOUTUBE_TELEGRAM_BOT_TOKEN`
- `GEMINI_API_KEY`
- `PEXELS_API_KEY`
- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `APP_SECRET_ENCRYPTION_KEY`
- database password

Per-user YouTube tokens are created by `/connect_youtube` and stored encrypted in the database.
