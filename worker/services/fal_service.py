"""
FalService — AI Image Generation Engine powered by Fal.ai (Flux.1 Schnell / Dev)
Designed for Cappy Para (3D Animated Capybara Mascot) character consistency.
"""

import os
import random
import requests
from pathlib import Path
from worker.config import FAL_KEY, ASSETS_DIR

# Capybara Mascot (Cappy Para) Outfit Prompts
COSTUME_PROMPTS = {
    "ancient_scholar": "wearing a traditional dark grey linen scholar robe and tiny round spectacles",
    "cozy_home": "wearing a cozy oversized knitted sweater, holding a steaming mug of tea",
    "onsen_relax": "relaxing in a warm wooden onsen bath with a small orange resting on head",
    "detective": "wearing a brown tweed detective hat and holding a vintage magnifying glass",
    "default": "wearing a small friendly scarf and tiny round spectacles",
}

# Style Presets
STYLE_PRESETS = {
    "cozy_anime_3d": "cozy 3D Pixar-Ghibli hybrid animation style, soft studio warm lighting, plush fur texture, vibrant color palette, vertical 9:16 aspect ratio, cinematic depth of field, 8k render",
    "chibi_3d": "cute 3D chibi cartoon character render, isometric soft lighting, pastel colors, 9:16 vertical ratio, 8k",
    "retro_storybook": "warm retro storybook illustration style, rich watercolors, soft golden lighting, 9:16 vertical ratio",
}


class FalService:
    def __init__(self, api_key: str | None = None):
        self.api_key = (api_key or "").strip()

    def get_active_key(self) -> str:
        return (self.api_key or os.environ.get("FAL_KEY", "") or FAL_KEY).strip()

    def is_available(self) -> bool:
        key = self.get_active_key()
        return bool(key and len(key) > 5)

    def build_cappy_prompt(self, mascot_profile: dict | None, scene_prompt: str, emotion: str = "", style_key: str = "cozy_anime_3d") -> str:
        """
        Builds a character-consistent prompt for Cappy Para (Capybara Mascot).
        """
        base_mascot = "A cute stylized 3D animated capybara mascot named Cappy, round friendly body, soft brown plush fur, big expressive eyes"
        sidekick = "a small yellow duck named Boni sitting peacefully on Cappy's head"
        
        costume_key = "default"
        if mascot_profile and isinstance(mascot_profile, dict):
            costume_key = mascot_profile.get("current_costume", "ancient_scholar")
            if mascot_profile.get("base_prompt"):
                base_mascot = mascot_profile.get("base_prompt")
            if mascot_profile.get("signature_sidekick"):
                sidekick = mascot_profile.get("signature_sidekick")
        
        costume_text = COSTUME_PROMPTS.get(costume_key, COSTUME_PROMPTS["default"])
        style_text = STYLE_PRESETS.get(style_key, STYLE_PRESETS["cozy_anime_3d"])
        
        emotion_text = f", {emotion} facial expression" if emotion else ""
        
        full_prompt = f"{base_mascot}, {costume_text}, {sidekick}, {scene_prompt}{emotion_text}, {style_text}"
        return full_prompt

    def generate_scene_image(
        self,
        scene_prompt: str,
        scene_id: int | str,
        mascot_profile: dict | None = None,
        emotion: str = "",
        style_preset: str = "cozy_anime_3d",
    ) -> str | None:
        """
        Generates a 9:16 vertical scene image via Fal.ai Flux Schnell model.
        Returns the path to the downloaded image file, or None if failed.
        """
        prompt = self.build_cappy_prompt(mascot_profile, scene_prompt, emotion, style_preset)

        active_key = self.get_active_key()
        if active_key and len(active_key) > 5:
            print(f"[FalService] Generating AI Image via Fal.ai Flux for Scene {scene_id}...")
            print(f"[FalService Prompt] {prompt[:160]}...")

            url = "https://fal.run/fal-ai/flux/schnell"
            headers = {
                "Authorization": f"Key {active_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "prompt": prompt,
                "image_size": "portrait_16_9",
                "num_inference_steps": 4,
                "num_images": 1,
                "enable_safety_checker": True,
            }

            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=45)
                if resp.status_code == 200:
                    data = resp.json()
                    images = data.get("images", [])
                    if images and isinstance(images, list) and images[0].get("url"):
                        img_url = images[0]["url"]
                        output_filename = f"scene_{scene_id}_fal_{random.randint(1000, 9999)}.png"
                        output_path = str(ASSETS_DIR / output_filename)
                        img_resp = requests.get(img_url, timeout=30)
                        if img_resp.status_code == 200:
                            with open(output_path, "wb") as f:
                                f.write(img_resp.content)
                            print(f"[FalService Success] AI Scene Image saved to: {output_path}")
                            return output_path

                print(f"[FalService Error] Fal.ai API status {resp.status_code}: {resp.text[:200]}")
            except Exception as err:
                print(f"[FalService Exception] Failed during Fal.ai call: {err}")

        # Fallback 100% Free AI Generator via Pollinations.ai (Flux Model - No key or credit required)
        print(f"[FalService Notice] Switching to 100% FREE Pollinations.ai Flux Engine for Scene {scene_id}...")
        return self.generate_free_pollinations_image(prompt, scene_id)

    def generate_free_pollinations_image(self, prompt: str, scene_id: int | str) -> str | None:
        """
        100% Free Unlimited AI Image Generator powered by Pollinations.ai (Flux model).
        Requires NO API Key and NO paid credits.
        """
        import urllib.parse
        encoded_prompt = urllib.parse.quote(prompt)
        seed = random.randint(10000, 99999)
        url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1920&nologo=true&seed={seed}&model=flux"
        print(f"[PollinationsFreeAI] Generating 100% FREE AI Image via Flux for Scene {scene_id}...")
        try:
            resp = requests.get(url, timeout=45)
            if resp.status_code == 200 and len(resp.content) > 5000:
                output_filename = f"scene_{scene_id}_free_ai_{random.randint(1000, 9999)}.png"
                output_path = str(ASSETS_DIR / output_filename)
                with open(output_path, "wb") as f:
                    f.write(resp.content)
                print(f"[PollinationsFreeAI Success] Saved 100% FREE AI Image to: {output_path}")
                return output_path
        except Exception as err:
            print(f"[PollinationsFreeAI Error] Failed to generate free AI image: {err}")
        return None
