/*
 * Release regression gate for the isolated Stream B image. The image must be
 * built before this script runs. It does not require MySQL, Redis, or Control
 * Plane access: the second case deliberately uses an unreachable Redis URL.
 */
const { execFileSync } = require('node:child_process');

const image = process.argv[2] || 'visionflow-legacy-intake:release-check';
const suffix = `${process.pid}-${Date.now()}`;

function docker(args, options = {}) {
  return execFileSync('docker', args, { encoding: 'utf8', ...options }).trim();
}

async function waitForHealth(port, expectedStatus, expectedFields) {
  const url = `http://127.0.0.1:${port}/health/visionflow/legacy-intake`;
  const deadline = Date.now() + 25_000;
  let lastError = 'health endpoint did not respond';
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(2_000) });
      const body = await response.json();
      if (response.status !== expectedStatus) {
        lastError = `expected HTTP ${expectedStatus}, got ${response.status}: ${JSON.stringify(body)}`;
      } else if (Object.entries(expectedFields).every(([key, value]) => body[key] === value)) {
        return;
      } else {
        lastError = `unexpected health body: ${JSON.stringify(body)}`;
      }
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
  throw new Error(lastError);
}

function mappedPort(containerName) {
  const output = docker(['port', containerName, '3000/tcp']);
  const first = output.split(/\r?\n/)[0];
  const match = first.match(/:(\d+)$/);
  if (!match) throw new Error(`Could not determine mapped health port: ${output}`);
  return Number(match[1]);
}

async function verifyCase(name, env, expectedStatus, expectedFields) {
  const containerName = `visionflow-intake-${name}-${suffix}`;
  try {
    docker(['run', '-d', '--name', containerName, '-p', '0:3000', ...env, image]);
    await waitForHealth(mappedPort(containerName), expectedStatus, expectedFields);
    console.log(`[OK] ${name}`);
  } finally {
    try { docker(['rm', '-f', containerName], { stdio: 'ignore' }); } catch {}
  }
}

(async () => {
  await verifyCase('dormant', [
    '-e', 'PORT=3000',
    '-e', 'VISIONFLOW_LEGACY_INTAKE_ENABLED=false',
  ], 200, { enabled: false, running: false, ready: true });

  await verifyCase('redis-unready', [
    '-e', 'PORT=3000',
    '-e', 'VISIONFLOW_LEGACY_INTAKE_ENABLED=true',
    '-e', 'REDIS_URL=redis://127.0.0.1:6399',
    '-e', 'VISIONFLOW_INTAKE_HMAC_KEY_ID=release-check',
    '-e', 'VISIONFLOW_INTAKE_HMAC_KEY=release-check-secret',
    '-e', 'VISIONFLOW_LEGACY_MAPPING_CLIENT_ID=release-check-client',
    '-e', 'VISIONFLOW_LEGACY_MAPPING_CLIENT_SECRET=release-check-secret-two',
    '-e', 'VISIONFLOW_CONTROL_PLANE_BASE_URL=https://control-plane.invalid',
    '-e', 'VISIONFLOW_AUTH_AUDIENCE=visionflow-control-plane',
  ], 503, { enabled: true, running: true, ready: false });
})().catch((error) => {
  console.error(`VisionFlow legacy intake container verification failed: ${error.message}`);
  process.exit(1);
});
