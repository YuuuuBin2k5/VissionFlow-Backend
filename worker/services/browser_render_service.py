import os
import shutil
import subprocess
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

from worker.config import ASSETS_DIR, OUTPUT_DIR, REACTIVE_RENDER_HEIGHT, REACTIVE_RENDER_WIDTH
from worker.services.browser_runtime import browser_launch_options, describe_browser_runtime


class BrowserRenderService:
    def _ffmpeg_path(self) -> str:
        return imageio_ffmpeg.get_ffmpeg_exe()

    def _clean_dir(self, path: Path):
        if not path.exists():
            return
        try:
            shutil.rmtree(path)
        except Exception:
            import random
            try:
                trash_path = path.parent / f"{path.name}_trash_{random.randint(1000, 9999)}"
                path.rename(trash_path)
                shutil.rmtree(trash_path, ignore_errors=True)
            except Exception:
                pass

    def render_html_to_video(
        self,
        html_path: str,
        audio_path: str,
        audio_data: dict,
        job_id: int,
        fps: int = 24,
    ) -> str:
        frame_dir = Path(ASSETS_DIR) / f"reactive_frames_{job_id}"
        self._clean_dir(frame_dir)
        frame_dir.mkdir(parents=True, exist_ok=True)

        total_frames = max(1, len(audio_data.get("bass", [])))
        # Compute the exact video duration we will render (number of frames / fps)
        video_duration_s = total_frames / fps
        output_path = Path(OUTPUT_DIR) / f"tiktok_music_reactive_{job_id}.mp4"

        print(f"[BrowserRenderService] Capturing {total_frames} frames at {fps} FPS...")
        with sync_playwright() as playwright:
            print(f"[BrowserRenderService] Launching browser runtime: {describe_browser_runtime()}")
            browser = playwright.chromium.launch(**browser_launch_options(headless=True))
            page = browser.new_page(
                viewport={"width": REACTIVE_RENDER_WIDTH, "height": REACTIVE_RENDER_HEIGHT},
                device_scale_factor=1,
            )
            page.goto(Path(html_path).resolve().as_uri(), wait_until="networkidle")
            page.evaluate("""() => {
                document.querySelectorAll('video').forEach(video => {
                    video.playbackRate = 1;
                    video.play().catch(() => {});
                });
            }""")

            for frame_idx in range(total_frames):
                page.evaluate(
                    """(payload) => {
                        window.updateVisualsForFrame(payload.frameIndex);
                    }""",
                    {"frameIndex": frame_idx, "time": frame_idx / fps},
                )
                page.screenshot(
                    path=str(frame_dir / f"frame_{frame_idx:06d}.jpg"),
                    type="jpeg",
                    quality=90,
                    full_page=False
                )

            browser.close()

        cmd = [
            self._ffmpeg_path(),
            "-y",
            "-framerate",
            str(fps),
            "-i",
            str(frame_dir / "frame_%06d.jpg"),
            "-ss", "0",
            "-t", str(video_duration_s),
            "-i",
            audio_path,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            # Hard limit output to exactly the rendered frame count duration
            "-t", str(video_duration_s),
            str(output_path),
        ]
        print(f"[BrowserRenderService] Encoding video with FFmpeg: {output_path}")
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        try:
            shutil.rmtree(frame_dir)
        except Exception as cleanup_error:
            print(f"[BrowserRenderService Warning] Failed to clean frame dir: {cleanup_error}")

        if not os.path.exists(output_path):
            raise RuntimeError("FFmpeg completed but output file was not created.")

        return str(output_path)

    def render_html_to_transparent_overlay(
        self,
        html_path: str,
        audio_data: dict,
        job_id: int,
        fps: int = 24,
    ) -> str:
        frame_dir = Path(ASSETS_DIR) / f"overlay_frames_{job_id}"
        self._clean_dir(frame_dir)
        frame_dir.mkdir(parents=True, exist_ok=True)

        total_frames = max(1, len(audio_data.get("bass", [])))
        video_duration_s = total_frames / fps
        output_path = Path(ASSETS_DIR) / f"lyric_overlay_{job_id}.mov"

        print(f"[BrowserRenderService] Capturing transparent overlay {total_frames} frames at {fps} FPS...")
        with sync_playwright() as playwright:
            print(f"[BrowserRenderService] Launching browser runtime: {describe_browser_runtime()}")
            browser = playwright.chromium.launch(**browser_launch_options(headless=True))
            page = browser.new_page(
                viewport={"width": REACTIVE_RENDER_WIDTH, "height": REACTIVE_RENDER_HEIGHT},
                device_scale_factor=1,
            )
            page.goto(Path(html_path).resolve().as_uri(), wait_until="networkidle")

            for frame_idx in range(total_frames):
                page.evaluate(
                    """(payload) => {
                        window.updateVisualsForFrame(payload.frameIndex);
                    }""",
                    {"frameIndex": frame_idx},
                )
                page.screenshot(
                    path=str(frame_dir / f"frame_{frame_idx:06d}.png"),
                    type="png",
                    full_page=False,
                    omit_background=True,
                )

            browser.close()

        cmd = [
            self._ffmpeg_path(),
            "-y",
            "-framerate", str(fps),
            "-i", str(frame_dir / "frame_%06d.png"),
            "-t", str(video_duration_s),
            "-c:v", "qtrle",
            "-pix_fmt", "argb",
            str(output_path),
        ]
        print(f"[BrowserRenderService] Encoding transparent overlay: {output_path}")
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        try:
            shutil.rmtree(frame_dir)
        except Exception as cleanup_error:
            print(f"[BrowserRenderService Warning] Failed to clean overlay frame dir: {cleanup_error}")

        if not os.path.exists(output_path):
            raise RuntimeError("FFmpeg completed but transparent overlay was not created.")
        return str(output_path)
