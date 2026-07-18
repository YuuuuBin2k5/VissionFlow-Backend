CREATE TABLE `agent_prompt_templates` (
    `id` INTEGER NOT NULL AUTO_INCREMENT,
    `prompt_key` VARCHAR(100) NOT NULL,
    `name` VARCHAR(160) NOT NULL,
    `description` TEXT NOT NULL,
    `production_version` INTEGER NULL,
    `created_at` DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
    `updated_at` DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),

    UNIQUE INDEX `agent_prompt_templates_prompt_key_key`(`prompt_key`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE `agent_prompt_versions` (
    `id` INTEGER NOT NULL AUTO_INCREMENT,
    `prompt_template_id` INTEGER NOT NULL,
    `version` INTEGER NOT NULL,
    `content` LONGTEXT NOT NULL,
    `config_json` JSON NULL,
    `change_note` VARCHAR(500) NULL,
    `created_by` VARCHAR(255) NULL,
    `created_at` DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),

    UNIQUE INDEX `agent_prompt_versions_prompt_template_id_version_key`(`prompt_template_id`, `version`),
    PRIMARY KEY (`id`)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

ALTER TABLE `agent_prompt_versions` ADD CONSTRAINT `agent_prompt_versions_prompt_template_id_fkey`
    FOREIGN KEY (`prompt_template_id`) REFERENCES `agent_prompt_templates`(`id`) ON DELETE CASCADE ON UPDATE CASCADE;

INSERT INTO `agent_prompt_templates` (`prompt_key`, `name`, `description`, `production_version`)
VALUES ('short_video_idea_generator', 'Short video idea generator', 'Generates the first short-video idea used by the Telegram campaign flow.', 1);

INSERT INTO `agent_prompt_versions` (`prompt_template_id`, `version`, `content`, `config_json`, `change_note`, `created_by`)
SELECT `id`, 1,
'Bạn là chuyên gia sáng tạo nội dung TikTok viral hàng đầu Việt Nam. Hãy đề xuất 1 ý tưởng video ngắn cực kỳ hấp dẫn dựa trên thông tin sau:\n- Chủ đề: "{{topic}}"\n- Đối tượng xem mục tiêu: "{{target_audience}}"\n\nChỉ trả về JSON hợp lệ: {"title":"tiêu đề dưới 60 ký tự","concept":"mô tả kịch bản ngắn","mood":"educational|energetic|lofi|chill|dramatic"}.',
'{"model":"gemini-1.5-flash","temperature":0.7,"response_mime_type":"application/json"}',
'Initial production prompt migrated from Telegram bot.', 'migration'
FROM `agent_prompt_templates` WHERE `prompt_key` = 'short_video_idea_generator';
