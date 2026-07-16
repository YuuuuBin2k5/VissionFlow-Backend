import { Prisma, PrismaClient } from '@prisma/client';
import { randomUUID } from 'crypto';

export type LegacyOutboxStatus = 'PENDING' | 'RETRY_SCHEDULED' | 'PROCESSING' | 'SUCCEEDED' | 'DEAD_LETTER';

export interface ClaimedLegacyOutboxRecord {
  id: string;
  sourceCommandId: string;
  organizationId: string;
  workflowRunId: string;
  legacyJobId: number;
  idempotencyKey: string;
  attemptCount: number;
  maxAttempts: number;
  leaseToken: string;
}

type OutboxRow = {
  id: string;
  source_command_id: string;
  organization_id: string;
  workflow_run_id: string;
  legacy_job_id: number;
  idempotency_key: string;
  attempt_count: number;
  max_attempts: number;
};

export interface LegacyMappingOutboxRepository {
  claimPending(limit: number, leaseOwner: string, leaseSeconds: number): Promise<ClaimedLegacyOutboxRecord[]>;
  markSucceeded(record: ClaimedLegacyOutboxRecord): Promise<void>;
  scheduleRetry(record: ClaimedLegacyOutboxRecord, nextAttemptAt: Date, errorCode: string): Promise<void>;
  markDeadLetter(record: ClaimedLegacyOutboxRecord, errorCode: string): Promise<void>;
}

export class SqlLegacyMappingOutboxRepository implements LegacyMappingOutboxRepository {
  constructor(private readonly prisma: PrismaClient) {}

  async claimPending(limit: number, leaseOwner: string, leaseSeconds: number): Promise<ClaimedLegacyOutboxRecord[]> {
    if (!Number.isInteger(limit) || limit < 1 || limit > 100) throw new Error('limit must be between 1 and 100');
    if (!leaseOwner.trim()) throw new Error('leaseOwner is required');
    if (!Number.isInteger(leaseSeconds) || leaseSeconds < 10 || leaseSeconds > 900) {
      throw new Error('leaseSeconds must be between 10 and 900');
    }
    const leaseToken = randomUUID();
    const leaseExpiresAt = new Date(Date.now() + leaseSeconds * 1_000);
    return this.prisma.$transaction(async (transaction) => {
      const rows = await transaction.$queryRaw<OutboxRow[]>(Prisma.sql`
        SELECT id, source_command_id, organization_id, workflow_run_id, legacy_job_id,
               idempotency_key, attempt_count, max_attempts
        FROM legacy_outbox
        WHERE (
          status IN ('PENDING', 'RETRY_SCHEDULED') AND next_attempt_at <= UTC_TIMESTAMP(3)
        ) OR (
          status = 'PROCESSING' AND lease_expires_at < UTC_TIMESTAMP(3)
        )
        ORDER BY next_attempt_at ASC, id ASC
        LIMIT ${limit}
        FOR UPDATE SKIP LOCKED
      `);
      if (rows.length === 0) return [];
      const ids = rows.map((row) => row.id);
      await transaction.$executeRaw(Prisma.sql`
        UPDATE legacy_outbox
        SET status = 'PROCESSING', lease_token = ${leaseToken}, lease_owner = ${leaseOwner},
            lease_expires_at = ${leaseExpiresAt}, attempt_count = attempt_count + 1,
            last_error_code = NULL
        WHERE id IN (${Prisma.join(ids)})
      `);
      return rows.map((row) => ({
        id: row.id,
        sourceCommandId: row.source_command_id,
        organizationId: row.organization_id,
        workflowRunId: row.workflow_run_id,
        legacyJobId: Number(row.legacy_job_id),
        idempotencyKey: row.idempotency_key,
        attemptCount: Number(row.attempt_count) + 1,
        maxAttempts: Number(row.max_attempts),
        leaseToken,
      }));
    }, { isolationLevel: Prisma.TransactionIsolationLevel.Serializable });
  }

  async markSucceeded(record: ClaimedLegacyOutboxRecord): Promise<void> {
    await this.updateClaimed(record, Prisma.sql`
      status = 'SUCCEEDED', processed_at = UTC_TIMESTAMP(3), lease_token = NULL,
      lease_owner = NULL, lease_expires_at = NULL, last_error_code = NULL
    `);
  }

  async scheduleRetry(record: ClaimedLegacyOutboxRecord, nextAttemptAt: Date, errorCode: string): Promise<void> {
    if (record.attemptCount >= record.maxAttempts) {
      return this.markDeadLetter(record, 'MAX_ATTEMPTS_EXCEEDED');
    }
    await this.updateClaimed(record, Prisma.sql`
      status = 'RETRY_SCHEDULED', next_attempt_at = ${nextAttemptAt}, lease_token = NULL,
      lease_owner = NULL, lease_expires_at = NULL, last_error_code = ${errorCode}
    `);
  }

  async markDeadLetter(record: ClaimedLegacyOutboxRecord, errorCode: string): Promise<void> {
    await this.updateClaimed(record, Prisma.sql`
      status = 'DEAD_LETTER', dead_lettered_at = UTC_TIMESTAMP(3), lease_token = NULL,
      lease_owner = NULL, lease_expires_at = NULL, last_error_code = ${errorCode}
    `);
  }

  private async updateClaimed(record: ClaimedLegacyOutboxRecord, assignment: Prisma.Sql): Promise<void> {
    const updated = await this.prisma.$executeRaw(Prisma.sql`
      UPDATE legacy_outbox SET ${assignment}
      WHERE id = ${record.id} AND status = 'PROCESSING' AND lease_token = ${record.leaseToken}
    `);
    if (updated !== 1) {
      throw new Error(`Outbox lease was lost for record ${record.id}`);
    }
  }
}
