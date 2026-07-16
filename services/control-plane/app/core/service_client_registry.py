"""Environment-backed registry for narrowly scoped machine identities.

Service credentials remain in the deployment secret manager.  The registry is
an adapter over environment configuration, not a database-backed identity
store, so credential rotation has a small and explicit operational surface.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.core.config import ConfigurationError


@dataclass(frozen=True)
class ServiceClient:
    client_id: str
    client_secret: str
    subject: str
    allowed_scopes: frozenset[str]


class ServiceClientRegistry:
    """Resolve configured OAuth client-credentials principals by client id.

    The narration worker remains required for backwards compatibility.  The
    legacy mapping client is optional until Stream B is rolled out, but its
    three settings must be configured as an all-or-nothing unit.
    """

    def __init__(self, clients: tuple[ServiceClient, ...]) -> None:
        by_client_id = {client.client_id: client for client in clients}
        if len(by_client_id) != len(clients):
            raise ConfigurationError("service client IDs must be unique")
        self._by_client_id = by_client_id

    @classmethod
    def from_env(cls) -> "ServiceClientRegistry":
        clients = [
            _client_from_env(
                "VISIONFLOW_WORKER",
                allowed_scopes=frozenset({"workflow:narration:complete", "credential:resolve"}),
                required=True,
            )
        ]
        mapping_client = _client_from_env(
            "VISIONFLOW_LEGACY_MAPPING",
            allowed_scopes=frozenset({"workflow:legacy-mapping:register"}),
            required=False,
        )
        if mapping_client is not None:
            clients.append(mapping_client)
        publisher_client = _client_from_env(
            "VISIONFLOW_PUBLISHER",
            allowed_scopes=frozenset({"publish:execute"}),
            required=False,
        )
        if publisher_client is not None:
            clients.append(publisher_client)
        return cls(tuple(clients))

    def get(self, client_id: str) -> ServiceClient | None:
        return self._by_client_id.get(client_id)


def _client_from_env(
    prefix: str, *, allowed_scopes: frozenset[str], required: bool
) -> ServiceClient | None:
    names = (f"{prefix}_CLIENT_ID", f"{prefix}_CLIENT_SECRET", f"{prefix}_SUBJECT")
    values = tuple((os.getenv(name) or "").strip() for name in names)
    configured = tuple(bool(value) for value in values)
    if not any(configured):
        if required:
            raise ConfigurationError(f"{names[0]} must be configured")
        return None
    if not all(configured):
        raise ConfigurationError(f"{prefix} service client settings must be configured together")
    return ServiceClient(
        client_id=values[0],
        client_secret=values[1],
        subject=values[2],
        allowed_scopes=allowed_scopes,
    )
