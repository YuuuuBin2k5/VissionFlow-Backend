import dotenv from 'dotenv';
import * as readline from 'readline/promises';
import { stdin as input, stdout as output } from 'process';

dotenv.config();

const clientId = process.env.YOUTUBE_CLIENT_ID;
const clientSecret = process.env.YOUTUBE_CLIENT_SECRET;
const redirectUri = process.env.YOUTUBE_REDIRECT_URI || 'http://localhost:3000/oauth2callback';

if (!clientId || !clientSecret) {
  console.error('Missing YOUTUBE_CLIENT_ID or YOUTUBE_CLIENT_SECRET in .env');
  process.exit(1);
}

const scope = encodeURIComponent('https://www.googleapis.com/auth/youtube.upload');
const authUrl =
  `https://accounts.google.com/o/oauth2/v2/auth?` +
  `client_id=${encodeURIComponent(clientId)}` +
  `&redirect_uri=${encodeURIComponent(redirectUri)}` +
  `&response_type=code` +
  `&scope=${scope}` +
  `&access_type=offline` +
  `&prompt=consent`;

async function main() {
  console.log('\nOpen this URL, approve YouTube upload access, then paste the returned code:\n');
  console.log(authUrl);
  const rl = readline.createInterface({ input, output });
  const code = (await rl.question('\nAuthorization code: ')).trim();
  rl.close();

  const response = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: clientId!,
      client_secret: clientSecret!,
      redirect_uri: redirectUri,
      code,
      grant_type: 'authorization_code',
    }),
  });

  const body = await response.text();
  if (!response.ok) {
    console.error(`OAuth token exchange failed (${response.status}): ${body}`);
    process.exit(1);
  }

  const parsed = JSON.parse(body);
  console.log('\nAdd this to orchestrator/.env:\n');
  console.log(`YOUTUBE_REFRESH_TOKEN="${parsed.refresh_token}"`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
