CREATE TABLE IF NOT EXISTS `bot_users` (
  `id` INTEGER NOT NULL AUTO_INCREMENT,
  `telegram_user_id` BIGINT NOT NULL,
  `telegram_chat_id` BIGINT NULL,
  `display_name` VARCHAR(255) NULL,
  `role` VARCHAR(30) NOT NULL DEFAULT 'user',
  `created_at` DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
  `updated_at` DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
  UNIQUE INDEX `bot_users_telegram_user_id_key`(`telegram_user_id`),
  PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `platform_connections` (
  `id` INTEGER NOT NULL AUTO_INCREMENT,
  `user_id` INTEGER NOT NULL,
  `platform` VARCHAR(30) NOT NULL,
  `status` VARCHAR(50) NOT NULL DEFAULT 'connected',
  `external_account_id` VARCHAR(255) NULL,
  `account_name` VARCHAR(255) NULL,
  `access_token_encrypted` TEXT NULL,
  `refresh_token_encrypted` TEXT NULL,
  `expires_at` DATETIME(0) NULL,
  `scopes` JSON NULL,
  `error_log` TEXT NULL,
  `created_at` DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
  `updated_at` DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
  UNIQUE INDEX `platform_connections_user_platform_key`(`user_id`, `platform`),
  INDEX `idx_platform_connections_platform_status`(`platform`, `status`),
  PRIMARY KEY (`id`),
  CONSTRAINT `platform_connections_user_id_fkey`
    FOREIGN KEY (`user_id`) REFERENCES `bot_users`(`id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `user_api_keys` (
  `id` INTEGER NOT NULL AUTO_INCREMENT,
  `user_id` INTEGER NOT NULL,
  `provider` VARCHAR(50) NOT NULL,
  `encrypted_key` TEXT NOT NULL,
  `status` VARCHAR(50) NOT NULL DEFAULT 'active',
  `created_at` DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
  `updated_at` DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
  UNIQUE INDEX `user_api_keys_user_provider_key`(`user_id`, `provider`),
  PRIMARY KEY (`id`),
  CONSTRAINT `user_api_keys_user_id_fkey`
    FOREIGN KEY (`user_id`) REFERENCES `bot_users`(`id`)
    ON DELETE CASCADE ON UPDATE CASCADE
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

ALTER TABLE `channels_campaign` ADD COLUMN `user_id` INTEGER NULL;
CREATE INDEX `idx_channels_campaign_user` ON `channels_campaign`(`user_id`);

ALTER TABLE `publish_targets` ADD COLUMN `user_id` INTEGER NULL;
ALTER TABLE `publish_targets` ADD COLUMN `platform_connection_id` INTEGER NULL;
CREATE INDEX `idx_publish_targets_user_platform` ON `publish_targets`(`user_id`, `platform`);
