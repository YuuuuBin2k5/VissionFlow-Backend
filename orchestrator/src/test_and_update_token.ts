import dotenv from 'dotenv';
import { prisma } from './database/db';
import { encryptSecret } from './security/secretCipher';

dotenv.config();

const NEW_REFRESH_TOKEN = "1//0gU-SXCjyXVyDCgYIARAAGBASNwF-L9IrCAPLR7IGNBtpyoLB3HvL7AKi7C7GPIf2jsuLcO2iBD5pXq7q9zXfyORWVcFuPKh_Dio";

async function main() {
  console.log('Testing refresh token against Google APIs...');
  
  const clientId = process.env.YOUTUBE_CLIENT_ID;
  const clientSecret = process.env.YOUTUBE_CLIENT_SECRET;
  
  if (!clientId || !clientSecret) {
    console.error('Error: YOUTUBE_CLIENT_ID or YOUTUBE_CLIENT_SECRET is missing from .env');
    process.exit(1);
  }
  
  // 1. Exchange refresh token for access token
  const tokenResponse = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: clientId,
      client_secret: clientSecret,
      refresh_token: NEW_REFRESH_TOKEN,
      grant_type: 'refresh_token',
    }),
  });
  
  const tokenBody = await tokenResponse.text();
  if (!tokenResponse.ok) {
    console.error(`Error exchanging refresh token: (${tokenResponse.status}) ${tokenBody}`);
    process.exit(1);
  }
  
  const parsedToken = JSON.parse(tokenBody);
  const accessToken = parsedToken.access_token;
  console.log('Successfully obtained new access token.');
  
  // 2. Encrypt the new refresh token
  console.log('\nEncrypting the new refresh token...');
  const encryptedRefreshToken = encryptSecret(NEW_REFRESH_TOKEN);
  const encryptedAccessToken = encryptSecret(accessToken);
  const expiresAt = parsedToken.expires_in
    ? new Date(Date.now() + Number(parsedToken.expires_in) * 1000)
    : null;
  
  // 3. Update connection ID 6 (Góc Chiêm Nghiệm | YuuBin)
  const connectionId = 6;
  console.log(`Updating connection ID ${connectionId} with the new refresh token...`);
  
  await prisma.$executeRawUnsafe(
    `UPDATE platform_connections 
     SET refresh_token_encrypted = ?, access_token_encrypted = ?, expires_at = ?, status = 'connected', error_log = NULL, updated_at = NOW()
     WHERE id = ?`,
    encryptedRefreshToken,
    encryptedAccessToken,
    expiresAt,
    connectionId
  );
  
  console.log(`SUCCESS: Database updated successfully for connection ID ${connectionId}!`);
}

main()
  .then(() => prisma.$disconnect())
  .catch((err) => {
    console.error('Failed to update token:', err);
    prisma.$disconnect();
    process.exit(1);
  });
