import sys
import unittest
import uuid
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.application.prompt_registry import (  # noqa: E402
    CreatePromptTemplateCommand,
    PromptRegistry,
    PromptTemplateSummary,
)


class FakePromptRegistryRepository:
    def __init__(self) -> None:
        self.created_commands: list[CreatePromptTemplateCommand] = []

    def create_template(self, command: CreatePromptTemplateCommand) -> PromptTemplateSummary:
        self.created_commands.append(command)
        return PromptTemplateSummary(uuid.uuid4(), command.prompt_key, command.name, command.description, None)


class PromptRegistryTests(unittest.TestCase):
    def _command(self, **overrides: object) -> CreatePromptTemplateCommand:
        values: dict[str, object] = {
            "organization_id": uuid.uuid4(),
            "prompt_key": "short-form.script",
            "name": "Short-form Script",
            "description": "Produces a concise voice-over script for one vertical video.",
            "content": "Create a short script from {{brief}}.",
            "actor_subject": "oidc|visionflow-admin",
        }
        values.update(overrides)
        return CreatePromptTemplateCommand(**values)  # type: ignore[arg-type]

    def test_creates_a_draft_template_by_default(self) -> None:
        repository = FakePromptRegistryRepository()
        result = PromptRegistry(repository).create_template(self._command())

        self.assertIsNone(result.production_version)
        self.assertEqual(1, len(repository.created_commands))

    def test_rejects_non_canonical_prompt_key(self) -> None:
        repository = FakePromptRegistryRepository()

        with self.assertRaisesRegex(ValueError, "prompt_key"):
            PromptRegistry(repository).create_template(self._command(prompt_key="Short Form Script"))
        self.assertEqual([], repository.created_commands)

    def test_allows_explicit_first_version_promotion(self) -> None:
        repository = FakePromptRegistryRepository()
        result = PromptRegistry(repository).create_template(self._command(promote_immediately=True))

        self.assertEqual("short-form.script", result.prompt_key)
        self.assertTrue(repository.created_commands[0].promote_immediately)
