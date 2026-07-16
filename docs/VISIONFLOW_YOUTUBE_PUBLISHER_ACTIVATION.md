# VisionFlow YouTube Publisher Activation

This document is the mandatory activation gate for the future VisionFlow
YouTube publisher adapter. It does **not** authorize use of the legacy MySQL
or browser-automation publisher.

## 1. Provider prerequisites

Create a Google Cloud project owned by the VisionFlow production organization.
Enable **YouTube Data API v3**, configure the OAuth consent screen, and create
a **Web application** OAuth client. Register the exact production callback:

```text
https://<control-plane-host>/api/v1/integrations/youtube/oauth/callback
```

The adapter must request only:

```text
https://www.googleapis.com/auth/youtube.upload
```

Never request browser cookies, account passwords, or broader Google scopes.
The OAuth `state` value must be cryptographically random, one-time, bound to
the authenticated VisionFlow organization and operator, and expire within ten
minutes. Store refresh tokens encrypted at rest, never in Vercel or browser
storage.

## 2. Render configuration

Set these **Render secrets only** on the future `visionflow-publisher` worker;
do not expose them to the Console:

```text
VISIONFLOW_YOUTUBE_CLIENT_ID=<google-oauth-client-id>
VISIONFLOW_YOUTUBE_CLIENT_SECRET=<google-oauth-client-secret>
VISIONFLOW_YOUTUBE_REDIRECT_URI=https://<control-plane-host>/api/v1/integrations/youtube/oauth/callback
VISIONFLOW_YOUTUBE_OAUTH_STATE_KEY=<32-byte-base64url-secret>
VISIONFLOW_PUBLISHER_CLIENT_ID=visionflow-publisher
VISIONFLOW_PUBLISHER_CLIENT_SECRET=<control-plane-service-client-secret>
```

Register `visionflow-publisher` in `VISIONFLOW_SERVICE_CLIENTS_JSON` with a
dedicated subject and only the scopes required to read an execution context and
advance `PUBLISHING -> PUBLISHED` / failure states. Its service membership must
be constrained to the intended organization.

## 3. Event contract

The publisher consumes only committed Redis Stream events where:

```json
{
  "event_type": "visionflow.workflow_run.state_changed.v1",
  "payload": {
    "workflow_run_id": "<uuid>",
    "from_state": "APPROVED",
    "to_state": "PUBLISHING"
  }
}
```

It must deduplicate on `event_id`, fetch the artifact through a Control Plane
authorized API, and reject any object key other than:

```text
visionflow/<workflow-run-id>/exports/final.mp4
```

The upload must use YouTube `videos.insert` with resumable media upload. The
initial production default is `private`; public/unlisted scheduling is enabled
only after the Google project has completed the required YouTube API audit.

## 4. Completion and failure rules

| Provider outcome | Control Plane transition | Required output |
| --- | --- | --- |
| Upload accepted, processing pending | remain `PUBLISHING` | YouTube video ID, processing status, provider trace |
| Processing succeeded | `PUBLISHING -> PUBLISHED` | video ID, canonical URL, privacy status, published timestamp |
| Retryable network/5xx/quota failure | `PUBLISHING -> RETRY_SCHEDULED` | safe error code, attempt number, next retry |
| Invalid OAuth grant or policy rejection | `PUBLISHING -> FAILED` | safe provider error code; no token/body in logs |

The adapter must ACK the Redis message only after it has durably recorded a
Control Plane outcome. It must use bounded exponential retry and a DLQ for
poison events. A redelivery may never create a second YouTube upload for the
same workflow run; provider request/idempotency evidence is persisted before
each attempt.

## 5. Production acceptance

1. Connect a dedicated test channel through OAuth; verify state/PKCE and token
   storage without exposing a refresh token.
2. Create and approve one short video in VisionFlow.
3. Create the explicit publish handoff in **Distribution**.
4. Verify exactly one Redis delivery and one private YouTube upload.
5. Verify the adapter records `PUBLISHED` only after processing succeeds and
   the Control Plane audit contains the provider URL.
6. Replay the same Redis event; verify no second upload occurs.

## Official references

- [Google OAuth 2.0 for web server applications](https://developers.google.com/identity/protocols/oauth2/web-server)
- [YouTube `videos.insert`](https://developers.google.com/youtube/v3/docs/videos/insert)
- [YouTube upload and processing guidance](https://developers.google.com/youtube/v3/guides/implementation/videos)
