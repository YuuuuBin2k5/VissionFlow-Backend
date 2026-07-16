/* Pre-deploy validation only: no Redis, database, or Control Plane calls. */
const requiredWhenEnabled = [
  'REDIS_URL',
  'VISIONFLOW_INTAKE_HMAC_KEY_ID',
  'VISIONFLOW_INTAKE_HMAC_KEY',
  'VISIONFLOW_LEGACY_MAPPING_CLIENT_ID',
  'VISIONFLOW_LEGACY_MAPPING_CLIENT_SECRET',
  'VISIONFLOW_LEGACY_MAPPING_SUBJECT',
  'VISIONFLOW_CONTROL_PLANE_BASE_URL',
  'VISIONFLOW_AUTH_AUDIENCE',
];

const enabled = process.env.VISIONFLOW_LEGACY_INTAKE_ENABLED === 'true';
if (!enabled) {
  console.log('VisionFlow Stream B is disabled; no runtime configuration is required.');
  process.exit(0);
}

const missing = requiredWhenEnabled.filter((name) => !process.env[name]?.trim());
if (missing.length) fail(`Missing required settings: ${missing.join(', ')}`);

const previousKeyId = process.env.VISIONFLOW_INTAKE_HMAC_PREV_KEY_ID?.trim() || '';
const previousKey = process.env.VISIONFLOW_INTAKE_HMAC_KEY_PREV?.trim() || '';
if (Boolean(previousKeyId) !== Boolean(previousKey)) {
  fail('VISIONFLOW_INTAKE_HMAC_PREV_KEY_ID and VISIONFLOW_INTAKE_HMAC_KEY_PREV must be configured together.');
}
if (previousKeyId && previousKeyId === process.env.VISIONFLOW_INTAKE_HMAC_KEY_ID?.trim()) {
  fail('Current and previous HMAC key IDs must differ.');
}
if (process.env.VISIONFLOW_LEGACY_MAPPING_CLIENT_SECRET === process.env.VISIONFLOW_WORKER_CLIENT_SECRET) {
  fail('Legacy mapping and narration worker client secrets must differ.');
}
if (process.env.VISIONFLOW_LEGACY_MAPPING_SUBJECT === process.env.VISIONFLOW_WORKER_SUBJECT) {
  fail('Legacy mapping and narration worker subjects must differ.');
}

const baseUrl = process.env.VISIONFLOW_CONTROL_PLANE_BASE_URL.trim();
if (!baseUrl.startsWith('https://') && !(process.env.APP_ENV === 'local' && baseUrl.startsWith('http://localhost'))) {
  fail('VISIONFLOW_CONTROL_PLANE_BASE_URL must use HTTPS outside local development.');
}
console.log('VisionFlow Stream B configuration is structurally valid.');

function fail(message) {
  console.error(`VisionFlow Stream B configuration error: ${message}`);
  process.exit(1);
}
