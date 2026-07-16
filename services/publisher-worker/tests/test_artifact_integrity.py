import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


WORKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKER_ROOT))

import main


class _Response:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, _chunk_size: int):
        return iter(self._chunks)


class _Session:
    def __init__(self, chunks: list[bytes]) -> None:
        self._response = _Response(chunks)

    def get(self, *_args, **_kwargs):
        return self._response


class PublisherArtifactIntegrityTests(unittest.TestCase):
    def _manifest(self, content: bytes) -> dict[str, object]:
        return {
            "artifact_download_url": "https://object.example/final.mp4",
            "artifact_byte_size": len(content),
            "artifact_checksum_sha256": hashlib.sha256(content).hexdigest(),
        }

    def test_accepts_download_matching_the_approved_artifact(self) -> None:
        content = b"approved video bytes"
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "final.mp4"
            main._download_verified_artifact(_Session([content[:8], content[8:]]), self._manifest(content), destination)
            self.assertEqual(content, destination.read_bytes())

    def test_rejects_download_with_a_checksum_mismatch(self) -> None:
        expected = b"approved video bytes"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "checksum"):
                main._download_verified_artifact(_Session([b"x" * len(expected)]), self._manifest(expected), Path(directory) / "final.mp4")
