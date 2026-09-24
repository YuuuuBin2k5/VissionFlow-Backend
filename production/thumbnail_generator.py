"""
AI Thumbnail Generation Service for VisionFlow Auto Production System.
Generates 3 distinct high-CTR, dramatic, viral thumbnail candidates using Google GenAI (Imagen 3).
Uploads generated thumbnails to Cloudflare R2 / S3 or fallback storage, and returns public URLs.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from production.credential_resolver import get_gemini_api_key

logger = logging.getLogger("visionflow.production.thumbnail_generator")

# Local storage for development fallback thumbnails
THUMBNAIL_LOCAL_DIR = Path(__file__).resolve().parent.parent / ".runs_storage" / "thumbnails"
THUMBNAIL_LOCAL_DIR.mkdir(parents=True, exist_ok=True)


class ThumbnailGenerator:
    """Generates dramatic, high-engagement thumbnails for vertical video (Shorts/TikTok) or horizontal video."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or get_gemini_api_key()

    def _build_prompts(
        self,
        title: str,
        hook: str,
        tone: str = "viral",
        category: str = "general",
    ) -> List[Dict[str, str]]:
        """
        Creates 3 diverse conceptual prompts tailored for maximum CTR and emotional hook.
        1. Extreme Emotional Focal: Hyper-focused expression or iconic subject.
        2. Epic Cinematic Wide/Atmospheric: High-stakes environmental setup.
        3. High-Contrast Dynamic Climax: Neon/punchy action focal point.
        """
        base_style = (
            "8k resolution, cinematic lighting, volumetric smoke, photorealistic masterpiece, "
            "shot on 35mm lens, f/1.8 depth of field, vivid dynamic color grading, hyper-detailed textures, "
            "ultra-clear focal subject, NO typography, NO watermark, NO text overlays, clean negative space."
        )

        cat_hints = {
            "history": "ancient dramatic atmosphere, historical epic, realistic museum lighting, dust motes",
            "mystery": "dark noir lighting, ominous shadows, chilling suspense, deep cinematic contrast",
            "science": "futuristic sleek aesthetics, holographic subtle rim light, high-tech clean lab atmosphere",
            "viral": "punchy vibrant colors, intense emotional shock, dramatic studio rim light, high saturation",
            "general": "vivid dramatic lighting, intense composition, cinematic depth of field",
        }
        style_hint = cat_hints.get(category.lower(), cat_hints["general"])

        prompts = [
            {
                "style_label": "Intense Close-Up",
                "prompt": (
                    f"A dramatic, intense close-up focal shot capturing the climax of: '{hook or title}'. "
                    f"{style_hint}. Emotional expressive focal element, intense eye-contact or captivating center of interest. {base_style}"
                ),
            },
            {
                "style_label": "Epic Cinematic Atmosphere",
                "prompt": (
                    f"An epic cinematic establishing scene representing '{title}'. "
                    f"{style_hint}. Volumetric atmosphere, dramatic scale, awe-inspiring perspective, mysterious mood. {base_style}"
                ),
            },
            {
                "style_label": "Dynamic High-Contrast Pop",
                "prompt": (
                    f"A high-contrast, vivid dynamic shot featuring the core subject of '{hook or title}'. "
                    f"{style_hint}. Striking color contrast, neon rim lighting against deep shadows, hyper-real commercial quality. {base_style}"
                ),
            },
        ]
        return prompts

    def _upload_thumbnail(self, image_bytes: bytes, run_id: str, index: int) -> str:
        """
        Uploads image to Cloudflare R2 / S3 if available; otherwise saves locally and returns local file URL.
        """
        file_name = f"thumb_{run_id}_{index}_{uuid.uuid4().hex[:6]}.jpg"
        mime_type = "image/jpeg"

        # 1. Try S3/R2 via S3CompatibleObjectStorage if configured
        try:
            from worker.services.visionflow_object_storage import (
                S3CompatibleObjectStorage,
                VisionFlowObjectStorageSettings,
            )
            settings = VisionFlowObjectStorageSettings.from_env()
            storage = S3CompatibleObjectStorage(settings)
            
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp.write(image_bytes)
                tmp_path = Path(tmp.name)

            try:
                object_key = f"visionflow/{run_id}/thumbnails/{file_name}"
                storage.put_file(object_key, str(tmp_path), content_type=mime_type)
                public_url = storage.get_public_url(object_key)
                logger.info("Successfully uploaded thumbnail to R2/S3: %s", public_url)
                return public_url
            finally:
                tmp_path.unlink(missing_ok=True)
        except Exception as err:
            logger.info("R2/S3 not configured or upload failed (%s), using local/fallback storage", err)

        # 2. Try CloudAssetUploader fallback (Litterbox/Tmpfiles)
        try:
            from worker.services.visionflow_object_storage import CloudAssetUploader
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp.write(image_bytes)
                tmp_path = Path(tmp.name)
            try:
                url = CloudAssetUploader.upload_export_video(run_id, str(tmp_path))
                if url:
                    return url
            finally:
                tmp_path.unlink(missing_ok=True)
        except Exception as fallback_err:
            logger.debug("CloudAssetUploader fallback notice: %s", fallback_err)

        # 3. Development / Local persistence: save to .runs_storage/thumbnails
        run_thumb_dir = THUMBNAIL_LOCAL_DIR / run_id
        run_thumb_dir.mkdir(parents=True, exist_ok=True)
        local_file = run_thumb_dir / file_name
        with open(local_file, "wb") as f:
            f.write(image_bytes)
        
        # Return path or relative URL
        api_base = os.getenv("VISIONFLOW_CONTROL_PLANE_PUBLIC_URL", "").rstrip("/")
        if api_base:
            return f"{api_base}/api/v1/production/runs/{run_id}/thumbnails/{file_name}"
        return f"/api/v1/production/runs/{run_id}/thumbnails/{file_name}"

    def generate_thumbnails(
        self,
        title: str,
        hook: str = "",
        tone: str = "viral",
        category: str = "general",
        aspect_ratio: str = "9:16",
        count: int = 3,
        run_id: Optional[str] = None,
    ) -> List[str]:
        """
        Generates up to `count` (default 3) thumbnail options for a video.
        Returns a list of accessible URLs.
        """
        active_run_id = run_id or f"thumb_run_{uuid.uuid4().hex[:8]}"
        prompts = self._build_prompts(title=title, hook=hook, tone=tone, category=category)
        prompts_to_use = prompts[:count]

        api_key = self.api_key or get_gemini_api_key()
        if not api_key:
            logger.warning("No GEMINI_API_KEY found, creating deterministic placeholder thumbnails.")
            return self._create_fallback_thumbnails(active_run_id, title, count)

        generated_urls: List[str] = []

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)

            # Map aspect ratio for Imagen (9:16 for vertical shorts, 16:9 for horizontal)
            target_aspect_ratio = "9:16" if "9" in aspect_ratio or "16" in aspect_ratio and aspect_ratio.startswith("9") else "16:9"

            for i, p_info in enumerate(prompts_to_use):
                prompt_text = p_info["prompt"]
                try:
                    logger.info("Generating thumbnail candidate %d with Imagen 3: %s", i + 1, p_info["style_label"])
                    config = types.GenerateImagesConfig(
                        number_of_images=1,
                        aspect_ratio=target_aspect_ratio,
                        output_mime_type="image/jpeg",
                    )
                    
                    # Try primary model: imagen-3.0-generate-002
                    model_name = os.getenv("VISIONFLOW_IMAGEN_MODEL", "imagen-3.0-generate-002")
                    try:
                        response = client.models.generate_images(
                            model=model_name,
                            prompt=prompt_text,
                            config=config,
                        )
                    except Exception as model_err:
                        # Fallback to fast model if primary hits quota or not found
                        logger.warning("Primary Imagen model %s failed (%s), trying imagen-3.0-fast-generate-001", model_name, model_err)
                        response = client.models.generate_images(
                            model="imagen-3.0-fast-generate-001",
                            prompt=prompt_text,
                            config=config,
                        )

                    if response and response.generated_images:
                        image_obj = response.generated_images[0].image
                        if image_obj and image_obj.image_bytes:
                            url = self._upload_thumbnail(image_obj.image_bytes, active_run_id, i + 1)
                            generated_urls.append(url)
                            continue

                    logger.warning("Empty image returned for thumbnail candidate %d", i + 1)
                except Exception as gen_err:
                    logger.error("Failed to generate thumbnail candidate %d: %s", i + 1, gen_err)

        except Exception as e:
            logger.error("Error setting up Google GenAI client for thumbnail generation: %s", e)

        # If any slots are missing, fill with high-quality styled fallbacks
        if len(generated_urls) < count:
            logger.info("Filling remaining %d thumbnail slots with SVG/graphic fallbacks", count - len(generated_urls))
            needed = count - len(generated_urls)
            fallback_urls = self._create_fallback_thumbnails(active_run_id, title, needed, start_idx=len(generated_urls) + 1)
            generated_urls.extend(fallback_urls)

        return generated_urls

    def _create_fallback_thumbnails(
        self,
        run_id: str,
        title: str,
        count: int,
        start_idx: int = 1,
    ) -> List[str]:
        """
        Creates visually appealing, gradient-based SVG/JPEG thumbnails as reliable fallbacks.
        Ensures the UI always has 3 valid, clickable images.
        """
        run_thumb_dir = THUMBNAIL_LOCAL_DIR / run_id
        run_thumb_dir.mkdir(parents=True, exist_ok=True)

        palettes = [
            ("#0f172a", "#1e293b", "#06b6d4"),  # Cyan slate
            ("#18181b", "#27272a", "#a855f7"),  # Purple dark
            ("#09090b", "#1c1917", "#f59e0b"),  # Amber flame
        ]

        urls: List[str] = []
        safe_title = (title or "VisionFlow Video")[:45]

        for i in range(count):
            idx = start_idx + i
            c1, c2, accent = palettes[i % len(palettes)]
            svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" width="720" height="1280" viewBox="0 0 720 1280">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{c1}" />
      <stop offset="100%" stop-color="{c2}" />
    </linearGradient>
    <radialGradient id="glow" cx="50%" cy="40%" r="50%">
      <stop offset="0%" stop-color="{accent}" stop-opacity="0.35" />
      <stop offset="100%" stop-color="{c1}" stop-opacity="0" />
    </radialGradient>
  </defs>
  <rect width="720" height="1280" fill="url(#bg)" />
  <circle cx="360" cy="500" r="300" fill="url(#glow)" />
  <rect x="60" y="80" width="160" height="40" rx="8" fill="{accent}" fill-opacity="0.2" stroke="{accent}" stroke-width="1.5" />
  <text x="140" y="105" font-family="system-ui, -apple-system, sans-serif" font-size="16" font-weight="700" fill="{accent}" text-anchor="middle">OPTION {idx}</text>
  <text x="360" y="550" font-family="system-ui, -apple-system, sans-serif" font-size="36" font-weight="800" fill="#ffffff" text-anchor="middle">
    <tspan x="360" dy="0">{safe_title[:22]}</tspan>
    <tspan x="360" dy="48">{safe_title[22:]}</tspan>
  </text>
  <rect x="220" y="1120" width="280" height="48" rx="24" fill="#000000" fill-opacity="0.6" stroke="#ffffff" stroke-opacity="0.2" />
  <text x="360" y="1150" font-family="system-ui, -apple-system, sans-serif" font-size="16" font-weight="600" fill="#ffffff" text-anchor="middle">VISIONFLOW AI</text>
</svg>"""
            file_name = f"thumb_{run_id}_{idx}.svg"
            local_file = run_thumb_dir / file_name
            with open(local_file, "w", encoding="utf-8") as f:
                f.write(svg_content)

            api_base = os.getenv("VISIONFLOW_CONTROL_PLANE_PUBLIC_URL", "").rstrip("/")
            if api_base:
                urls.append(f"{api_base}/api/v1/production/runs/{run_id}/thumbnails/{file_name}")
            else:
                urls.append(f"/api/v1/production/runs/{run_id}/thumbnails/{file_name}")

        return urls


# Singleton instance
thumbnail_generator = ThumbnailGenerator()
