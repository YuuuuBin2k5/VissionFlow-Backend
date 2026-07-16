import { createHmac, timingSafeEqual } from 'crypto';

export const LEGACY_JOB_REQUESTED_EVENT = 'visionflow.legacy_job.requested.v1';

export type StreamFields = Record<string, string>;

export interface LegacyJobRequested {
  eventId: string;
  sourceCommandId: string;
  organizationId: string;
  workflowRunId: string;
  traceId: string;
  intake: {
    title: string;
    brief: string;
    formatProfile: string;
    timezone: string;
    inputPayload: Record<string, unknown>;
    promptManifest: Record<string, unknown>;
  };
  rawPayload: Record<string, unknown>;
}

export interface IntakeHmacKeys {
  current: { keyId: string; key: string };
  previous?: { keyId: string; key: string };
}

export class IntakeContractError extends Error {
  constructor(public readonly code: string, message: string) {
    super(message);
  }
}

export function intakeHmacKeysFromEnv(env: NodeJS.ProcessEnv = process.env): IntakeHmacKeys {
  const currentKeyId = env.VISIONFLOW_INTAKE_HMAC_KEY_ID?.trim() || '';
  const currentKey = env.VISIONFLOW_INTAKE_HMAC_KEY?.trim() || '';
  if (!currentKeyId || !currentKey) {
    throw new IntakeContractError('INTAKE_HMAC_NOT_CONFIGURED', 'Current intake HMAC key is not configured');
  }
  const previousKeyId = env.VISIONFLOW_INTAKE_HMAC_PREV_KEY_ID?.trim() || '';
  const previousKey = env.VISIONFLOW_INTAKE_HMAC_KEY_PREV?.trim() || '';
  if (Boolean(previousKeyId) !== Boolean(previousKey)) {
    throw new IntakeContractError('INTAKE_HMAC_ROTATION_INVALID', 'Previous HMAC key ID and key must be configured together');
  }
  return {
    current: { keyId: currentKeyId, key: currentKey },
    ...(previousKey ? { previous: { keyId: previousKeyId, key: previousKey } } : {}),
  };
}

export function parseAndVerifyLegacyJobRequest(fields: StreamFields, keys: IntakeHmacKeys): LegacyJobRequested {
  if (fields.event_type !== LEGACY_JOB_REQUESTED_EVENT) {
    throw new IntakeContractError('UNSUPPORTED_EVENT_TYPE', 'Stream event type is not a legacy job request');
  }
  const payload = parseObject(fields.payload, 'payload');
  const signatureKeyId = requiredString(fields.signature_key_id, 'signature_key_id');
  const signature = requiredString(fields.signature, 'signature');
  const signingKey = signatureKeyId === keys.current.keyId
    ? keys.current.key
    : signatureKeyId === keys.previous?.keyId
      ? keys.previous.key
      : undefined;
  if (!signingKey) {
    throw new IntakeContractError('UNKNOWN_SIGNATURE_KEY', 'Signature key ID is not accepted');
  }

  const envelope = {
    event_id: requiredUuid(fields.event_id, 'event_id'),
    event_type: fields.event_type,
    aggregate_type: requiredString(fields.aggregate_type, 'aggregate_type'),
    aggregate_id: requiredUuid(fields.aggregate_id, 'aggregate_id'),
    trace_id: requiredTraceId(fields.trace_id),
    payload,
  };
  const expected = createHmac('sha256', signingKey).update(canonicalBytes(envelope)).digest('hex');
  const supplied = Buffer.from(signature, 'hex');
  const expectedBytes = Buffer.from(expected, 'hex');
  if (supplied.length !== expectedBytes.length || !timingSafeEqual(supplied, expectedBytes)) {
    throw new IntakeContractError('INVALID_SIGNATURE', 'Stream event signature is invalid');
  }
  if (payload.event_version !== 1 || payload.event_id !== envelope.event_id) {
    throw new IntakeContractError('INVALID_EVENT_PAYLOAD', 'Event payload version or ID is invalid');
  }
  const intake = parseObject(payload.intake, 'intake');
  return {
    eventId: envelope.event_id,
    sourceCommandId: requiredUuid(payload.source_command_id, 'source_command_id'),
    organizationId: requiredUuid(payload.organization_id, 'organization_id'),
    workflowRunId: requiredUuid(payload.workflow_run_id, 'workflow_run_id'),
    traceId: envelope.trace_id,
    intake: {
      title: requiredString(intake.title, 'intake.title'),
      brief: requiredString(intake.brief, 'intake.brief'),
      formatProfile: requiredString(intake.format_profile, 'intake.format_profile'),
      timezone: requiredString(intake.timezone, 'intake.timezone'),
      inputPayload: parseObject(intake.input_payload, 'intake.input_payload'),
      promptManifest: parseObject(intake.prompt_manifest, 'intake.prompt_manifest'),
    },
    rawPayload: payload,
  };
}

export function canonicalBytes(envelope: Record<string, unknown>): string {
  return JSON.stringify(sortForCanonicalJson(envelope));
}

function sortForCanonicalJson(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortForCanonicalJson);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, child]) => [key, sortForCanonicalJson(child)]),
    );
  }
  return value;
}

function parseObject(value: unknown, name: string): Record<string, unknown> {
  let parsed: unknown;
  try {
    parsed = typeof value === 'string' ? JSON.parse(value) : value;
  } catch {
    throw new IntakeContractError('INVALID_JSON', `${name} is not valid JSON`);
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new IntakeContractError('INVALID_OBJECT', `${name} must be an object`);
  }
  return parsed as Record<string, unknown>;
}

function requiredString(value: unknown, name: string): string {
  if (typeof value !== 'string' || !value.trim()) {
    throw new IntakeContractError('MISSING_FIELD', `${name} is required`);
  }
  return value;
}

function requiredUuid(value: unknown, name: string): string {
  const normalized = requiredString(value, name).toLowerCase();
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(normalized)) {
    throw new IntakeContractError('INVALID_IDENTIFIER', `${name} must be a UUID`);
  }
  return normalized;
}

function requiredTraceId(value: unknown): string {
  const normalized = requiredString(value, 'trace_id').toLowerCase();
  if (!/^[0-9a-f]{32}$/.test(normalized)) {
    throw new IntakeContractError('INVALID_TRACE_ID', 'trace_id must be 32 hexadecimal characters');
  }
  return normalized;
}
