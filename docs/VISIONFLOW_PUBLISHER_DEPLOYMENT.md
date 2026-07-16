# VisionFlow YouTube Publisher deployment

The free Render Blueprint intentionally runs only the Control Plane. For the no-cost profile, GitHub Actions runs relay and publisher work every ten minutes or manually. Do not import `render.staging.yaml` unless you later choose paid workers.

Required GitHub repository secrets:

- `VISIONFLOW_DATABASE_URL`: the same TLS Neon URL used by the Control Plane.
- `VISIONFLOW_REDIS_URL`: durable TLS Redis endpoint shared with the Control Plane.
- `VISIONFLOW_CONTROL_PLANE_URL`: `https://<control-plane>/api/v1`.
- `VISIONFLOW_AUTH_AUDIENCE`: `visionflow-control-plane`.
- `VISIONFLOW_PUBLISHER_CLIENT_ID` and `VISIONFLOW_PUBLISHER_CLIENT_SECRET`: a new, dedicated client-credentials pair.
- `VISIONFLOW_PUBLISHER_SUBJECT` and `VISIONFLOW_PUBLISHER_WORKER_SUBJECT`: both `service|visionflow-publisher`.

The same client ID, secret, and subject must be registered as `VISIONFLOW_PUBLISHER_*` on the Control Plane. The service token carries only `publish:execute`.

The consumer automatically reclaims unacknowledged messages after 60 seconds. It retries a failed event up to five times and then writes the original envelope and error class to `visionflow.publisher-dlq.v1`. Tune this only with explicit operational ownership using `VISIONFLOW_PUBLISHER_CLAIM_IDLE_MS`, `VISIONFLOW_PUBLISHER_MAX_ATTEMPTS`, and `VISIONFLOW_PUBLISHER_DLQ_STREAM`.

Before enabling workers, run `python -m alembic upgrade head` once against Neon. Verify Control Plane health, then publish one approved private test Short. A successful execution ends with workflow state `PUBLISHED` and a YouTube watch URL.
