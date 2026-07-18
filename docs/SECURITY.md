# Security

## Secret Handling

Never commit secrets to Git.

Secrets include:
- Telegram bot tokens
- Google API keys
- OAuth client secrets
- YouTube refresh/access tokens
- `APP_SECRET_ENCRYPTION_KEY`
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

Run the local secret scanner:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/security-scan.ps1
```

Install the pre-commit hook once per clone:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install-git-hooks.ps1
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

For Oracle ARM64 deployment details, see `docs/ORACLE_ARM64_DEPLOY.md`.

## Rotation Checklist Before Deploy

Rotate anything that has appeared in chat, screenshots, logs, or public repos.

1. Telegram bot tokens:
   - Open BotFather.
   - Select the bot.
   - Revoke/regenerate the current token.
   - Update only `orchestrator/.env` on the deploy machine.
2. Google API keys:
   - Open Google Cloud Console credentials.
   - Delete leaked keys or create replacements.
   - Restrict each key to only the required APIs.
3. Google OAuth client:
   - Create or rotate the OAuth client secret.
   - Regenerate the YouTube refresh token with the matching client ID/secret.
   - Move the OAuth consent app to production when ready so refresh tokens do not expire after testing windows.
4. Server:
   - Put secrets in `.env` only.
   - Never paste secrets into issue comments, commit messages, PR descriptions, or logs.
   - Back up `.env` privately outside Git.

## Multi-user Token Storage

Per-user YouTube refresh tokens are stored in `platform_connections` after encryption.
The encryption key comes from `APP_SECRET_ENCRYPTION_KEY`.

Do not rotate `APP_SECRET_ENCRYPTION_KEY` casually. If it changes, old encrypted user tokens cannot be decrypted unless you build a migration that decrypts with the old key and re-encrypts with the new key.
