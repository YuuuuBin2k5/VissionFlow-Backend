"""
AudioMixer — Hòa Âm Phối Khí Chuyên Nghiệp Viral Audio 2026
=============================================================
Nâng cấp theo tài liệu ToiUuGiongDocAI.docx:
  - Thay thế MoviePy ducking thủ công bằng FFmpeg Sidechain Ducking tự động
  - Tích hợp viral_audio_master 2-Pass Studio Master:
      Signal Flow: Denoise → HPF 80Hz → EQ → Compressor → Sidechain → 2-Pass Loudnorm
  - Fallback sang MoviePy nếu FFmpeg không khả dụng
"""
import os
import tempfile
import numpy as np
from pathlib import Path
from moviepy.audio.io.AudioFileClip import AudioFileClip
from moviepy.audio.AudioClip import CompositeAudioClip


class AudioMixer:
    def __init__(self):
        pass

    def get_speech_intervals(self, word_timestamps: list, merge_gap_s: float = 1.0) -> list:
        if not word_timestamps:
            return []
        intervals = []
        for w in word_timestamps:
            s = float(w["start_ms"]) / 1000.0
            e = float(w["end_ms"]) / 1000.0
            intervals.append((s, e))

        intervals.sort(key=lambda x: x[0])

        merged = []
        for s, e in intervals:
            if not merged:
                merged.append([s, e])
            else:
                prev_s, prev_e = merged[-1]
                if s - prev_e <= merge_gap_s:
                    merged[-1][1] = max(prev_e, e)
                else:
                    merged.append([s, e])
        return [tuple(x) for x in merged]

    def apply_ducking_to_music(self, music_clip: AudioFileClip, word_timestamps: list, total_duration: float) -> AudioFileClip:
        """
        MoviePy-based Auto-Ducking (Fallback khi FFmpeg không khả dụng).
        """
        intervals = self.get_speech_intervals(word_timestamps)

        def duck_filter(gf, t):
            factor = np.full(t.shape, 0.25)  # Thường dùng 0.25 (-12dB)
            for s, e in intervals:
                factor[(t >= s - 0.1) & (t <= e + 0.1)] = 0.05  # Giảm xuống 0.05 (-26dB) khi nói
            if len(factor.shape) > 0:
                return gf(t) * factor[:, np.newaxis]
            return gf(t) * factor

        return music_clip.transform(duck_filter)

    def mix_viral_audio_ffmpeg(
        self,
        voice_audio_path: str,
        background_music_path: str | None,
        output_path: str,
        total_duration: float = 0,
    ) -> str:
        """
        🎧 FFmpeg Studio Master 2-Pass Pipeline (Viral Audio 2026).
        Áp dụng đầy đủ:
          1. Signal Flow: Denoise → HPF 80Hz → EQ 350Hz(-3dB) → EQ 4kHz(+2dB) → Compressor
          2. Sidechain Ducking: threshold=0.05, ratio=12:1, attack=10ms, release=300ms
          3. 2-Pass Loudnorm: I=-14 LUFS, TP=-1.5, LRA=11, linear=true
        Nguồn: ToiUuGiongDocAI.docx — Two-Pass Loudness Normalization + Sidechain.

        Returns:
            str: Đường dẫn file audio đã master (aac, 192kbps, 44100Hz).
        """
        try:
            from worker.services.viral_audio_master import master_viral_audio
            result = master_viral_audio(
                voice_path=voice_audio_path,
                output_path=output_path,
                music_path=background_music_path if background_music_path and os.path.exists(background_music_path) else None,
                total_duration=total_duration,
            )
            return result
        except Exception as e:
            print(f"[AudioMixer Warning] FFmpeg viral_audio_master thất bại, fallback MoviePy: {e}")
            return ""

    def mix_audio_tracks(
        self,
        voice_audio_path: str,
        background_music_path: str,
        total_duration: float,
        word_timestamps: list,
        assets_dir: Path,
        cut_points: list = None,
    ) -> CompositeAudioClip:
        """
        Hòa âm phối khí: Giọng thoại + BGM + Sóng não 432Hz + SFX Transitions.

        ⚡ NÂNG CẤP: Thử FFmpeg Studio Master 2-Pass trước.
        Nếu thành công, trả về AudioFileClip từ file master.
        Fallback sang MoviePy ducking nếu FFmpeg thất bại.
        """
        # ── Thử FFmpeg Studio Master 2-Pass ──────────────────────────────
        try:
            with tempfile.NamedTemporaryFile(suffix=".aac", delete=False) as tmp:
                master_output_path = tmp.name

            result = self.mix_viral_audio_ffmpeg(
                voice_audio_path=voice_audio_path,
                background_music_path=background_music_path,
                output_path=master_output_path,
                total_duration=total_duration,
            )

            if result and os.path.exists(result) and os.path.getsize(result) > 5000:
                print(f"[AudioMixer] ✅ FFmpeg Studio Master 2-Pass thành công → {result}")
                # Cộng thêm 432Hz + SFX rồi mix cuối
                audio_clips = [AudioFileClip(result)]
                self._add_432hz_and_sfx(audio_clips, assets_dir, total_duration, cut_points)
                return CompositeAudioClip(audio_clips)

        except Exception as e:
            print(f"[AudioMixer Warning] FFmpeg pipeline thất bại: {e}. Dùng MoviePy fallback.")

        # ── Fallback: MoviePy Ducking ─────────────────────────────────────
        print("[AudioMixer] Sử dụng MoviePy ducking fallback...")
        audio_clips = []

        # 1. Giọng thoại chính
        voice_clip = AudioFileClip(voice_audio_path)
        audio_clips.append(voice_clip)

        # 2. Nhạc nền (MoviePy Auto-Ducking)
        if background_music_path and os.path.exists(background_music_path):
            try:
                music_clip = AudioFileClip(background_music_path)
                if music_clip.duration < total_duration:
                    from moviepy import afx
                    music_clip = music_clip.with_effects([afx.AudioLoop(duration=total_duration)])
                else:
                    music_clip = music_clip.subclipped(0, total_duration)
                music_clip = self.apply_ducking_to_music(music_clip, word_timestamps, total_duration)
                audio_clips.append(music_clip)
            except Exception as e:
                print(f"[AudioMixer Warning] Background music mix failed: {e}")

        # 3 + 4: 432Hz + SFX
        self._add_432hz_and_sfx(audio_clips, assets_dir, total_duration, cut_points)

        return CompositeAudioClip(audio_clips)

    def _add_432hz_and_sfx(
        self,
        audio_clips: list,
        assets_dir: Path,
        total_duration: float,
        cut_points: list | None,
    ) -> None:
        """Thêm tần số sóng não 432Hz và SFX chuyển cảnh."""
        # 3. Tần số sóng não 432Hz (Tác động tiềm thức giữ chân)
        audio_432hz_path = assets_dir / "audio" / "focus_432hz.mp3"
        if audio_432hz_path.exists():
            try:
                audio_432hz = AudioFileClip(str(audio_432hz_path))
                if audio_432hz.duration < total_duration:
                    from moviepy import afx
                    audio_432hz = audio_432hz.with_effects([afx.AudioLoop(duration=total_duration)])
                else:
                    audio_432hz = audio_432hz.subclipped(0, total_duration)
                audio_432hz = audio_432hz.with_volume_scaled(0.03)  # Thấp ở mức 3%
                audio_clips.append(audio_432hz)
            except Exception as e432:
                print(f"[AudioMixer Warning] Failed to mix 432Hz focus track: {e432}")

        # 4. Hiệu ứng âm thanh chuyển cảnh (SFX Transitions)
        if cut_points:
            for cp in cut_points:
                sfx_path = assets_dir / "audio" / f"sfx_{cp['type']}.wav"
                if sfx_path.exists():
                    try:
                        sfx_clip = AudioFileClip(str(sfx_path))
                        sfx_start = max(0.0, cp['time'] - 0.25)
                        sfx_clip = sfx_clip.with_start(sfx_start).with_volume_scaled(0.3)
                        audio_clips.append(sfx_clip)
                    except Exception as sfx_err:
                        print(f"[AudioMixer Warning] Failed to mix SFX: {sfx_err}")
