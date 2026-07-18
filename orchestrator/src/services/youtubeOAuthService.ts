import { createOAuthState, upsertPlatformConnection, verifyOAuthState } from '../database/userConnectionRepo';

const YOUTUBE_SCOPE = 'https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly';

function requireEnv(name: string) {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is not configured.`);
  return value;
}

export function buildYouTubeConnectUrl(userId: number) {
  const clientId = requireEnv('YOUTUBE_CLIENT_ID');
  const redirectUri = process.env.YOUTUBE_REDIRECT_URI || 'http://localhost:3000/oauth2callback';
  const state = createOAuthState(userId, 'youtube');
  const params = new URLSearchParams({
    client_id: clientId,
    redirect_uri: redirectUri,
    response_type: 'code',
    scope: YOUTUBE_SCOPE,
    access_type: 'offline',
    prompt: 'consent',
    state,
  });
  return `https://accounts.google.com/o/oauth2/v2/auth?${params.toString()}`;
}

export async function handleYouTubeOAuthCallback(code: string, state: string) {
  const verified = verifyOAuthState(state, 'youtube');
  if (!verified) throw new Error('OAuth state is invalid or expired.');

  const clientId = requireEnv('YOUTUBE_CLIENT_ID');
  const clientSecret = requireEnv('YOUTUBE_CLIENT_SECRET');
  const redirectUri = process.env.YOUTUBE_REDIRECT_URI || 'http://localhost:3000/oauth2callback';

  const response = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: clientId,
      client_secret: clientSecret,
      redirect_uri: redirectUri,
      code,
      grant_type: 'authorization_code',
    }),
  });

  const body = await response.text();
  if (!response.ok) {
    throw new Error(`YouTube OAuth token exchange failed (${response.status}): ${body}`);
  }

  const parsed: any = JSON.parse(body);
  if (!parsed.refresh_token) {
    throw new Error('Google did not return a refresh token. Ask the user to remove app access and connect again.');
  }

  const expiresAt = parsed.expires_in
    ? new Date(Date.now() + Number(parsed.expires_in) * 1000)
    : null;

  let externalAccountId: string | null = null;
  let accountName: string | null = null;

  try {
    const channelsResponse = await fetch('https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true', {
      headers: {
        Authorization: `Bearer ${parsed.access_token}`,
      },
    });

    if (channelsResponse.ok) {
      const channelsData: any = await channelsResponse.json();
      if (channelsData.items && channelsData.items.length > 0) {
        const channel = channelsData.items[0];
        externalAccountId = channel.id;
        accountName = channel.snippet?.title || 'YouTube Channel';
      }
    } else {
      console.warn(`[YouTube OAuth] Failed to fetch channel details: ${channelsResponse.statusText}`);
    }
  } catch (err) {
    console.warn('[YouTube OAuth] Failed to fetch channel info:', err);
  }

  await upsertPlatformConnection({
    userId: verified.userId,
    platform: 'youtube',
    accessToken: parsed.access_token || null,
    refreshToken: parsed.refresh_token,
    expiresAt,
    scopes: String(parsed.scope || YOUTUBE_SCOPE).split(/\s+/).filter(Boolean),
    externalAccountId,
    accountName,
  });

  return verified.userId;
}
