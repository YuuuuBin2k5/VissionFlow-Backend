-- Isolated Stream B aggregate. Legacy Telegram tables and handlers are untouched.
CREATE TABLE `visionflow_job_links` (
  `id` CHAR(36) NOT NULL,
  `source_command_id` CHAR(36) NOT NULL,
  `organization_id` CHAR(36) NOT NULL,
  `workflow_run_id` CHAR(36) NOT NULL,
  `legacy_job_id` INTEGER NOT NULL,
  `trace_id` CHAR(32) NOT NULL,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE INDEX `uq_visionflow_job_links_source_command`(`source_command_id`),
  UNIQUE INDEX `uq_visionflow_job_links_workflow_run`(`workflow_run_id`),
  UNIQUE INDEX `uq_visionflow_job_links_legacy_job`(`legacy_job_id`),
  INDEX `idx_visionflow_job_links_org_workflow`(`organization_id`, `workflow_run_id`),
  CONSTRAINT `visionflow_job_links_legacy_job_fkey`
    FOREIGN KEY (`legacy_job_id`) REFERENCES `video_pipeline_jobs`(`id`) ON DELETE RESTRICT ON UPDATE CASCADE
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE `legacy_outbox` (
  `id` CHAR(36) NOT NULL,
  `event_id` CHAR(36) NOT NULL,
  `source_command_id` CHAR(36) NOT NULL,
  `organization_id` CHAR(36) NOT NULL,
  `workflow_run_id` CHAR(36) NOT NULL,
  `legacy_job_id` INTEGER NOT NULL,
  `event_type` VARCHAR(160) NOT NULL,
  `payload_json` JSON NOT NULL,
  `idempotency_key` VARCHAR(128) NOT NULL,
  `status` VARCHAR(32) NOT NULL,
  `attempt_count` INTEGER NOT NULL DEFAULT 0,
  `max_attempts` INTEGER NOT NULL DEFAULT 10,
  `next_attempt_at` DATETIME(3) NOT NULL,
  `lease_token` CHAR(36) NULL,
  `lease_owner` VARCHAR(128) NULL,
  `lease_expires_at` DATETIME(3) NULL,
  `last_error_code` VARCHAR(96) NULL,
  `processed_at` DATETIME(3) NULL,
  `dead_lettered_at` DATETIME(3) NULL,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE INDEX `uq_legacy_outbox_event`(`event_id`),
  UNIQUE INDEX `uq_legacy_outbox_source_command`(`source_command_id`),
  UNIQUE INDEX `uq_legacy_outbox_idempotency`(`idempotency_key`),
  INDEX `idx_legacy_outbox_due`(`status`, `next_attempt_at`, `id`),
  INDEX `idx_legacy_outbox_lease`(`lease_expires_at`),
  CONSTRAINT `legacy_outbox_legacy_job_fkey`
    FOREIGN KEY (`legacy_job_id`) REFERENCES `video_pipeline_jobs`(`id`) ON DELETE RESTRICT ON UPDATE CASCADE
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
