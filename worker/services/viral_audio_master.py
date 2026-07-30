"""
Viral Audio Master — FFmpeg Studio Master Chain 2-Pass
======================================================
Triển khai theo tài liệu ToiUuGiongDocAI.docx:

Signal Flow (thứ tự vật lý đúng):
  [Voice] → afftdn (Denoise) → highpass=80Hz → EQ 350Hz(-3dB) → EQ 4kHz(+2dB)
          → acompressor(threshold=-18dB, ratio=3:1)
          → [Sidechain Ducking với nhạc nền, ratio=12:1, attack=10ms, release=300ms]
          → amix → loudnorm 2-Pass (I=-14 LUFS, TP=-1.5, LRA=11, linear=true)

Tham chiếu:
  - EBU R128 loudness standard (-14 LUFS cho YouTube Shorts / TikTok)
  - FFmpeg sidechaincompress (threshold=0.05, ratio=12, attack=10, release=300)
  - Two-Pass Loudness Normalization (linear=true)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


# ═══════════════════════════════════════════════════════════════════════════
# TARGET LOUDNESS — Chuẩn EBU R128 cho YouTube Shorts / TikTok
# ═══════════════════════════════════════════════════════════════════════════

TARGET_LUFS = -14.0   # Integrated Loudness — ngưỡng nền tảng tự động chuẩn hóa
TARGET_TP = -1.5      # True Peak — tránh clipping khi codec nén AAC
TARGET_LRA = 11.0     # Loudness Range — dải động mượt mà


# ═══════════════════════════════════════════════════════════════════════════
# SIGNAL CHAIN — Bộ lọc giọng đọc (thứ tự vật lý đúng)
# ═══════════════════════════════════════════════════════════════════════════

def _build_voice_filter_chain() -> str:
    """
    Chuỗi bộ lọc xử lý giọng đọc theo thứ tự Signal Flow:
    1. afftdn    — Khử nhiễu nền (quạt, điều hòa, hiss)
    2. highpass  — Lọc thông cao 80Hz (loại bỏ ù điện, rung cơ học)
    3. EQ 350Hz  — Cắt dải đục -3dB (giải phóng khỏi âm "hộp giấy")
    4. EQ 4kHz   — Tăng dải sáng +2dB (phụ âm sắc sảo, nghe rõ trên loa điện thoại)
    5. acompressor — Nén động học ratio=3:1, tránh peak quá cao
    Nguồn: ToiUuGiongDocAI.docx — Signal Flow + FFmpeg EQ specs.
    """
    return (
        "afftdn=nf=-25,"                                        # 1. Denoise (-25dB noise floor)
        "highpass=f=80,"                                        # 2. HPF 80Hz
        "equalizer=f=350:t=q:w=1.0:g=-3,"                     # 3. Muddy cut -3dB @ 350Hz
        "equalizer=f=4000:t=q:w=1.0:g=2,"                     # 4. Presence boost +2dB @ 4kHz
        "acompressor=threshold=-18dB:ratio=3:attack=10:release=100:makeup=1"  # 5. Compressor
    )


def _build_sidechain_ducking_filter() -> str:
    """
    Sidechain Ducking FFmpeg filter.
    threshold=0.05 (~-26dBFS) — phản hồi ngay cả khi thì thầm
    ratio=12       — ép nhạc nền xuống sâu -16dB đến -20dB
    attack=10ms    — nhạc bị ép ngay lập tức khi từ đầu tiên phát
    release=300ms  — nhạc từ từ trở lại mượt mà trong khoảng nghỉ

    Nguồn: ToiUuGiongDocAI.docx — Sidechain Tham số Tối ưu.
    """
    return "sidechaincompress=threshold=0.05:ratio=12:attack=10:release=300"


# ═══════════════════════════════════════════════════════════════════════════
# FFmpeg HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _run_ffmpeg(cmd: str, description: str = "") -> str:
    """Thực thi lệnh FFmpeg, raise nếu lỗi, return stderr."""
    print(f"[ViralAudioMaster] {description}")
    try:
        result = subprocess.run(
            cmd, shell=True, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        return result.stderr.decode("utf-8", errors="ignore")
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="ignore") if e.stderr else ""
        print(f"[ViralAudioMaster ERROR] Command failed:\n{cmd}\n{stderr[:500]}")
        raise RuntimeError(f"FFmpeg command failed: {stderr[:300]}") from e


def _extract_loudnorm_json(stderr_output: str) -> dict:
    """Trích xuất JSON đo lường loudnorm từ stderr của FFmpeg Pass 1."""
    json_match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", stderr_output, re.DOTALL)
    if not json_match:
        raise RuntimeError(
            "Không thể trích xuất thông số Loudness từ Pass 1. "
            "FFmpeg có thể chưa được cài đặt hoặc filter loudnorm không khả dụng."
        )
    return json.loads(json_match.group(0))


# ═══════════════════════════════════════════════════════════════════════════
# MAIN: MASTER VIRAL AUDIO — 2-Pass Pipeline
# ═══════════════════════════════════════════════════════════════════════════

def _get_ffmpeg_bin() -> str:
    try:
        import imageio_ffmpeg
        return f'"{imageio_ffmpeg.get_ffmpeg_exe()}"'
    except Exception:
        return "ffmpeg"

def master_viral_audio(
    voice_path: str,
    output_path: str,
    music_path: str | None = None,
    target_lufs: float = TARGET_LUFS,
    target_tp: float = TARGET_TP,
    target_lra: float = TARGET_LRA,
) -> str:
    """
    Quy trình hậu kỳ Studio Master 2-Pass tích hợp Sidechain Ducking.

    Args:
        voice_path:   Đường dẫn file âm thanh giọng đọc (từ ElevenLabs/Edge-TTS).
        output_path:  Đường dẫn file âm thanh đầu ra đã xử lý.
        music_path:   Đường dẫn nhạc nền (nếu có, áp dụng sidechain ducking).
        target_lufs:  Mục tiêu Integrated Loudness (mặc định -14 LUFS).
        target_tp:    Mục tiêu True Peak (mặc định -1.5 dBTP).
        target_lra:   Mục tiêu Loudness Range (mặc định 11 LU).

    Returns:
        str: Đường dẫn file âm thanh đầu ra.

    Nguồn: ToiUuGiongDocAI.docx — Two-Pass Loudness Normalization + Sidechain.
    """
    ffmpeg_bin = _get_ffmpeg_bin()
    voice_path = str(Path(voice_path).resolve())
    output_path = str(Path(output_path).resolve())

    if not os.path.exists(voice_path):
        raise FileNotFoundError(f"Không tìm thấy file giọng đọc: {voice_path}")

    has_music = music_path and os.path.exists(str(music_path))
    voice_filter = _build_voice_filter_chain()
    sidechain_filter = _build_sidechain_ducking_filter()

    # ──────────────────────────────────────────────────────────────────────
    # PASS 1: Đo lường Loudness thực tế của hỗn hợp sau khi xử lý
    # ──────────────────────────────────────────────────────────────────────
    print(f"[ViralAudioMaster] ⏳ Pass 1: Phân tích Loudness thực tế...")

    if has_music:
        # Với nhạc nền: voice chain → sidechain → amix → loudnorm analyze
        # Cấu hình vo_proc là đầu vào thứ 1 của amix (duration=first) để đảm bảo thời lượng khớp 100% với giọng đọc, không bị cắt sớm
        filter_pass1 = (
            f"[1:a]{voice_filter},asplit=2[vo_proc][sc_detector];"
            f"[0:a][sc_detector]{sidechain_filter}[bg_ducked];"
            f"[vo_proc][bg_ducked]amix=inputs=2:duration=first[mix_preview];"
            f"[mix_preview]loudnorm=I={target_lufs}:TP={target_tp}:LRA={target_lra}:print_format=json"
        )
        cmd_pass1 = (
            f'{ffmpeg_bin} -y -stream_loop -1 -i "{music_path}" -i "{voice_path}" '
            f'-filter_complex "{filter_pass1}" -f null -'
        )
    else:
        # Chỉ giọng đọc: voice chain → loudnorm analyze
        filter_pass1 = (
            f"[0:a]{voice_filter}[voice_proc];"
            f"[voice_proc]loudnorm=I={target_lufs}:TP={target_tp}:LRA={target_lra}:print_format=json"
        )
        cmd_pass1 = (
            f'{ffmpeg_bin} -y -i "{voice_path}" '
            f'-filter_complex "{filter_pass1}" -f null -'
        )

    stderr_pass1 = _run_ffmpeg(cmd_pass1, "Pass 1: Phân tích Loudness...")
    measurements = _extract_loudnorm_json(stderr_pass1)

    m_i = measurements["input_i"]
    m_tp = measurements["input_tp"]
    m_lra = measurements["input_lra"]
    m_thresh = measurements["input_thresh"]
    m_offset = measurements.get("target_offset", "0.0")

    print(
        f"[ViralAudioMaster] ✅ Pass 1 hoàn tất: "
        f"Loudness={m_i} LUFS, True Peak={m_tp} dBTP, LRA={m_lra} LU"
    )

    # ──────────────────────────────────────────────────────────────────────
    # PASS 2: Áp dụng xử lý tuyến tính với thông số đo lường từ Pass 1
    # linear=true → hệ số khuếch đại đồng nhất, bảo toàn dynamics giọng đọc
    # ──────────────────────────────────────────────────────────────────────
    print(f"[ViralAudioMaster] ⏳ Pass 2: Áp dụng Studio Master (linear=true)...")

    loudnorm_pass2 = (
        f"loudnorm=I={target_lufs}:TP={target_tp}:LRA={target_lra}:"
        f"measured_I={m_i}:measured_TP={m_tp}:measured_LRA={m_lra}:"
        f"measured_thresh={m_thresh}:offset={m_offset}:linear=true"
    )

    if has_music:
        filter_pass2 = (
            f"[1:a]{voice_filter},asplit=2[vo_proc][sc_detector];"
            f"[0:a][sc_detector]{sidechain_filter}[bg_ducked];"
            f"[vo_proc][bg_ducked]amix=inputs=2:duration=first[mix_unnormalized];"
            f"[mix_unnormalized]{loudnorm_pass2}[final_master]"
        )
        cmd_pass2 = (
            f'{ffmpeg_bin} -y -stream_loop -1 -i "{music_path}" -i "{voice_path}" '
            f'-filter_complex "{filter_pass2}" '
            f'-map "[final_master]" -c:a aac -b:a 192k -ar 44100 "{output_path}"'
        )
    else:
        filter_pass2 = (
            f"[0:a]{voice_filter}[voice_proc];"
            f"[voice_proc]{loudnorm_pass2}[final_master]"
        )
        cmd_pass2 = (
            f'{ffmpeg_bin} -y -i "{voice_path}" '
            f'-filter_complex "{filter_pass2}" '
            f'-map "[final_master]" -c:a aac -b:a 192k -ar 44100 "{output_path}"'
        )

    _run_ffmpeg(cmd_pass2, "Pass 2: Áp dụng mastering + xuất bản...")

    if not os.path.exists(output_path) or os.path.getsize(output_path) < 1000:
        raise RuntimeError(f"Pass 2 thất bại: Output không hợp lệ tại {output_path}")

    output_size_kb = os.path.getsize(output_path) / 1024
    print(
        f"[ViralAudioMaster] ✅ Studio Master 2-Pass hoàn tất! "
        f"Output: {output_path} ({output_size_kb:.1f} KB)"
    )
    return output_path


# ═══════════════════════════════════════════════════════════════════════════
# QUICK VOICE MASTER — Chỉ xử lý giọng đọc (không có nhạc nền)
# ═══════════════════════════════════════════════════════════════════════════

def master_voice_only(voice_path: str, output_path: str) -> str:
    """
    Phiên bản rút gọn chỉ master giọng đọc (không nhạc nền).
    Dùng khi audio_mixer đã mix nhạc trước.
    """
    return master_viral_audio(
        voice_path=voice_path,
        output_path=output_path,
        music_path=None,
    )
