from __future__ import annotations

import typing
from typing import Protocol, Tuple

class CreativePlanningProvider(Protocol):
    def generate_proposal(
        self,
        *,
        prompt: str,
        history: list[dict[str, str]],  # List of {"actor": "user"|"assistant", "content": "..."}
        creation_spec: dict,            # Canonical creation spec
        planner_prompt_template: str,
        director_prompt_template: str,
        provider_credential_secret: str,
        model_name: str | None = None,
    ) -> Tuple[str, list[dict]]:
        """Calls Gemini API to generate the assistant response and proposal structure.

        Returns:
            Tuple[assistant_message, list_of_scenes]
        """
        ...
