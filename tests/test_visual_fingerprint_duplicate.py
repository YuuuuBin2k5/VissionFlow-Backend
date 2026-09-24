"""
Visual Perceptual Fingerprinting & Duplicate Detection Test Suite (Phase 2.5 - Section 14)
Verifies:
- 64-bit dHash computation on keyframe images.
- Hamming distance bit-level comparison.
- Near-duplicate detection thresholds (distance <= 6 matches near-duplicates, distance > 12 separates distinct footage).
- Visual duplicate clustering into groups.
"""

from __future__ import annotations

from pathlib import Path
import pytest
from PIL import Image, ImageDraw

from production.visual_hasher import (
    compute_dhash,
    compute_scene_visual_fingerprint,
    find_duplicate_scenes,
    hamming_distance,
)


def _create_sample_image(path: Path, color: str, shape: str = "rect") -> None:
    img = Image.new("RGB", (100, 100), color=color)
    draw = ImageDraw.Draw(img)
    if shape == "circle":
        draw.ellipse([20, 20, 80, 80], fill="white")
    elif shape == "rect":
        draw.rectangle([20, 20, 80, 80], fill="black")
    elif shape == "line":
        draw.line([0, 0, 100, 100], fill="yellow", width=5)
    img.save(path)


def test_dhash_computation(tmp_path: Path):
    img_path = tmp_path / "frame1.png"
    _create_sample_image(img_path, "red", "circle")

    h = compute_dhash(img_path)
    assert len(h) == 16, f"Expected 16-hex char dHash, got {h}"
    assert all(c in "0123456789abcdef" for c in h)


def test_hamming_distance_metrics():
    h1 = "dhash:0000000000000000"
    h2 = "dhash:0000000000000000"
    h3 = "dhash:0000000000000001"  # 1 bit difference
    h4 = "dhash:ffffffffffffffff"  # 64 bits difference

    assert hamming_distance(h1, h2) == 0
    assert hamming_distance(h1, h3) == 1
    assert hamming_distance(h1, h4) == 64


def test_near_duplicate_detection(tmp_path: Path):
    # Image 1
    img1 = tmp_path / "shot_a.png"
    _create_sample_image(img1, "blue", "circle")

    # Image 2: slightly altered image (e.g. compressed or 1 pixel different)
    img2 = tmp_path / "shot_a_copy.png"
    im = Image.open(img1)
    im.putpixel((50, 50), (255, 255, 255))
    im.save(img2, "PNG")

    # Image 3: completely distinct scene (white with yellow line)
    img3 = tmp_path / "shot_b_distinct.png"
    _create_sample_image(img3, "green", "line")

    h1 = compute_dhash(img1)
    h2 = compute_dhash(img2)
    h3 = compute_dhash(img3)

    dist_near = hamming_distance(f"dhash:{h1}", f"dhash:{h2}")
    dist_distinct = hamming_distance(f"dhash:{h1}", f"dhash:{h3}")

    assert dist_near <= 6, f"Near-duplicate distance should be <= 6, got {dist_near}"
    assert dist_distinct > 12, f"Distinct scene distance should be > 12, got {dist_distinct}"


def test_find_duplicate_scenes_clustering():
    target_fp = "dhash:1234567812345678"
    candidates = {
        "scn_02": "dhash:1234567812345679",  # Hamming dist 1 (near-duplicate)
        "scn_03": "dhash:ffffffff00000000",  # distinct
        "scn_04": "dhash:1234567812345670",  # Hamming dist 2 (near-duplicate)
        "scn_05": "dhash:a0a0a0a0a0a0a0a0",  # distinct
    }

    dups = find_duplicate_scenes(target_fp, candidates, max_distance=6)
    assert len(dups) == 2, f"Expected 2 duplicate matches, found {len(dups)}"

    dup_ids = [d[0] for d in dups]
    assert "scn_02" in dup_ids
    assert "scn_04" in dup_ids
    assert "scn_03" not in dup_ids
