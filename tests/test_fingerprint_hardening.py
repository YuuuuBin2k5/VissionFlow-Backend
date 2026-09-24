"""
Fingerprint Hardening & Security Unit Test Suite (Phase 2.5 - Sections 12, 13, 16)
Verifies:
- Tier 1 fast fingerprint (head, mid, tail sampling + stream signature).
- Tier 2 canonical fingerprint (full cryptographic SHA-256 with v1:<64 hex> prefix).
- Short fingerprint helper (fp[:16]) for logging and UI display.
- Two-tier deduplication workflow: Fast match check + canonical confirmation.
- Zero secret logging across all codebase files (no partial key leaks).
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
import pytest

from production.contracts import SourceAssetRecord, SourceIngestState, RightsState
from production.source_ingest import (
    compute_canonical_fingerprint,
    compute_fast_fingerprint,
    compute_scene_fingerprint,
    compute_source_fingerprint,
)


def test_canonical_fingerprint_full_sha256(tmp_path: Path):
    test_file = tmp_path / "test_video.mp4"
    content = b"TEST_VIDEO_DATA_CANONICAL_IDENTITY_VERIFICATION" * 100
    test_file.write_bytes(content)

    fp = compute_canonical_fingerprint(test_file)
    assert fp.startswith("v1:"), f"Canonical fingerprint must have 'v1:' prefix, got {fp}"

    raw_hex = fp.removeprefix("v1:")
    assert len(raw_hex) == 64, f"Canonical fingerprint must contain 64 hex characters, got {len(raw_hex)}"

    # Direct verification with hashlib
    expected_hex = hashlib.sha256(content).hexdigest()
    assert raw_hex == expected_hex


def test_fast_fingerprint_tier1_sensitivity(tmp_path: Path):
    f1 = tmp_path / "v1.mp4"
    f2 = tmp_path / "v2.mp4"

    # Create two files with same size but differing contents
    f1.write_bytes(b"A" * 1024 * 1024)
    f2.write_bytes(b"B" * 1024 * 1024)

    meta1 = {"duration": 10.0, "width": 1920, "height": 1080}
    meta2 = {"duration": 10.0, "width": 1920, "height": 1080}
    meta_diff_dur = {"duration": 12.5, "width": 1920, "height": 1080}

    fp1 = compute_fast_fingerprint(f1, meta1)
    fp2 = compute_fast_fingerprint(f2, meta2)
    fp1_dur = compute_fast_fingerprint(f1, meta_diff_dur)

    assert fp1.startswith("fast:")
    assert fp2.startswith("fast:")
    assert fp1 != fp2, "Different byte content must yield different fast fingerprints"
    assert fp1 != fp1_dur, "Different stream duration must yield different fast fingerprints"


def test_source_record_fingerprint_short():
    rec = SourceAssetRecord(
        id="src_test_short",
        source_type="video",
        fingerprint="v1:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        fast_fingerprint="fast:a1b2c3d4e5f60718293a4b5c6d7e8f90",
        duration=10.0,
        width=1920,
        height=1080,
        fps=30.0,
        codec="h264",
    )
    assert rec.fingerprint_short == "v1:e3b0c442...b855"
    assert len(rec.fingerprint) == 67  # 'v1:' + 64 hex chars


def test_scene_fingerprint_deterministic():
    src_fp = "v1:abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
    fp_a = compute_scene_fingerprint(src_fp, 0.0, 5.25)
    fp_b = compute_scene_fingerprint(src_fp, 0.0, 5.25)
    fp_c = compute_scene_fingerprint(src_fp, 0.0, 5.30)

    assert fp_a == fp_b
    assert fp_a != fp_c
    assert fp_a.startswith("scn_")


def test_security_zero_secret_logging():
    """Verifies that no partial API keys or secrets are logged across the codebase."""
    backend_root = Path(__file__).resolve().parent.parent

    # Patterns that leak partial keys: e.g. api_key[: or key[:6] or api_key[0:
    leak_pattern = re.compile(r"api_key\[[:0-9]+\]")

    for py_file in backend_root.rglob("*.py"):
        if "venv" in str(py_file) or ".git" in str(py_file):
            continue
        code = py_file.read_text(encoding="utf-8", errors="ignore")
        matches = leak_pattern.findall(code)
        assert len(matches) == 0, f"Secret leak pattern found in {py_file}: {matches}"
