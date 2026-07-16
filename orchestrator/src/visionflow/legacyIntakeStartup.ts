import type { Express } from 'express';
import { LegacyIntakeRuntime, startLegacyIntakeRuntime } from './legacyIntakeRuntime';

/**
 * Composition-root adapter kept separate from the currently dirty main.ts.
 * The activation commit imports this one function after its review gate.
 */
export function attachLegacyIntakeRuntime(app: Express): LegacyIntakeRuntime | null {
  const runtime = startLegacyIntakeRuntime();
  app.get('/health/visionflow/legacy-intake', (_request, response) => {
    const health = runtime?.health() || {
      enabled: false,
      running: false,
      lastConsumerSuccessAt: null,
      lastProcessorSuccessAt: null,
      lastErrorCode: null,
    };
    response.status(health.running || !health.enabled ? 200 : 503).json(health);
  });
  return runtime;
}
