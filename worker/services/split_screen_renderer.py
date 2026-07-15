import os
import subprocess
import json
import re
from pathlib import Path

from worker.config import ASSETS_DIR, OUTPUT_DIR, FONTS_DIR
from worker.services.subtitle_renderer import SubtitleRenderer

class SplitScreenRenderer:
    def __init__(self):
        self.sub_renderer = SubtitleRenderer()

    def _ass_time(self, seconds: float) -> str:
        seconds = max(0.0, float(seconds))
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centis = int((seconds - int(seconds)) * 100)
        return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"

    def _escape_ass_text(self, text: str) -> str:
        return str(text or "").replace("{", "").replace("}", "").replace("\n", "\\N")

    def _escape_ffmpeg_path(self, path: str) -> str:
        p = str(path).replace("\\", "/")
        if ":" in p:
            p = p.replace(":", "\\:")
        p = p.replace("'", "'\\\\\\''")
        return p

    def _write_split_screen_ass(
        self,
        output_path: Path,
        word_timestamps: list,
        hook_text: str,
        hook_duration: float,
        cta_text: str,
        cta_start: float | None,
        total_duration: float,
        job_id: int,
        visual_preset: str = "split_editorial",
    ) -> str:
        preset_styles = {
            "split_editorial": ("&H00FFFFFF", "&H000000FF", "&H00000000", 56),
            "neon_depth": ("&H00FFFFFF", "&H0066FF00", "&H001A0010", 58),
            "warm_cinematic": ("&H00E6F2FF", "&H004DDEFF", "&H00241A10", 54),
            "clean_explainer": ("&H00FFFFFF", "&H00FFFFFF", "&H00000000", 50),
        }
        primary, secondary, outline, font_size = preset_styles.get(visual_preset, preset_styles["split_editorial"])
        lines = [
            "[Script Info]",
            "ScriptType: v4.00+",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: SplitMain,Montserrat ExtraBold,{font_size},{primary},{secondary},{outline},&HA0000000,-1,0,0,0,100,100,0,0,3,5,0,5,72,72,18,1",
            "Style: SplitHook,Montserrat ExtraBold,66,&H00FFFFFF,&H000000FF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,3,5,0,5,72,72,18,1",
            "Style: SplitCta,Montserrat ExtraBold,48,&H0000FFFF,&H000000FF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,3,4,0,5,72,72,18,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]

        if hook_text:
            lines.append(
                f"Dialogue: 0,{self._ass_time(0)},{self._ass_time(min(hook_duration, total_duration))},SplitHook,,0,0,0,,{{\\pos(540,300)}}{self._escape_ass_text(hook_text)}"
            )

        chunks = self.sub_renderer.group_words_into_chunks(word_timestamps)
        active_word_global_idx = 0

        for chunk in chunks:
            for i, active_w in enumerate(chunk):
                start_s = max(float(active_w["start_ms"]) / 1000.0, hook_duration)

                if i < len(chunk) - 1:
                    end_s = float(chunk[i+1]["start_ms"]) / 1000.0
                else:
                    end_s = float(chunk[-1]["end_ms"]) / 1000.0

                if end_s <= start_s:
                    continue

                word_tokens = []
                for j, w in enumerate(chunk):
                    word_str = self._escape_ass_text(w["word"])
                    if j == i:
                        angle = [-2, 2, -1, 1][(active_word_global_idx + j) % 4]
                        word_tokens.append(f"{{\\c&H66FF00&\\fscx110\\fscy110\\frz{angle}}}{word_str}{{\\r}}")
                    else:
                        if self.sub_renderer._is_keyword(word_str):
                            word_tokens.append(f"{{\\c&H4DDEFF&}}{word_str}{{\\r}}")
                        else:
                            word_tokens.append(word_str)

                styled_text = " ".join(word_tokens)
                lines.append(
                    f"Dialogue: 0,{self._ass_time(start_s)},{self._ass_time(min(end_s, total_duration))},SplitMain,,0,0,0,,{{\\pos(540,1500)}}{styled_text}"
                )

            active_word_global_idx += len(chunk)

        if cta_text and cta_start is not None:
            lines.append(
                f"Dialogue: 1,{self._ass_time(cta_start)},{self._ass_time(total_duration)},SplitCta,,0,0,0,,{{\\pos(540,1700)}}{self._escape_ass_text(cta_text)}"
            )

        output_path.write_text("\n".join(lines), encoding="utf-8")
        return str(output_path)

    def render_split_screen_video_ffmpeg(
        self,
        top_source: str,
        bottom_source: str,
        voice_audio_path: str,
        background_music_path: str | None,
        hook_text: str,
        hook_duration: float,
        cta_text: str,
        cta_start: float | None,
        total_duration: float,
        job_id: int,
        word_timestamps: list = None,
        metadata: dict = None,
        progress_callback = None
    ) -> str:
        # Parse border configuration
        visual_preset = str((metadata or {}).get("visual_preset") or "split_editorial")
        default_border = {"neon_depth": (6, "#00ff66"), "warm_cinematic": (4, "#d8a94a"), "clean_explainer": (2, "#ffffff")}
        border_thick, border_color_code = default_border.get(visual_preset, (0, "#000000"))
        border_config_str = metadata.get("border_config") if metadata else None
        if border_config_str:
            try:
                parsed = json.loads(border_config_str)
                if isinstance(parsed, dict):
                    border_thick = int(parsed.get("thickness", 4))
                    border_color_code = parsed.get("color", "#000000")
            except Exception:
                parts = str(border_config_str).split(",")
                if len(parts) == 2:
                    try:
                        border_thick = int(parts[0])
                        border_color_code = parts[1]
                    except Exception:
                        pass

        # Map color to safe FFmpeg format
        ffmpeg_color = "black"
        if border_color_code:
            col_lower = str(border_color_code).lower()
            if "white" in col_lower or col_lower == "#ffffff":
                ffmpeg_color = "white"
            elif "00ff66" in col_lower:
                ffmpeg_color = "0x00ff66"
            elif "black" in col_lower or col_lower == "#000000":
                ffmpeg_color = "black"
            else:
                if col_lower.startswith("#") and len(col_lower) == 7:
                    ffmpeg_color = "0x" + col_lower[1:]
                else:
                    ffmpeg_color = col_lower

        output_file_path = str(OUTPUT_DIR / f"split_screen_short_{job_id}.mp4")
        ass_path = ASSETS_DIR / f"split_screen_{job_id}.ass"

        self._write_split_screen_ass(
            output_path=ass_path,
            word_timestamps=word_timestamps or [],
            hook_text=hook_text,
            hook_duration=hook_duration,
            cta_text=cta_text,
            cta_start=cta_start,
            total_duration=total_duration,
            job_id=job_id,
            visual_preset=visual_preset,
        )

        ass_filter_path = self._escape_ffmpeg_path(str(ass_path))

        # Check fonts directory
        fonts_dir = FONTS_DIR
        workspace_root = Path(__file__).resolve().parent.parent.parent
        alt_fonts_dir = workspace_root / "AgentTiktok" / "shared" / "fonts"
        if (alt_fonts_dir / "Montserrat-ExtraBold.ttf").exists():
            fonts_dir = alt_fonts_dir

        fonts_dir_escaped = self._escape_ffmpeg_path(str(fonts_dir))

        env_copy = os.environ.copy()
        temp_fonts_dir = ASSETS_DIR / f"fonts_temp_{job_id}"
        temp_fonts_dir.mkdir(parents=True, exist_ok=True)
        fonts_conf_path = temp_fonts_dir / "fonts.conf"
        fonts_conf_content = f"""<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
    <dir>C:\\Windows\\Fonts</dir>
    <dir>{fonts_dir.as_posix()}</dir>
</fontconfig>
"""
        try:
            with open(fonts_conf_path, "w", encoding="utf-8") as f:
                f.write(fonts_conf_content)
        except Exception as fe:
            print(f"[SplitScreenRenderer Warning] Failed to write fonts.conf: {fe}")

        env_copy["FONTCONFIG_FILE"] = str(fonts_conf_path)
        env_copy["FONTCONFIG_PATH"] = str(temp_fonts_dir)
        env_copy["FC_CONFIG_DIR"] = str(temp_fonts_dir)

        inputs = [
            "ffmpeg", "-y",
            "-i", top_source,
            "-i", bottom_source,
            "-i", voice_audio_path,
        ]
        has_music = bool(background_music_path and os.path.exists(background_music_path))
        if has_music:
            inputs.extend(["-i", str(background_music_path)])

        if border_thick > 0:
            y_pos = int(960 - border_thick / 2)
            video_filter = (
                "[0:v]split[bg][fg];"
                "[bg]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960,boxblur=20,drawbox=color=black@0.3:t=1000[bg_blur];"
                "[fg]scale=1080:960:force_original_aspect_ratio=decrease[fg_scaled];"
                "[bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2[top_half];"
                "[1:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960[bottom_half];"
                "[top_half]pad=1080:1920:0:0:black[canvas];"
                "[canvas][bottom_half]overlay=0:960[stacked_raw];"
                    f"[stacked_raw]drawbox=x=0:y={y_pos}:w=1080:h={border_thick}:color={ffmpeg_color}:t=-1[stacked];"
                    f"[stacked]subtitles='{ass_filter_path}':fontsdir='{fonts_dir_escaped}'[v]"
            )
        else:
            video_filter = (
                "[0:v]split[bg][fg];"
                "[bg]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960,boxblur=20,drawbox=color=black@0.3:t=1000[bg_blur];"
                "[fg]scale=1080:960:force_original_aspect_ratio=decrease[fg_scaled];"
                "[bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2[top_half];"
                "[1:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960[bottom_half];"
                "[top_half]pad=1080:1920:0:0:black[canvas];"
                    "[canvas][bottom_half]overlay=0:960[stacked];"
                    f"[stacked]subtitles='{ass_filter_path}':fontsdir='{fonts_dir_escaped}'[v]"
            )

        if has_music:
            filter_complex = f"{video_filter};[3:a]volume=0.08[m];[2:a][m]amix=inputs=2:duration=first[a]"
            audio_map = "[a]"
        else:
            filter_complex = video_filter
            audio_map = "2:a"

        command = inputs + [
            "-t", f"{total_duration:.3f}",
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", audio_map,
            "-r", "24",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-strict", "-2",
            "-shortest",
            output_file_path,
        ]

        print(f"[SplitScreenRenderer] Rendering split-screen via FFmpeg: {output_file_path}")
        if progress_callback:
            progress_callback(0)

        result = subprocess.run(command, capture_output=True, text=True, env=env_copy)
        if result.returncode != 0:
            err_msg = (result.stderr or "").strip()
            if "fontsdir" in err_msg or "Option 'fontsdir' not found" in err_msg:
                print("[SplitScreenRenderer Warning] FFmpeg does not support 'fontsdir' option. Retrying without it...")
                new_filter_complex = re.sub(r":fontsdir='[^']*'", "", filter_complex)
                retry_command = list(command)
                for idx, arg in enumerate(retry_command):
                    if arg == filter_complex:
                        retry_command[idx] = new_filter_complex

                result = subprocess.run(retry_command, capture_output=True, text=True, env=env_copy)

            if result.returncode != 0:
                print(f"[SplitScreenRenderer FFmpeg Error] stdout: {result.stdout[-1200:]}")
                print(f"[SplitScreenRenderer FFmpeg Error] stderr: {result.stderr[-2000:]}")
                result.check_returncode()

        if progress_callback:
            progress_callback(100)

        try:
            ass_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            import shutil
            if temp_fonts_dir.exists():
                shutil.rmtree(temp_fonts_dir, ignore_errors=True)
        except Exception:
            pass

        return output_file_path
