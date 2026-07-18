# Multi-user Connections

The bot is moving from a single-owner setup to a multi-user setup.

## Ownership Model

System-owned secrets stay in `.env`:

- `TELEGRAM_BOT_TOKEN`
- `YOUTUBE_TELEGRAM_BOT_TOKEN`
- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `APP_SECRET_ENCRYPTION_KEY`
- database and Redis credentials

User-owned credentials are stored per user:

- YouTube OAuth refresh token
- future TikTok OAuth token or browser profile reference
- optional user API keys for AI/media providers

## YouTube Flow

1. User starts the YouTube Telegram bot.
2. Bot creates or updates a `bot_users` row from Telegram user ID.
3. User clicks `Kết nối YouTube` or runs `/connect_youtube`.
4. Google redirects to `YOUTUBE_REDIRECT_URI`.
5. The callback stores the user's refresh token encrypted in `platform_connections`.
6. Publish jobs use that user's YouTube connection instead of a global refresh token.

## New Tables

- `bot_users`: maps Telegram users to internal users.
- `platform_connections`: stores encrypted platform tokens per user/platform.
- `user_api_keys`: reserved for optional per-user provider keys.

## Current TikTok Plan

TikTok multi-user support should use one of these later:

- official TikTok OAuth/Content Posting API when available and approved
- separate browser profile per user, such as `worker/browser_profiles/tiktok/{user_id}`

Do not mix multiple users into one TikTok browser profile.
