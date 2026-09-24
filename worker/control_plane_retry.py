"""Shared, non-blocking control-plane admission and safe HTTP diagnostics."""
from __future__ import annotations

import math
import random
import re
import time
from datetime import timezone
from email.utils import parsedate_to_datetime


class ControlPlaneError(RuntimeError):
    def __init__(self, category, *, status=None, retry_after=0.0, cf_ray=None, deferred=False):
        super().__init__(category)
        self.code = self.category = category
        self.status = status
        self.retry_after = retry_after
        self.cf_ray = cf_ray
        self.deferred = deferred
        self.retryable = category in {
            "RATE_LIMITED", "EDGE_CHALLENGE", "TRANSIENT_NETWORK", "SERVER_UNAVAILABLE",
        }


def retry_delay(headers, wall_time=time.time):
    """Retry-After seconds/date; standardized reset delta and legacy reset epoch."""
    headers = {str(k).lower(): str(v) for k, v in headers.items()}
    delays = [0.0]
    raw = headers.get("retry-after", "")
    try:
        delays.append(float(raw))
    except ValueError:
        try:
            stamp = parsedate_to_datetime(raw)
            delays.append(stamp.replace(tzinfo=stamp.tzinfo or timezone.utc).timestamp() - wall_time())
        except (ValueError, TypeError, OverflowError):
            pass
    for key in ("ratelimit-reset", "x-ratelimit-reset"):
        try:
            value = float(headers[key])
            delays.append(value - wall_time() if key.startswith("x-") else value)
        except (KeyError, ValueError):
            pass
    return max(v for v in delays if math.isfinite(v))


def classify(response, wall_time=time.time):
    status = response.status_code
    headers = {str(k).lower(): str(v) for k, v in getattr(response, "headers", {}).items()}
    body = getattr(response, "text", "")[:4096].lower()
    challenge = status in (403, 429) and (
        headers.get("cf-mitigated") == "challenge" or
        ("text/html" in headers.get("content-type", "") and
         ("just a moment" in body or "cloudflare" in body)))
    if challenge:
        category = "EDGE_CHALLENGE"
    elif status in (401, 403):
        category = "AUTH_FAILURE"
    elif status == 429:
        category = "RATE_LIMITED"
    elif status >= 500:
        category = "SERVER_UNAVAILABLE"
    elif status in (404, 409, 410, 422):
        category = "JOB_REJECTED"
    else:
        category = "PERMANENT_REQUEST_ERROR"
    ray = headers.get("cf-ray", "")
    ray = ray if re.fullmatch(r"[A-Za-z0-9-]{1,100}", ray) else None
    return ControlPlaneError(category, status=status, retry_after=retry_delay(headers, wall_time), cf_ray=ray)


class RetryPolicy:
    """Called under the client's lock, including HTTP I/O: one half-open probe."""
    def __init__(self, *, clock=time.monotonic, jitter=random.random, base=1, maximum=60,
                 cooldown=30, cooldown_max=120, threshold=3):
        self.clock, self.jitter = clock, jitter
        self.base, self.maximum = base, maximum
        self.cooldown, self.cooldown_max, self.threshold = cooldown, cooldown_max, threshold
        self.failures = self.rate_failures = 0
        self.until = 0.0
        self.circuit = "CLOSED"
        self.health = "DEGRADED"
        self.last_category = "TRANSIENT_NETWORK"

    def remaining(self):
        return max(0.0, self.until - self.clock())

    def admit(self):
        if self.health == "AUTH_FAILED":
            raise ControlPlaneError("AUTH_FAILURE", deferred=True)
        if self.remaining():
            raise ControlPlaneError(self.last_category, retry_after=self.remaining(), deferred=True)
        if self.circuit == "OPEN":
            self.circuit = "HALF_OPEN"

    def success(self):
        self.failures = self.rate_failures = 0
        self.until = 0.0
        self.circuit, self.health = "CLOSED", "ONLINE"

    def failure(self, error):
        self.last_category = error.category
        if error.category == "AUTH_FAILURE":
            self.health = "AUTH_FAILED"
            return
        self.failures += 1
        limited = error.category in ("RATE_LIMITED", "EDGE_CHALLENGE")
        self.rate_failures = self.rate_failures + 1 if limited else 0
        delay = min(self.maximum, self.base * 2 ** min(self.failures - 1, 20))
        if limited:
            delay = max(delay, min(self.cooldown_max, self.cooldown * 2 ** min(self.rate_failures - 1, 10)))
        if self.rate_failures >= self.threshold or self.circuit == "HALF_OPEN":
            self.circuit = "OPEN"
            delay = max(delay, min(self.cooldown_max, self.cooldown * 2 ** min(self.failures - 1, 10)))
        # Positive jitter never shortens the server's required quiet period.
        delay = max(error.retry_after, delay) + self.jitter() * min(5, delay * .2)
        self.until = max(self.until, self.clock() + delay)
        error.retry_after = self.remaining()
        self.health = "RATE_LIMITED" if limited else "BACKEND_UNAVAILABLE" if error.retryable else "DEGRADED"
