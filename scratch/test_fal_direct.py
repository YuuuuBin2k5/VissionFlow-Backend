import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from worker.config import FAL_KEY
from worker.services.fal_service import FalService

print(f"[Debug] FAL_KEY from worker.config: '{FAL_KEY[:8]}...' if len > 8 else '{FAL_KEY}'")
print(f"[Debug] FAL_KEY from os.environ: '{os.environ.get('FAL_KEY', '')[:8]}...'")

fal = FalService()
print(f"[Debug] FalService.is_available(): {fal.is_available()}")

if not fal.is_available():
    print("[ERROR] FalService is NOT available because FAL_KEY is missing in worker/config.py or os.environ.")
else:
    print("[Debug] Calling generate_scene_image test...")
    res = fal.generate_scene_image(
        scene_prompt="Cappy Para reading an ancient scroll under glowing paper lanterns in a cozy room",
        scene_id="test-1",
        mascot_profile={
            "name": "Cappy Para",
            "current_costume": "ancient_scholar"
        },
        emotion="wise_calm",
        style_preset="cozy_anime_3d"
    )
    print(f"[Debug] Result from generate_scene_image: {res}")
