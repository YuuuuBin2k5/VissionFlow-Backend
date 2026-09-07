"""
Visual Perceptual Hashing & Near-Duplicate Scene Detection (Phase 2.5 - Section 14)
Implements:
- Difference Hash (dHash) on video keyframes via Pillow.
- Hamming distance computation for perceptual visual signatures.
- Near-duplicate scene cluster / duplicate group detection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple
from PIL import Image


def compute_dhash(image_path: str | Path, hash_size: int = 8) -> str:
    """
    Computes a 64-bit difference hash (dHash) for an image.
    Robust against scaling, compression artifacts, and minor luminance shifts.
    Returns a 16-character hexadecimal string.
    """
    p = Path(image_path)
    if not p.exists() or p.stat().st_size == 0:
        return "0000000000000000"

    try:
        with Image.open(p) as img:
            # Resize to (hash_size + 1, hash_size) in grayscale
            resized = img.convert("L").resize(
                (hash_size + 1, hash_size),
                Image.Resampling.LANCZOS,
            )
            pixels = list(resized.getdata())

        diff = []
        for row in range(hash_size):
            for col in range(hash_size):
                pixel_left = pixels[row * (hash_size + 1) + col]
                pixel_right = pixels[row * (hash_size + 1) + col + 1]
                diff.append("1" if pixel_left > pixel_right else "0")

        decimal_val = int("".join(diff), 2)
        return f"{decimal_val:016x}"
    except Exception:
        return "0000000000000000"


def hamming_distance(hash1: str, hash2: str) -> int:
    """
    Computes Hamming distance (number of bit differences) between two hexadecimal hashes.
    Distance 0 = visually identical.
    Distance <= 6 = near duplicate (same footage with minor re-compression or color adjustment).
    Distance > 12 = visually distinct scenes.
    """
    if not hash1 or not hash2:
        return 64
    clean1 = hash1.removeprefix("dhash:")
    clean2 = hash2.removeprefix("dhash:")
    try:
        val1 = int(clean1, 16)
        val2 = int(clean2, 16)
        return bin(val1 ^ val2).count("1")
    except ValueError:
        return 64


def compute_scene_visual_fingerprint(keyframe_paths: List[str]) -> Optional[str]:
    """
    Computes the canonical visual fingerprint for a scene from its keyframes.
    Format: 'dhash:<16-hex>'
    """
    if not keyframe_paths:
        return None

    # Compute dHash for first valid keyframe (or median if multiple)
    hashes = []
    for kf in keyframe_paths:
        h = compute_dhash(kf)
        if h != "0000000000000000":
            hashes.append(h)

    if not hashes:
        return None
    return f"dhash:{hashes[0]}"


def find_duplicate_scenes(
    target_fp: str,
    candidate_fps: Dict[str, str],
    max_distance: int = 6,
) -> List[Tuple[str, int]]:
    """
    Finds candidate scenes that share near-duplicate visual content.
    Returns: List of (candidate_scene_id, distance) sorted by similarity.
    """
    if not target_fp:
        return []

    duplicates = []
    for scn_id, fp in candidate_fps.items():
        if not fp:
            continue
        dist = hamming_distance(target_fp, fp)
        if dist <= max_distance:
            duplicates.append((scn_id, dist))

    duplicates.sort(key=lambda x: x[1])
    return duplicates
