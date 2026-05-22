import { Prisma } from '@prisma/client';
import prisma from './db';

export interface PublishTargetRecord {
  id: number;
  job_id: number;
  platform: string;
  status: string;
  scheduled_publish_time: Date | null;
  external_video_id: string | null;
  external_url: string | null;
  privacy_status: string;
  title: string | null;
  description: string | null;
  tags: any;
  error_log: string | null;
  created_at: Date;
  updated_at: Date;
}

export function parseTargetTags(tags: any): string[] {
  if (!tags) return [];
  if (Array.isArray(tags)) return tags.map(String);
  try {
    const parsed = typeof tags === 'string' ? JSON.parse(tags) : tags;
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
}

export async function ensurePublishTargetsTable() {
  await prisma.$executeRawUnsafe(`
    CREATE TABLE IF NOT EXISTS publish_targets (
      id INTEGER NOT NULL AUTO_INCREMENT,
      job_id INTEGER NOT NULL,
      platform VARCHAR(30) NOT NULL,
      status VARCHAR(50) NOT NULL DEFAULT 'PENDING_APPROVAL',
      scheduled_publish_time DATETIME(0) NULL,
      external_video_id VARCHAR(255) NULL,
      external_url VARCHAR(500) NULL,
      privacy_status VARCHAR(30) NOT NULL DEFAULT 'public',
      title VARCHAR(255) NULL,
      description TEXT NULL,
      tags JSON NULL,
      error_log TEXT NULL,
      created_at DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
      updated_at DATETIME(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
      INDEX idx_publish_targets_job(job_id),
      INDEX idx_publish_targets_platform_status(platform, status),
      INDEX idx_publish_targets_scheduled(scheduled_publish_time),
      PRIMARY KEY (id),
      CONSTRAINT publish_targets_job_id_fkey
        FOREIGN KEY (job_id) REFERENCES video_pipeline_jobs(id)
        ON DELETE CASCADE ON UPDATE CASCADE
    ) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
  `);
}

export async function findActiveYouTubeTarget(jobId: number, statuses: string[]) {
  const rows = await prisma.$queryRaw<PublishTargetRecord[]>(
    Prisma.sql`
      SELECT * FROM publish_targets
      WHERE job_id = ${jobId}
        AND platform = 'youtube'
        AND status IN (${Prisma.join(statuses)})
      ORDER BY updated_at DESC
      LIMIT 1
    `,
  );
  return rows[0] || null;
}

export async function createYouTubeTarget(input: {
  jobId: number;
  scheduledTime: Date | null;
  privacyStatus: string;
  title: string;
  description: string;
  tags: string[];
}) {
  await prisma.$executeRaw(
    Prisma.sql`
      INSERT INTO publish_targets
        (job_id, platform, status, scheduled_publish_time, privacy_status, title, description, tags)
      VALUES
        (${input.jobId}, 'youtube', 'PENDING_APPROVAL', ${input.scheduledTime}, ${input.privacyStatus}, ${input.title}, ${input.description}, CAST(${JSON.stringify(input.tags)} AS JSON))
    `,
  );
  return findActiveYouTubeTarget(input.jobId, ['PENDING_APPROVAL']);
}

export async function updateYouTubeTarget(id: number, input: Partial<{
  status: string;
  scheduled_publish_time: Date | null;
  external_video_id: string | null;
  external_url: string | null;
  privacy_status: string;
  title: string | null;
  description: string | null;
  tags: string[];
  error_log: string | null;
}>) {
  const currentRows = await prisma.$queryRaw<PublishTargetRecord[]>(Prisma.sql`SELECT * FROM publish_targets WHERE id = ${id} LIMIT 1`);
  const current = currentRows[0];
  if (!current) throw new Error(`Publish target #${id} was not found.`);

  await prisma.$executeRaw(
    Prisma.sql`
      UPDATE publish_targets
      SET
        status = ${input.status ?? current.status},
        scheduled_publish_time = ${input.scheduled_publish_time !== undefined ? input.scheduled_publish_time : current.scheduled_publish_time},
        external_video_id = ${input.external_video_id !== undefined ? input.external_video_id : current.external_video_id},
        external_url = ${input.external_url !== undefined ? input.external_url : current.external_url},
        privacy_status = ${input.privacy_status ?? current.privacy_status},
        title = ${input.title !== undefined ? input.title : current.title},
        description = ${input.description !== undefined ? input.description : current.description},
        tags = CAST(${JSON.stringify(input.tags !== undefined ? input.tags : parseTargetTags(current.tags))} AS JSON),
        error_log = ${input.error_log !== undefined ? input.error_log : current.error_log},
        updated_at = CURRENT_TIMESTAMP(0)
      WHERE id = ${id}
    `,
  );

  const rows = await prisma.$queryRaw<PublishTargetRecord[]>(Prisma.sql`SELECT * FROM publish_targets WHERE id = ${id} LIMIT 1`);
  return rows[0];
}

export async function updateActiveYouTubeTargets(jobId: number, statuses: string[], status: string, errorLog: string | null) {
  await prisma.$executeRaw(
    Prisma.sql`
      UPDATE publish_targets
      SET status = ${status}, error_log = ${errorLog}, updated_at = CURRENT_TIMESTAMP(0)
      WHERE job_id = ${jobId}
        AND platform = 'youtube'
        AND status IN (${Prisma.join(statuses)})
    `,
  );
}

export async function getYouTubeTargetsForSchedule(start: Date, end: Date) {
  return prisma.$queryRaw<Array<PublishTargetRecord & { video_title_idea: string | null }>>(
    Prisma.sql`
      SELECT pt.*, j.video_title_idea
      FROM publish_targets pt
      JOIN video_pipeline_jobs j ON j.id = pt.job_id
      WHERE pt.platform = 'youtube'
        AND pt.scheduled_publish_time >= ${start}
        AND pt.scheduled_publish_time < ${end}
      ORDER BY pt.scheduled_publish_time ASC
    `,
  );
}

export async function getYouTubePendingTargets() {
  return prisma.$queryRaw<Array<PublishTargetRecord & { video_title_idea: string | null }>>(
    Prisma.sql`
      SELECT pt.*, j.video_title_idea
      FROM publish_targets pt
      JOIN video_pipeline_jobs j ON j.id = pt.job_id
      WHERE pt.platform = 'youtube'
        AND pt.status = 'PENDING_APPROVAL'
        AND j.pipeline_state IN ('RENDERED', 'RENDERED_SUBTITLED')
      ORDER BY pt.scheduled_publish_time ASC
      LIMIT 10
    `,
  );
}

export async function getYouTubeTargetStatusCounts() {
  return prisma.$queryRaw<Array<{ status: string; count_value: bigint }>>(
    Prisma.sql`
      SELECT status, COUNT(*) AS count_value
      FROM publish_targets
      WHERE platform = 'youtube'
      GROUP BY status
    `,
  );
}

export async function getDueYouTubeTargets(now: Date) {
  return prisma.$queryRaw<Array<PublishTargetRecord & { campaign_status: string | null }>>(
    Prisma.sql`
      SELECT pt.*, c.status AS campaign_status
      FROM publish_targets pt
      JOIN video_pipeline_jobs j ON j.id = pt.job_id
      LEFT JOIN channels_campaign c ON c.id = j.campaign_id
      WHERE pt.platform = 'youtube'
        AND pt.status IN ('APPROVED', 'PUBLISH_QUEUED')
        AND pt.scheduled_publish_time <= ${now}
    `,
  );
}
