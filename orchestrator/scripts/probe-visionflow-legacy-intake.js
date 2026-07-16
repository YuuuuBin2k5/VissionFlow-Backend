const baseUrl = (process.env.VISIONFLOW_LEGACY_INTAKE_BASE_URL || '').replace(/\/$/, '');
if (!baseUrl.startsWith('https://') && !baseUrl.startsWith('http://localhost')) {
  console.error('Set VISIONFLOW_LEGACY_INTAKE_BASE_URL to the deployed HTTPS service URL.');
  process.exit(1);
}

(async () => {
  const response = await fetch(`${baseUrl}/health/visionflow/legacy-intake`, {
    signal: AbortSignal.timeout(10_000),
  });
  const health = await response.json();
  if (!response.ok || typeof health !== 'object' || health === null) {
    throw new Error(`Health endpoint failed with HTTP ${response.status}`);
  }
  console.log(JSON.stringify(health));
  if (process.env.VISIONFLOW_EXPECT_LEGACY_INTAKE_ENABLED === 'true' && health.running !== true) {
    throw new Error('Stream B was expected to be running but is not healthy.');
  }
})().catch((error) => {
  console.error(`VisionFlow legacy intake probe failed: ${error.message}`);
  process.exit(1);
});
