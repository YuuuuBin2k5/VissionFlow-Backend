"""FFmpeg post-render compositor for operator-owned text layers.

MoviePy renders the base short.  This adapter applies the locked caption track
afterwards with an ASS sidecar, so timeline text is part of the exported MP4
rather than console-only metadata.  It intentionally uses an argv list (never
a shell command) and writes every transient file inside the render workspace.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from worker.domain.composition_render_plan import CompositionRenderPlan


class CaptionCompositingError(RuntimeError):
    """FFmpeg could not apply a locked operator caption layer."""


@dataclass(frozen=True)
class CaptionCue:
    start_ms: int
    end_ms: int
    text: str
    pop: bool


def resolve_ffmpeg_executable(executable: str = "ffmpeg") -> str:
    import shutil
    if executable != "ffmpeg" and shutil.which(executable):
        return executable
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return executable


class FfmpegCaptionCompositor:
    def __init__(self, executable: str | None = None) -> None:
        self._executable = resolve_ffmpeg_executable(executable or "ffmpeg")

    def apply(self, source_path: str, render_plan: CompositionRenderPlan, workspace: Path, caption_preset: str = "hormozi") -> str:
        cues = caption_cues(render_plan)
        if not cues:
            return source_path
        workspace.mkdir(parents=True, exist_ok=True)
        ass_path = workspace / "composition-captions.ass"
        output_path = workspace / "composition-captioned.mp4"
        ass_path.write_text(build_ass_script(cues, caption_preset), encoding="utf-8")
        command = build_ffmpeg_command(self._executable, Path(source_path), ass_path, output_path)
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0 or not output_path.is_file():
            raise CaptionCompositingError("FFmpeg failed to apply the locked caption layer")
        return str(output_path)


def caption_cues(render_plan: CompositionRenderPlan) -> tuple[CaptionCue, ...]:
    cues: list[CaptionCue] = []
    for track in render_plan.tracks:
        if track.track_type != "caption" or track.muted:
            continue
        for clip in track.clips:
            if clip.source_type != "text":
                continue
            text = clip.source_ref.strip()
            if not text:
                continue
            cues.append(CaptionCue(
                start_ms=clip.timeline_start_ms,
                end_ms=clip.timeline_start_ms + clip.duration_ms,
                text=text,
                pop=any(effect.key == "caption_pop" for effect in clip.effects),
            ))
    return tuple(sorted(cues, key=lambda cue: (cue.start_ms, cue.end_ms, cue.text)))


def build_ass_script(cues: tuple[CaptionCue, ...], caption_preset: str = "hormozi") -> str:
    # ASS Style definitions: Format is BGR alpha
    # hormozi: Bold Yellow text, high-contrast black outline
    # clean_news: Crisp white text, subtle outline
    # cinematic_quote: Italicized white text, soft shadow
    if caption_preset == "clean_news":
        style_line = "Style: VisionFlow,Arial,52,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,2,1,2,80,80,160,1"
    elif caption_preset == "cinematic_quote":
        style_line = "Style: VisionFlow,Arial,54,&H00F0F0F0,&H0000FFFF,&H00101010,&H80000000,1,1,0,0,100,100,0,0,1,2,3,2,80,80,200,1"
    else:  # hormozi (default)
        style_line = "Style: VisionFlow,Arial,66,&H0000FFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,2,2,80,80,220,1"

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
        style_line,
        "",
        "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ]
    for cue in cues:
        text = _escape_ass_text(cue.text)
        prefix = r"{\fad(80,120)}" if cue.pop else ""
        lines.append(f"Dialogue: 0,{_ass_timestamp(cue.start_ms)},{_ass_timestamp(cue.end_ms)},VisionFlow,,0,0,0,,{prefix}{text}")
    return "\n".join(lines) + "\n"


def build_ffmpeg_command(executable: str, source_path: Path, ass_path: Path, output_path: Path) -> list[str]:
    # Filter escaping is required by FFmpeg's filter parser; subprocess still
    # receives a separate argv item, so caption content never becomes a shell.
    filter_path = str(ass_path.resolve()).replace("\\", "/")
    escaped = filter_path.replace("'", r"\'").replace(":", r"\:").replace(",", r"\,").replace("[", r"\[").replace("]", r"\]")
    return [
        executable, "-y", "-i", str(source_path),
        "-vf", f"ass=filename='{escaped}'",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "copy", "-movflags", "+faststart", str(output_path),
    ]


def _ass_timestamp(milliseconds: int) -> str:
    total_centiseconds = max(0, milliseconds // 10)
    hours, remainder = divmod(total_centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


def _escape_ass_text(value: str) -> str:
    return value.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\r\n", "\\N").replace("\n", "\\N").replace("\r", "\\N")
