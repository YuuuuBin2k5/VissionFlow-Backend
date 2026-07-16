import { Prisma, PrismaClient } from '@prisma/client';
import { randomUUID } from 'crypto';
import { LegacyJobRequested } from './legacyIntakeContract';

export class IntakePersistenceError extends Error {
  constructor(public readonly code: string, message: string) {
    super(message);
  }
}

export interface IntakePersistResult {
  legacyJobId: number;
  created: boolean;
}

type ExistingLink = {
  legacy_job_id: number;
  organization_id: string;
  workflow_run_id: string;
};

/**
 * The sole writer for the new Stream B MySQL aggregate. It deliberately uses
 * raw SQL until the user's existing dirty Prisma schema can be reconciled in
 * its own reviewable migration; no runtime schema creation is performed.
 */
export class LegacyJobIntakeRepository {
  constructor(private readonly prisma: PrismaClient) {}

  async persist(request: LegacyJobRequested): Promise<IntakePersistResult> {
    return this.prisma.$transaction(async (transaction) => {
      const existing = await transaction.$queryRaw<ExistingLink[]>(Prisma.sql`
        SELECT legacy_job_id, organization_id, workflow_run_id
        FROM visionflow_job_links
        WHERE source_command_id = ${request.sourceCommandId}
        FOR UPDATE
      `);
      if (existing.length > 0) {
        const link = existing[0];
        if (link.organization_id === request.organizationId && link.workflow_run_id === request.workflowRunId) {
          return { legacyJobId: Number(link.legacy_job_id), created: false };
        }
        throw new IntakePersistenceError('SOURCE_COMMAND_CONFLICT', 'source_command_id belongs to another workflow');
      }

      // V1 Stream B represents an immediate, unscheduled short-form request.
      // `day_number=0` means it is not part of a Telegram campaign schedule.
      const receivedAt = new Date();
      await transaction.$executeRaw(Prisma.sql`
        INSERT INTO video_pipeline_jobs (
          campaign_id, day_number, scheduled_post_time, video_title_idea,
          hook_text_3s, full_voice_script, scenes_layout_json, pipeline_state
        ) VALUES (
          NULL, 0, ${receivedAt}, ${request.intake.title},
          NULL, NULL, NULL, 'QUEUED'
        )
      `);
      const generated = await transaction.$queryRaw<Array<{ id: bigint | number }>>(Prisma.sql`SELECT LAST_INSERT_ID() AS id`);
      const legacyJobId = Number(generated[0]?.id);
      if (!Number.isSafeInteger(legacyJobId) || legacyJobId <= 0) {
        throw new IntakePersistenceError('LEGACY_JOB_CREATE_FAILED', 'MySQL did not return a valid job ID');
      }

      await transaction.$executeRaw(Prisma.sql`
        INSERT INTO visionflow_job_links (
          id, source_command_id, organization_id, workflow_run_id, legacy_job_id, trace_id
        ) VALUES (
          ${randomUUID()}, ${request.sourceCommandId}, ${request.organizationId},
          ${request.workflowRunId}, ${legacyJobId}, ${request.traceId}
        )
      `);
      await transaction.$executeRaw(Prisma.sql`
        INSERT INTO legacy_outbox (
          id, event_id, source_command_id, organization_id, workflow_run_id,
          legacy_job_id, event_type, payload_json, idempotency_key, status,
          attempt_count, max_attempts, next_attempt_at
        ) VALUES (
          ${randomUUID()}, ${request.eventId}, ${request.sourceCommandId},
          ${request.organizationId}, ${request.workflowRunId}, ${legacyJobId},
          'visionflow.legacy_job.mapping_requested.v1',
          ${JSON.stringify(request.rawPayload)}, ${`legacy-mapping:${request.sourceCommandId}`},
          'PENDING', 0, 10, ${receivedAt}
        )
      `);
      return { legacyJobId, created: true };
    }, { isolationLevel: Prisma.TransactionIsolationLevel.Serializable });
  }
}
