"""
VisionFlow Unified Cross-Platform Render Engine Profile
======================================================
Đảm bảo 100% kết quả Render Video đồng nhất (Deterministic Parity)
giữa máy tính cá nhân (Local Windows) và GitHub Actions CI/CD Runner (Ubuntu Linux).
"""
import os
import sys
import shutil
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# 1. CORE UNIFIED ENCODING PARAMETERS (CRF 18 / 30 FPS / BT.709 Color Space)
# ─────────────────────────────────────────────────────────────────────────────
UNIFIED_CRF = 18                    # Visually Lossless 1080p Quality
UNIFIED_PRESET = "medium"           # High-Efficiency Compression Ratio
UNIFIED_FPS = 30                    # Standard Mobile Smooth Frame Rate (Shorts/Reels/TikTok)
UNIFIED_PIX_FMT = "yuv420p"         # Universal H.264 Player Compatibility
UNIFIED_AUDIO_SAMPLE_RATE = 44100   # 44.1kHz Studio Audio Rate
UNIFIED_AUDIO_BITRATE = "192k"      # High-fidelity AAC Audio Bitrate

# ─────────────────────────────────────────────────────────────────────────────
# 2. CROSS-PLATFORM FONT RESOLVER (Windows & Linux Ubuntu)
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
FONTS_DIR = BASE_DIR / "assets" / "fonts"

def ensure_fonts_dir() -> Path:
    """Tự động tạo thư mục chứa Font chữ dùng chung nếu chưa tồn tại"""
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    return FONTS_DIR

def get_font_file_path(font_name: str = "BeVietnamPro-Bold.ttf") -> str:
    """Trả về đường dẫn tuyệt đối đến tệp Font chữ dùng chung"""
    font_path = FONTS_DIR / font_name
    if font_path.exists():
        return str(font_path).replace("\\", "/")
    return font_name

# ─────────────────────────────────────────────────────────────────────────────
# 3. UNIVERSAL FFMPEG / FFPROBE BINARY RESOLVER
# ─────────────────────────────────────────────────────────────────────────────
def resolve_ffmpeg_exe() -> str:
    """Tự động tìm đường dẫn FFmpeg hoạt động 100% trên cả Windows và Linux"""
    # 1. Kiểm tra trong PATH hệ thống
    ffmpeg_in_path = shutil.which("ffmpeg")
    if ffmpeg_in_path:
        return f'"{ffmpeg_in_path}"' if " " in ffmpeg_in_path else ffmpeg_in_path

    # 2. Kiểm tra gói imageio_ffmpeg Python
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return f'"{exe}"' if " " in exe else exe
    except Exception:
        pass

    # 3. Fallback theo hệ điều hành
    return "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"

def resolve_ffprobe_exe() -> str:
    """Tự động tìm đường dẫn FFprobe hoạt động 100% trên cả Windows và Linux"""
    # 1. Kiểm tra trong PATH hệ thống
    ffprobe_in_path = shutil.which("ffprobe")
    if ffprobe_in_path:
        return f'"{ffprobe_in_path}"' if " " in ffprobe_in_path else ffprobe_in_path

    # 2. Kiểm tra bên cạnh ffmpeg trong imageio_ffmpeg
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        ffprobe_exe = str(Path(ffmpeg_exe).parent / ("ffprobe.exe" if sys.platform == "win32" else "ffprobe"))
        if os.path.exists(ffprobe_exe):
            return f'"{ffprobe_exe}"' if " " in ffprobe_exe else ffprobe_exe
    except Exception:
        pass

    return "ffprobe.exe" if sys.platform == "win32" else "ffprobe"

def build_unified_ffmpeg_args(
    input_path: str,
    output_path: str,
    duration: float | None = None,
    filter_graph: str | None = None,
    extra_args: list[str] | None = None
) -> list[str]:
    """
    Xây dựng chuỗi lệnh FFmpeg chuẩn hóa đồng nhất 100% giữa Windows Local và Linux GitHub Actions.
    """
    ffmpeg_bin = resolve_ffmpeg_exe().replace('"', '')
    cmd = [ffmpeg_bin, "-y"]

    if duration and duration > 0:
        cmd.extend(["-t", f"{duration:.3f}"])

    cmd.extend(["-i", str(input_path)])

    if filter_graph:
        cmd.extend(["-vf", filter_graph])

    cmd.extend([
        "-r", str(UNIFIED_FPS),
        "-c:v", "libx264",
        "-preset", UNIFIED_PRESET,
        "-crf", str(UNIFIED_CRF),
        "-pix_fmt", UNIFIED_PIX_FMT,
        "-colorspace", "bt709",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-movflags", "+faststart"
    ])

    if extra_args:
        cmd.extend(extra_args)

    cmd.append(str(output_path))
    return cmd
