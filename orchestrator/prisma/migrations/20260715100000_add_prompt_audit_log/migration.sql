CREATE TABLE `agent_prompt_audit_logs` (
    `id` INTEGER NOT NULL AUTO_INCREMENT,
    `prompt_template_id` INTEGER NOT NULL,
    `prompt_version` INTEGER NULL,
    `action` VARCHAR(50) NOT NULL,
    `actor_subject` VARCHAR(255) NULL,
    `details_json` JSON NULL,
    `created_at` DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),

    INDEX `idx_agent_prompt_audit_template_created`(`prompt_template_id`, `created_at`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

ALTER TABLE `agent_prompt_audit_logs` ADD CONSTRAINT `agent_prompt_audit_logs_prompt_template_id_fkey`
    FOREIGN KEY (`prompt_template_id`) REFERENCES `agent_prompt_templates`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;
