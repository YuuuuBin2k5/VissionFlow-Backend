from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SaveCreativeDraftCommand:
    organization_id: uuid.UUID
    workflow_run_id: uuid.UUID
    creative_draft: dict[str, object]


class CreativeDraftRepository(Protocol):
    def save_creative_draft(self, command: SaveCreativeDraftCommand) -> None: ...


class SaveCreativeDraft:
    """Operator-owned draft boundary; workers never mutate this input contract."""

    def __init__(self, repository: CreativeDraftRepository) -> None:
        self._repository = repository

    def execute(self, command: SaveCreativeDraftCommand) -> None:
        self._repository.save_creative_draft(command)
