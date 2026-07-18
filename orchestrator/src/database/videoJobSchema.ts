import prisma from './db';

export async function ensureVideoJobLanguageColumns() {
  const columns = await prisma.$queryRawUnsafe<Array<{ COLUMN_NAME: string }>>(
    `SELECT COLUMN_NAME
     FROM INFORMATION_SCHEMA.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'video_pipeline_jobs'
       AND COLUMN_NAME IN ('video_language', 'voice_profile')`,
  );
  const existing = new Set(columns.map((column) => column.COLUMN_NAME));

  if (!existing.has('video_language')) {
    await prisma.$executeRawUnsafe(
      `ALTER TABLE video_pipeline_jobs ADD COLUMN video_language VARCHAR(10) NOT NULL DEFAULT 'vi'`,
    );
  }
  if (!existing.has('voice_profile')) {
    await prisma.$executeRawUnsafe(
      `ALTER TABLE video_pipeline_jobs ADD COLUMN voice_profile VARCHAR(100) NULL`,
    );
  }
}
