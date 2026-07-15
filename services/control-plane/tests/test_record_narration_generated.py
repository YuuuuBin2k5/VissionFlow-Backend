import sys
import unittest
import uuid
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.application.record_narration_generated import (
    RecordNarrationGenerated,
    RecordNarrationGeneratedCommand,
    SceneCommandPayload,
    NarrationResultSummary,
)
from app.domain.workflow import WorkflowState


class FakeNarrationResultRepository:
    def __init__(self) -> None:
        self.commands: list[RecordNarrationGeneratedCommand] = []
        self.summary = NarrationResultSummary(
            workflow_run_id=uuid.uuid4(),
            state=WorkflowState.SCRIPTED,
            changed=True,
            version_id=uuid.uuid4(),
            version=1,
        )

    def record_narration_result(
        self, command: RecordNarrationGeneratedCommand
    ) -> NarrationResultSummary:
        self.commands.append(command)
        return self.summary


class RecordNarrationGeneratedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FakeNarrationResultRepository()
        self.use_case = RecordNarrationGenerated(self.repository)
        self.org_id = uuid.uuid4()
        self.run_id = uuid.uuid4()
        self.valid_scenes = [
            SceneCommandPayload("Narration 1", "Visual prompt 1", 5),
            SceneCommandPayload("Narration 2", "Visual prompt 2", 10),
            SceneCommandPayload("Narration 3", "Visual prompt 3", 15),
        ]
        self.valid_script = "This is a valid voice script that contains more than forty characters total."
        self.valid_idempotency = "valid_idempotency_key_16_chars"

    def test_executes_valid_command(self) -> None:
        command = RecordNarrationGeneratedCommand(
            organization_id=self.org_id,
            workflow_run_id=self.run_id,
            idempotency_key=self.valid_idempotency,
            script=self.valid_script,
            scenes=self.valid_scenes,
            source_metadata={"model": "gpt-4"},
        )
        result = self.use_case.execute(command)
        self.assertEqual(WorkflowState.SCRIPTED, result.state)
        self.assertTrue(result.changed)
        self.assertEqual([command], self.repository.commands)

    def test_rejects_blank_script(self) -> None:
        with self.assertRaisesRegex(ValueError, "script must not be blank"):
            self.use_case.execute(
                RecordNarrationGeneratedCommand(
                    organization_id=self.org_id,
                    workflow_run_id=self.run_id,
                    idempotency_key=self.valid_idempotency,
                    script="   ",
                    scenes=self.valid_scenes,
                    source_metadata={},
                )
            )

    def test_rejects_short_script(self) -> None:
        with self.assertRaisesRegex(ValueError, "script must be at least 40 characters"):
            self.use_case.execute(
                RecordNarrationGeneratedCommand(
                    organization_id=self.org_id,
                    workflow_run_id=self.run_id,
                    idempotency_key=self.valid_idempotency,
                    script="Too short script.",
                    scenes=self.valid_scenes,
                    source_metadata={},
                )
            )

    def test_rejects_empty_scenes(self) -> None:
        with self.assertRaisesRegex(ValueError, "scenes list must not be empty"):
            self.use_case.execute(
                RecordNarrationGeneratedCommand(
                    organization_id=self.org_id,
                    workflow_run_id=self.run_id,
                    idempotency_key=self.valid_idempotency,
                    script=self.valid_script,
                    scenes=[],
                    source_metadata={},
                )
            )

    def test_rejects_too_few_scenes(self) -> None:
        with self.assertRaisesRegex(ValueError, "scenes list must contain between 3 and 20 elements"):
            self.use_case.execute(
                RecordNarrationGeneratedCommand(
                    organization_id=self.org_id,
                    workflow_run_id=self.run_id,
                    idempotency_key=self.valid_idempotency,
                    script=self.valid_script,
                    scenes=self.valid_scenes[:2],
                    source_metadata={},
                )
            )

    def test_rejects_scene_blank_narration(self) -> None:
        invalid_scenes = [
            SceneCommandPayload("   ", "Visual prompt 1", 5),
            SceneCommandPayload("Narration 2", "Visual prompt 2", 10),
            SceneCommandPayload("Narration 3", "Visual prompt 3", 15),
        ]
        with self.assertRaisesRegex(ValueError, "scene 1: narration must not be blank"):
            self.use_case.execute(
                RecordNarrationGeneratedCommand(
                    organization_id=self.org_id,
                    workflow_run_id=self.run_id,
                    idempotency_key=self.valid_idempotency,
                    script=self.valid_script,
                    scenes=invalid_scenes,
                    source_metadata={},
                )
            )

    def test_rejects_scene_duration_out_of_bounds(self) -> None:
        invalid_scenes = [
            SceneCommandPayload("Narration 1", "Visual prompt 1", 0),
            SceneCommandPayload("Narration 2", "Visual prompt 2", 10),
            SceneCommandPayload("Narration 3", "Visual prompt 3", 15),
        ]
        with self.assertRaisesRegex(ValueError, "scene 1: duration_seconds must be between 1 and 90"):
            self.use_case.execute(
                RecordNarrationGeneratedCommand(
                    organization_id=self.org_id,
                    workflow_run_id=self.run_id,
                    idempotency_key=self.valid_idempotency,
                    script=self.valid_script,
                    scenes=invalid_scenes,
                    source_metadata={},
                )
            )

    def test_rejects_short_idempotency_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "idempotency_key must be at least 16 characters"):
            self.use_case.execute(
                RecordNarrationGeneratedCommand(
                    organization_id=self.org_id,
                    workflow_run_id=self.run_id,
                    idempotency_key="too_short",
                    script=self.valid_script,
                    scenes=self.valid_scenes,
                    source_metadata={},
                )
            )

    def test_rejects_invalid_trace_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "trace_id must be a 32-character"):
            self.use_case.execute(
                RecordNarrationGeneratedCommand(
                    organization_id=self.org_id,
                    workflow_run_id=self.run_id,
                    idempotency_key=self.valid_idempotency,
                    script=self.valid_script,
                    scenes=self.valid_scenes,
                    source_metadata={},
                    trace_id="invalid-trace-id",
                )
            )


if __name__ == "__main__":
    unittest.main()
