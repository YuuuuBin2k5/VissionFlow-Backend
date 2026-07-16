import IORedis from 'ioredis';
import prisma from '../database/db';
import { controlPlaneLegacyMappingSettingsFromEnv, HttpControlPlaneLegacyMappingClient } from './controlPlaneLegacyMappingClient';
import { intakeHmacKeysFromEnv } from './legacyIntakeContract';
import { LegacyIntakeConsumer } from './legacyIntakeConsumer';
import { LegacyJobIntakeRepository } from './legacyJobIntakeRepository';
import { LegacyMappingOutboxProcessor } from './legacyMappingOutboxProcessor';
import { SqlLegacyMappingOutboxRepository } from './legacyMappingOutboxRepository';

export interface LegacyIntakeRuntime {
  stop(): Promise<void>;
  health(): LegacyIntakeHealth;
}

export interface LegacyIntakeHealth {
  enabled: boolean;
  running: boolean;
  /** Redis consumer-group initialization completed and no current runtime failure is known. */
  ready: boolean;
  lastConsumerSuccessAt: string | null;
  lastProcessorSuccessAt: string | null;
  lastErrorCode: string | null;
}

/**
 * Builds Stream B only when the exact opt-in flag is enabled. Keeping this out
 * of main.ts is intentional until migration rehearsal and deployment review.
 */
export function startLegacyIntakeRuntime(env: NodeJS.ProcessEnv = process.env): LegacyIntakeRuntime | null {
  if (env.VISIONFLOW_LEGACY_INTAKE_ENABLED !== 'true') return null;
  const redisUrl = required(env.REDIS_URL, 'REDIS_URL');
  const redis = new IORedis(redisUrl, { maxRetriesPerRequest: null });
  const instanceId = env.VISIONFLOW_LEGACY_INTAKE_INSTANCE_ID?.trim() || `legacy-intake-${process.pid}`;
  const stream = env.VISIONFLOW_EVENTS_STREAM?.trim() || 'visionflow.workflow-events.v1';
  const consumer = new LegacyIntakeConsumer(
    redis,
    new LegacyJobIntakeRepository(prisma),
    intakeHmacKeysFromEnv(env),
    {
      stream,
      group: env.VISIONFLOW_LEGACY_INTAKE_GROUP?.trim() || 'visionflow-legacy-orchestrator-intake',
      consumer: instanceId,
      deadLetterStream: env.VISIONFLOW_LEGACY_INTAKE_DLQ_STREAM?.trim() || `${stream}.legacy-intake.dlq`,
      maxDeliveries: positiveInteger(env.VISIONFLOW_LEGACY_INTAKE_MAX_DELIVERIES, 10, 'VISIONFLOW_LEGACY_INTAKE_MAX_DELIVERIES'),
      claimIdleMs: positiveInteger(env.VISIONFLOW_LEGACY_INTAKE_CLAIM_IDLE_MS, 60_000, 'VISIONFLOW_LEGACY_INTAKE_CLAIM_IDLE_MS'),
    },
  );
  const processor = new LegacyMappingOutboxProcessor(
    new SqlLegacyMappingOutboxRepository(prisma),
    new HttpControlPlaneLegacyMappingClient(controlPlaneLegacyMappingSettingsFromEnv(env)),
    {
      leaseOwner: instanceId,
      leaseSeconds: positiveInteger(env.VISIONFLOW_LEGACY_MAPPING_LEASE_SECONDS, 60, 'VISIONFLOW_LEGACY_MAPPING_LEASE_SECONDS'),
      batchSize: positiveInteger(env.VISIONFLOW_LEGACY_MAPPING_BATCH_SIZE, 20, 'VISIONFLOW_LEGACY_MAPPING_BATCH_SIZE'),
    },
  );
  const state: LegacyIntakeHealth = {
    enabled: true,
    running: true,
    ready: false,
    lastConsumerSuccessAt: null,
    lastProcessorSuccessAt: null,
    lastErrorCode: null,
  };
  let stopped = false;
  const runConsumer = async () => {
    if (stopped) return;
    try {
      await consumer.reclaimPendingOnce();
      await consumer.consumeOnce(1_000);
      state.ready = true;
      state.lastConsumerSuccessAt = new Date().toISOString();
      state.lastErrorCode = null;
    } catch (error) {
      state.ready = false;
      state.lastErrorCode = error instanceof Error ? error.name : 'CONSUMER_FAILURE';
    }
  };
  const runProcessor = async () => {
    if (stopped) return;
    try {
      await processor.executeOnce();
      state.lastProcessorSuccessAt = new Date().toISOString();
      state.lastErrorCode = null;
    } catch (error) {
      state.lastErrorCode = error instanceof Error ? error.name : 'PROCESSOR_FAILURE';
    }
  };
  void consumer.ensureGroup().then(runConsumer).catch((error: unknown) => {
    state.ready = false;
    state.lastErrorCode = error instanceof Error ? error.name : 'GROUP_CREATE_FAILURE';
  });
  const interval = setInterval(() => { void runProcessor(); }, 5_000);
  return {
    async stop() {
      stopped = true;
      clearInterval(interval);
      state.running = false;
      state.ready = false;
      await redis.quit();
    },
    health() { return { ...state }; },
  };
}

function required(value: string | undefined, name: string): string {
  const normalized = value?.trim() || '';
  if (!normalized) throw new Error(`${name} must be configured when Stream B is enabled`);
  return normalized;
}

function positiveInteger(raw: string | undefined, fallback: number, name: string): number {
  const value = raw === undefined ? fallback : Number(raw);
  if (!Number.isInteger(value) || value < 1) throw new Error(`${name} must be a positive integer`);
  return value;
}
