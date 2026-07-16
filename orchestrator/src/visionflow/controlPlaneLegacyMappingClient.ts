import { ClaimedLegacyOutboxRecord } from './legacyMappingOutboxRepository';

export class ControlPlaneRequestError extends Error {
  constructor(public readonly statusCode: number | null, message: string) {
    super(message);
  }
}

export interface ControlPlaneLegacyMappingClient {
  register(record: ClaimedLegacyOutboxRecord): Promise<void>;
}

export interface ControlPlaneLegacyMappingSettings {
  baseUrl: string;
  audience: string;
  clientId: string;
  clientSecret: string;
  source: string;
  timeoutMs: number;
}

export function controlPlaneLegacyMappingSettingsFromEnv(
  env: NodeJS.ProcessEnv = process.env,
): ControlPlaneLegacyMappingSettings {
  const baseUrl = required(env.VISIONFLOW_CONTROL_PLANE_BASE_URL, 'VISIONFLOW_CONTROL_PLANE_BASE_URL').replace(/\/$/, '');
  if (!baseUrl.startsWith('https://') && !(env.APP_ENV === 'local' && baseUrl.startsWith('http://localhost'))) {
    throw new Error('VISIONFLOW_CONTROL_PLANE_BASE_URL must use HTTPS outside local development');
  }
  const timeoutMs = Number(env.VISIONFLOW_CONTROL_PLANE_TIMEOUT_MS || '10000');
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1_000 || timeoutMs > 60_000) {
    throw new Error('VISIONFLOW_CONTROL_PLANE_TIMEOUT_MS must be between 1000 and 60000');
  }
  return {
    baseUrl,
    audience: required(env.VISIONFLOW_AUTH_AUDIENCE, 'VISIONFLOW_AUTH_AUDIENCE'),
    clientId: required(env.VISIONFLOW_LEGACY_MAPPING_CLIENT_ID, 'VISIONFLOW_LEGACY_MAPPING_CLIENT_ID'),
    clientSecret: required(env.VISIONFLOW_LEGACY_MAPPING_CLIENT_SECRET, 'VISIONFLOW_LEGACY_MAPPING_CLIENT_SECRET'),
    source: env.VISIONFLOW_LEGACY_SOURCE?.trim() || 'agentbot.orchestrator.v1',
    timeoutMs,
  };
}

export class HttpControlPlaneLegacyMappingClient implements ControlPlaneLegacyMappingClient {
  constructor(private readonly settings: ControlPlaneLegacyMappingSettings) {}

  async register(record: ClaimedLegacyOutboxRecord): Promise<void> {
    const token = await this.issueToken();
    let response: Response;
    try {
      response = await fetch(`${this.settings.baseUrl}/api/v1/workflows/${record.workflowRunId}/legacy-job-mapping`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
          'Idempotency-Key': record.idempotencyKey,
          'X-Request-ID': record.id.replace(/-/g, ''),
        },
        body: JSON.stringify({
          organization_id: record.organizationId,
          legacy_source: this.settings.source,
          legacy_job_id: String(record.legacyJobId),
        }),
        signal: AbortSignal.timeout(this.settings.timeoutMs),
      });
    } catch {
      throw new ControlPlaneRequestError(null, 'Control Plane network request failed');
    }
    if (response.status === 200 || response.status === 201) return;
    throw new ControlPlaneRequestError(response.status, `Control Plane mapping request failed with HTTP ${response.status}`);
  }

  private async issueToken(): Promise<string> {
    let response: Response;
    try {
      response = await fetch(`${this.settings.baseUrl}/api/v1/auth/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({
          grant_type: 'client_credentials',
          client_id: this.settings.clientId,
          client_secret: this.settings.clientSecret,
          audience: this.settings.audience,
          scope: 'workflow:legacy-mapping:register',
        }),
        signal: AbortSignal.timeout(this.settings.timeoutMs),
      });
    } catch {
      throw new ControlPlaneRequestError(null, 'Control Plane token request failed');
    }
    if (!response.ok) throw new ControlPlaneRequestError(response.status, 'Control Plane token request was rejected');
    const body = await response.json() as { access_token?: unknown };
    if (typeof body.access_token !== 'string' || !body.access_token) {
      throw new ControlPlaneRequestError(502, 'Control Plane token response was invalid');
    }
    return body.access_token;
  }
}

function required(value: string | undefined, name: string): string {
  const normalized = value?.trim() || '';
  if (!normalized) throw new Error(`${name} must be configured`);
  return normalized;
}
