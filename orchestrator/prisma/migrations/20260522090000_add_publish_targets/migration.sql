CREATE TABLE `publish_targets` (
  `id` INTEGER NOT NULL AUTO_INCREMENT,
  `job_id` INTEGER NOT NULL,
  `platform` VARCHAR(30) NOT NULL,
  `status` VARCHAR(50) NOT NULL DEFAULT 'PENDING_APPROVAL',
  `scheduled_publish_time` DATETIME(0) NULL,
  `external_video_id` VARCHAR(255) NULL,
  `external_url` VARCHAR(500) NULL,
  `privacy_status` VARCHAR(30) NOT NULL DEFAULT 'public',
  `title` VARCHAR(255) NULL,
  `description` TEXT NULL,
  `tags` JSON NULL,
  `error_log` TEXT NULL,
  `created_at` DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
  `updated_at` DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),

  INDEX `idx_publish_targets_job`(`job_id`),
  INDEX `idx_publish_targets_platform_status`(`platform`, `status`),
  INDEX `idx_publish_targets_scheduled`(`scheduled_publish_time`),
  PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

ALTER TABLE `publish_targets`
  ADD CONSTRAINT `publish_targets_job_id_fkey`
  FOREIGN KEY (`job_id`) REFERENCES `video_pipeline_jobs`(`id`)
  ON DELETE CASCADE ON UPDATE CASCADE;
