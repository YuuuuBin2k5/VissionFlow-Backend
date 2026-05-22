# Security

## Secret Handling

Never commit secrets to Git.

Secrets include:
- Telegram bot tokens
- Google API keys
- OAuth client secrets
- YouTube refresh/access tokens
- TikTok cookies/session data
- Chrome profiles
- database passwords

Use `.env` locally and keep `.env` ignored.
Document required variables in `.env.example`.

## If A Secret Leaks

Rotate it immediately:

- Telegram token: regenerate in BotFather.
- Google API key: restrict or recreate in Google Cloud Console.
- OAuth client secret: rotate/recreate the OAuth client secret.
- Refresh token: revoke app access and run OAuth setup again.

After rotating, update local `.env`.

## GitHub Before First Push

Before pushing to GitHub:

```bash
git status
git diff --cached
```

Confirm these are not staged:

```text
orchestrator/.env
worker/.env
worker/chrome_profile/
worker/temp_assets/
worker/output_videos/
*.mp4
*.mp3
```

## Production Configuration

Follow the 12-factor config principle: deployment-specific config belongs in environment variables or a secret manager, not in source code.

For production-like deploys, prefer:

```bash
npx prisma migrate deploy
```

over development-only database commands.
