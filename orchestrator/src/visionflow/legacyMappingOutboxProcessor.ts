import { ControlPlaneLegacyMappingClient, ControlPlaneRequestError } from './controlPlaneLegacyMappingClient';
import { ClaimedLegacyOutboxRecord, LegacyMappingOutboxRepository } from './legacyMappingOutboxRepository';

export interface LegacyMappingOutboxProcessorSettings {
  leaseOwner: string;
  leaseSeconds: number;
  batchSize: number;
}

export class LegacyMappingOutboxProcessor {
  constructor(
    private readonly repository: LegacyMappingOutboxRepository,
    private readonly client: ControlPlaneLegacyMappingClient,
    private readonly settings: LegacyMappingOutboxProcessorSettings,
  ) {}

  async executeOnce(): Promise<number> {
    const records = await this.repository.claimPending(
      this.settings.batchSize,
      this.settings.leaseOwner,
      this.settings.leaseSeconds,
    );
    for (const record of records) await this.deliver(record);
    return records.length;
  }

  private async deliver(record: ClaimedLegacyOutboxRecord): Promise<void> {
    try {
      await this.client.register(record);
      await this.repository.markSucceeded(record);
    } catch (error) {
      const classification = classify(error);
      if (classification.retryable) {
        await this.repository.scheduleRetry(record, retryAt(record.attemptCount), classification.code);
      } else {
        await this.repository.markDeadLetter(record, classification.code);
      }
    }
  }
}

function classify(error: unknown): { code: string; retryable: boolean } {
  if (!(error instanceof ControlPlaneRequestError)) return { code: 'UNEXPECTED_DELIVERY_ERROR', retryable: true };
  if (error.statusCode === null || error.statusCode >= 500 || error.statusCode === 429) {
    return { code: error.statusCode === 429 ? 'CONTROL_PLANE_RATE_LIMITED' : 'CONTROL_PLANE_UNAVAILABLE', retryable: true };
  }
  if (error.statusCode === 409) return { code: 'LEGACY_JOB_MAPPING_CONFLICT', retryable: false };
  if (error.statusCode === 401 || error.statusCode === 403) return { code: 'CONTROL_PLANE_AUTHORIZATION_REJECTED', retryable: false };
  if (error.statusCode === 400 || error.statusCode === 404 || error.statusCode === 422) {
    return { code: 'CONTROL_PLANE_COMMAND_REJECTED', retryable: false };
  }
  return { code: 'CONTROL_PLANE_REQUEST_REJECTED', retryable: false };
}

function retryAt(attemptCount: number): Date {
  const cappedExponent = Math.min(Math.max(attemptCount - 1, 0), 8);
  const delayMs = Math.min(30_000 * (2 ** cappedExponent), 30 * 60_000);
  return new Date(Date.now() + delayMs);
}
