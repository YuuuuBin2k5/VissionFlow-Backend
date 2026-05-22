-- CreateTable
CREATE TABLE `channels_campaign` (
    `id` INTEGER NOT NULL AUTO_INCREMENT,
    `telegram_chat_id` BIGINT NOT NULL,
    `topic` VARCHAR(255) NOT NULL,
    `target_audience` TEXT NULL,
    `status` VARCHAR(50) NOT NULL DEFAULT 'INITIALIZING',
    `created_at` DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
    `updated_at` DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),

    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `video_pipeline_jobs` (
    `id` INTEGER NOT NULL AUTO_INCREMENT,
    `campaign_id` INTEGER NULL,
    `day_number` INTEGER NOT NULL,
    `scheduled_post_time` DATETIME(0) NOT NULL,
    `video_title_idea` VARCHAR(255) NULL,
    `hook_text_3s` TEXT NULL,
    `full_voice_script` TEXT NULL,
    `scenes_layout_json` LONGTEXT NULL,
    `seo_tags_metadata` JSON NULL,
    `audio_file_path` VARCHAR(500) NULL,
    `video_output_path` VARCHAR(500) NULL,
    `pipeline_state` VARCHAR(50) NOT NULL DEFAULT 'QUEUED',
    `retry_count` INTEGER NOT NULL DEFAULT 0,
    `max_retries` INTEGER NOT NULL DEFAULT 3,
    `error_log_trace` TEXT NULL,
    `created_at` DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
    `updated_at` DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),

    INDEX `idx_pipeline_state`(`pipeline_state`),
    INDEX `idx_scheduled_time`(`scheduled_post_time`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- CreateTable
CREATE TABLE `process_realtime_logs` (
    `id` INTEGER NOT NULL AUTO_INCREMENT,
    `job_id` INTEGER NULL,
    `execution_step` VARCHAR(100) NOT NULL,
    `status_level` VARCHAR(20) NOT NULL,
    `log_message` TEXT NOT NULL,
    `logged_at` DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),

    INDEX `idx_job_logs`(`job_id`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- AddForeignKey
ALTER TABLE `video_pipeline_jobs` ADD CONSTRAINT `video_pipeline_jobs_campaign_id_fkey` FOREIGN KEY (`campaign_id`) REFERENCES `channels_campaign`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE `process_realtime_logs` ADD CONSTRAINT `process_realtime_logs_job_id_fkey` FOREIGN KEY (`job_id`) REFERENCES `video_pipeline_jobs`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;
