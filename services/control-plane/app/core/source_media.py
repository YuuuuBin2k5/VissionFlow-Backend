"""Source-media intake policy shared by URL and browser-upload adapters."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeSourceUrl(ValueError):
    pass


def validate_external_video_url(value: str, *, resolver=socket.getaddrinfo) -> str:
    """Reject SSRF-prone URLs before any importer performs an outbound request.

    An importer must call this again for every redirect target; DNS answers are
    checked rather than trusting hostname spelling alone.
    """
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise UnsafeSourceUrl("source_url must be a public http(s) URL without credentials")
    try:
        answers = resolver(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafeSourceUrl("source_url host cannot be resolved") from exc
    for answer in answers:
        address = ipaddress.ip_address(answer[4][0])
        if not address.is_global:
            raise UnsafeSourceUrl("source_url must not resolve to a private or reserved address")
    return parsed.geturl()
