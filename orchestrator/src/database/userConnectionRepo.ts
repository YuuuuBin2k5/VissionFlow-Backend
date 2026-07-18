import crypto from 'crypto';
import { Prisma } from '@prisma/client';
import prisma from './db';
import { decryptSecret, encryptSecret } from '../security/secretCipher';

export interface BotUserRecord {
  id: number;
  telegram_user_id: bigint;
  telegram_chat_id: bigint | null;
  display_name: string | null;
  role: string;
  created_at: Date;
  updated_at: Date;
}

export interface PlatformConnectionRecord {
  id: number;
  user_id: number;
  platform: string;
  status: string;
  external_account_id: string | null;
  account_name: string | null;
  access_token_encrypted: string | null;
  refresh_token_encrypted: string | null;
  expires_at: Date | null;
  scopes: any;
  error_log: string | null;
  created_at: Date;
  updated_at: Date;
}

async function columnExists(tableName: string, columnName: string) {
  const rows = await prisma.$queryRaw<Array<{ count_value: bigint }>>(
    Prisma.sql`
      SELECT COUNT(*) AS count_value
      FROM information_schema.COLUMNS
      WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = ${tableName}
        AND COLUMN_NAME = ${columnName}
    `,
  );
  return Number(rows[0]?.count_value || 0) > 0;
}

async function indexExists(tableName: string, indexName: string) {
  const rows = await prisma.$queryRaw<Array<{ count_value: bigint }>>(
    Prisma.sql`
      SELECT COUNT(*) AS count_value
      FROM information_schema.STATISTICS
      WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME = ${tableName}
        AND INDEX_NAME = ${indexName}
    `,
  );
  return Number(rows[0]?.count_value || 0) > 0;
}

export async function ensureUserConnectionTables() {
  await prisma.$executeRawUnsafe(`
    CREATE TABLE IF NOT EXISTS bot_users (
      id INTEGER NOT NULL AUTO_INCREMENT,
      telegram_user_id BIGINT NOT NULL,
      telegram_chat_id BIGINT NULL,
      display_name VARCHAR(255) NULL,
      role VARCHAR(30) NOT NULL DEFAULT 'user',
      created_at DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
      updated_at DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
      UNIQUE INDEX bot_users_telegram_user_id_key(telegram_user_id),
      PRIMARY KEY (id)
    ) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
  `);

  await prisma.$executeRawUnsafe(`
    CREATE TABLE IF NOT EXISTS platform_connections (
      id INTEGER NOT NULL AUTO_INCREMENT,
      user_id INTEGER NOT NULL,
      platform VARCHAR(30) NOT NULL,
      status VARCHAR(50) NOT NULL DEFAULT 'connected',
      external_account_id VARCHAR(255) NULL,
      account_name VARCHAR(255) NULL,
      access_token_encrypted TEXT NULL,
      refresh_token_encrypted TEXT NULL,
      expires_at DATETIME(0) NULL,
      scopes JSON NULL,
      error_log TEXT NULL,
      created_at DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
      updated_at DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
      UNIQUE INDEX platform_connections_user_platform_account_key(user_id, platform, external_account_id),
      INDEX idx_platform_connections_platform_status(platform, status),
      PRIMARY KEY (id),
      CONSTRAINT platform_connections_user_id_fkey
        FOREIGN KEY (user_id) REFERENCES bot_users(id)
        ON DELETE CASCADE ON UPDATE CASCADE
    ) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
  `);

  await prisma.$executeRawUnsafe(`
    CREATE TABLE IF NOT EXISTS user_api_keys (
      id INTEGER NOT NULL AUTO_INCREMENT,
      user_id INTEGER NOT NULL,
      provider VARCHAR(50) NOT NULL,
      encrypted_key TEXT NOT NULL,
      status VARCHAR(50) NOT NULL DEFAULT 'active',
      created_at DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
      updated_at DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
      UNIQUE INDEX user_api_keys_user_provider_key(user_id, provider),
      PRIMARY KEY (id),
      CONSTRAINT user_api_keys_user_id_fkey
        FOREIGN KEY (user_id) REFERENCES bot_users(id)
        ON DELETE CASCADE ON UPDATE CASCADE
    ) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
  `);

  if (!(await columnExists('channels_campaign', 'user_id'))) {
    await prisma.$executeRawUnsafe(`ALTER TABLE channels_campaign ADD COLUMN user_id INTEGER NULL`);
  }
  if (!(await indexExists('channels_campaign', 'idx_channels_campaign_user'))) {
    await prisma.$executeRawUnsafe(`CREATE INDEX idx_channels_campaign_user ON channels_campaign(user_id)`);
  }

  if (!(await columnExists('publish_targets', 'user_id'))) {
    await prisma.$executeRawUnsafe(`ALTER TABLE publish_targets ADD COLUMN user_id INTEGER NULL`);
  }
  if (!(await columnExists('publish_targets', 'platform_connection_id'))) {
    await prisma.$executeRawUnsafe(`ALTER TABLE publish_targets ADD COLUMN platform_connection_id INTEGER NULL`);
  }
  if (!(await indexExists('publish_targets', 'idx_publish_targets_user_platform'))) {
    await prisma.$executeRawUnsafe(`CREATE INDEX idx_publish_targets_user_platform ON publish_targets(user_id, platform)`);
  }

  // Self-healing migration for multi-account unique key
  if (!(await indexExists('platform_connections', 'platform_connections_user_platform_account_key'))) {
    console.log('[Migration] Creating new unique index: platform_connections_user_platform_account_key...');
    await prisma.$executeRawUnsafe(`ALTER TABLE platform_connections ADD UNIQUE INDEX platform_connections_user_platform_account_key(user_id, platform, external_account_id)`);
  }
  if (await indexExists('platform_connections', 'platform_connections_user_platform_key')) {
    console.log('[Migration] Dropping old unique index: platform_connections_user_platform_key...');
    await prisma.$executeRawUnsafe(`ALTER TABLE platform_connections DROP INDEX platform_connections_user_platform_key`);
  }
}

export async function upsertTelegramUser(input: {
  telegramUserId: number | bigint;
  telegramChatId?: number | bigint | null;
  displayName?: string | null;
}) {
  const telegramUserId = BigInt(input.telegramUserId);
  const telegramChatId = input.telegramChatId === undefined || input.telegramChatId === null ? null : BigInt(input.telegramChatId);
  await prisma.$executeRaw(
    Prisma.sql`
      INSERT INTO bot_users (telegram_user_id, telegram_chat_id, display_name)
      VALUES (${telegramUserId}, ${telegramChatId}, ${input.displayName || null})
      ON DUPLICATE KEY UPDATE
        telegram_chat_id = VALUES(telegram_chat_id),
        display_name = COALESCE(VALUES(display_name), display_name),
        updated_at = CURRENT_TIMESTAMP(0)
    `,
  );
  const rows = await prisma.$queryRaw<BotUserRecord[]>(
    Prisma.sql`SELECT * FROM bot_users WHERE telegram_user_id = ${telegramUserId} LIMIT 1`,
  );
  return rows[0];
}

export async function getTelegramUser(telegramUserId: number | bigint) {
  const rows = await prisma.$queryRaw<BotUserRecord[]>(
    Prisma.sql`SELECT * FROM bot_users WHERE telegram_user_id = ${BigInt(telegramUserId)} LIMIT 1`,
  );
  return rows[0] || null;
}

export function createOAuthState(userId: number, platform: string) {
  const timestamp = Date.now().toString(36);
  const nonce = crypto.randomBytes(12).toString('base64url');
  const payload = `${userId}.${platform}.${timestamp}.${nonce}`;
  const secret = process.env.APP_SECRET_ENCRYPTION_KEY || process.env.YOUTUBE_CLIENT_SECRET || 'dev-state-secret';
  const signature = crypto.createHmac('sha256', secret).update(payload).digest('base64url');
  return `${payload}.${signature}`;
}

export function verifyOAuthState(state: string, expectedPlatform: string) {
  const parts = state.split('.');
  if (parts.length !== 5) return null;
  const [userIdRaw, platform, timestampRaw, nonce, signature] = parts;
  if (platform !== expectedPlatform) return null;
  const payload = `${userIdRaw}.${platform}.${timestampRaw}.${nonce}`;
  const secret = process.env.APP_SECRET_ENCRYPTION_KEY || process.env.YOUTUBE_CLIENT_SECRET || 'dev-state-secret';
  const expected = crypto.createHmac('sha256', secret).update(payload).digest('base64url');
  if (signature.length !== expected.length) return null;
  if (!crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected))) return null;
  const createdAt = parseInt(timestampRaw, 36);
  if (!Number.isFinite(createdAt) || Date.now() - createdAt > 15 * 60 * 1000) return null;
  const userId = parseInt(userIdRaw, 10);
  return Number.isFinite(userId) ? { userId, platform } : null;
}

export async function upsertPlatformConnection(input: {
  userId: number;
  platform: 'youtube' | 'tiktok';
  accessToken?: string | null;
  refreshToken?: string | null;
  expiresAt?: Date | null;
  scopes?: string[];
  externalAccountId?: string | null;
  accountName?: string | null;
}) {
  const accessToken = input.accessToken ? encryptSecret(input.accessToken) : null;
  const refreshToken = input.refreshToken ? encryptSecret(input.refreshToken) : null;
  await prisma.$executeRaw(
    Prisma.sql`
      INSERT INTO platform_connections
        (user_id, platform, status, access_token_encrypted, refresh_token_encrypted, expires_at, scopes, external_account_id, account_name)
      VALUES
        (${input.userId}, ${input.platform}, 'connected', ${accessToken}, ${refreshToken}, ${input.expiresAt || null}, CAST(${JSON.stringify(input.scopes || [])} AS JSON), ${input.externalAccountId || null}, ${input.accountName || null})
      ON DUPLICATE KEY UPDATE
        status = 'connected',
        access_token_encrypted = COALESCE(VALUES(access_token_encrypted), access_token_encrypted),
        refresh_token_encrypted = COALESCE(VALUES(refresh_token_encrypted), refresh_token_encrypted),
        expires_at = VALUES(expires_at),
        scopes = VALUES(scopes),
        external_account_id = COALESCE(VALUES(external_account_id), external_account_id),
        account_name = COALESCE(VALUES(account_name), account_name),
        error_log = NULL,
        updated_at = CURRENT_TIMESTAMP(0)
    `,
  );
  return getPlatformConnection(input.userId, input.platform, input.externalAccountId);
}

export async function getPlatformConnection(userId: number, platform: 'youtube' | 'tiktok', externalAccountId?: string | null) {
  if (externalAccountId !== undefined && externalAccountId !== null) {
    const rows = await prisma.$queryRaw<PlatformConnectionRecord[]>(
      Prisma.sql`
        SELECT * FROM platform_connections
        WHERE user_id = ${userId}
          AND platform = ${platform}
          AND external_account_id = ${externalAccountId}
        LIMIT 1
      `,
    );
    return rows[0] || null;
  } else {
    const rows = await prisma.$queryRaw<PlatformConnectionRecord[]>(
      Prisma.sql`
        SELECT * FROM platform_connections
        WHERE user_id = ${userId}
          AND platform = ${platform}
        ORDER BY updated_at DESC
        LIMIT 1
      `,
    );
    return rows[0] || null;
  }
}

export async function getPlatformConnectionById(id: number) {
  const rows = await prisma.$queryRaw<PlatformConnectionRecord[]>(
    Prisma.sql`
      SELECT * FROM platform_connections
      WHERE id = ${id}
      LIMIT 1
    `,
  );
  return rows[0] || null;
}

export async function getConnectedPlatformConnection(userId: number, platform: 'youtube' | 'tiktok') {
  const connection = await getPlatformConnection(userId, platform);
  return connection && connection.status === 'connected' ? connection : null;
}

export function decryptConnectionRefreshToken(connection: PlatformConnectionRecord) {
  if (!connection.refresh_token_encrypted) return null;
  return decryptSecret(connection.refresh_token_encrypted);
}

export async function getAllPlatformConnections(userId: number, platform?: 'youtube' | 'tiktok') {
  if (platform) {
    return prisma.$queryRaw<PlatformConnectionRecord[]>(
      Prisma.sql`
        SELECT * FROM platform_connections
        WHERE user_id = ${userId}
          AND platform = ${platform}
        ORDER BY created_at DESC
      `,
    );
  }
  return prisma.$queryRaw<PlatformConnectionRecord[]>(
    Prisma.sql`
      SELECT * FROM platform_connections
      WHERE user_id = ${userId}
      ORDER BY platform ASC, created_at DESC
    `,
  );
}

export async function disconnectPlatform(userId: number, platform: 'youtube' | 'tiktok') {
  await prisma.$executeRaw(
    Prisma.sql`
      UPDATE platform_connections
      SET status = 'revoked', updated_at = CURRENT_TIMESTAMP(0)
      WHERE user_id = ${userId}
        AND platform = ${platform}
    `,
  );
}
