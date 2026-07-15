import os
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
        Tự động giảm âm lượng nhạc nền (Auto-Ducking) trong khi nói.
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

    def mix_audio_tracks(self, voice_audio_path: str, background_music_path: str, total_duration: float, word_timestamps: list, assets_dir: Path, cut_points: list = None) -> CompositeAudioClip:
        """
        Hòa âm phối khí: Giọng thoại + BGM (ducked) + Sóng não 432Hz + SFX Transitions.
        """
        audio_clips = []

        # 1. Giọng thoại chính
        voice_clip = AudioFileClip(voice_audio_path)
        audio_clips.append(voice_clip)

        # 2. Nhạc nền (Auto-Ducking)
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

        return CompositeAudioClip(audio_clips)
