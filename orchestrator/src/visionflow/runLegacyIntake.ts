import express from 'express';
import dotenv from 'dotenv';
import { attachLegacyIntakeRuntime } from './legacyIntakeStartup';

dotenv.config();

const app = express();
const runtime = attachLegacyIntakeRuntime(app);
const port = Number(process.env.VISIONFLOW_LEGACY_INTAKE_PORT || process.env.PORT || '3100');

if (!Number.isInteger(port) || port < 1 || port > 65_535) {
  throw new Error('VISIONFLOW_LEGACY_INTAKE_PORT must be a valid TCP port');
}

const server = app.listen(port, () => {
  console.log(`[VisionFlow Legacy Intake] health endpoint listening on port ${port}`);
});

async function shutdown(signal: 'SIGINT' | 'SIGTERM'): Promise<void> {
  server.close();
  await runtime?.stop();
  process.exit(0);
}

process.once('SIGINT', () => { void shutdown('SIGINT'); });
process.once('SIGTERM', () => { void shutdown('SIGTERM'); });
