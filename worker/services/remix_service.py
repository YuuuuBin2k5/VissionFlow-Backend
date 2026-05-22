from pathlib import Path

import numpy as np
import soundfile as sf

from worker.config import ASSETS_DIR, REMIX_BASS_GAIN, REMIX_DRUM_GAIN, REMIX_STYLE


class RemixService:
    def __init__(self):
        try:
            import librosa  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "RemixService requires librosa/scipy/soundfile. Run pip install -r worker/requirements.txt."
            ) from exc

    def create_remix(self, audio_path: str, job_id: int, metadata: dict | None = None) -> dict:
        metadata = metadata or {}
        source = Path(audio_path)
        if not source.exists():
            raise RuntimeError(f"Source audio not found for remix: {audio_path}")

        import librosa

        y, sr = librosa.load(str(source), sr=44100, mono=True)
        if y.size == 0:
            raise RuntimeError("Source audio is empty.")

        detected_bpm = self._detect_bpm(y, sr, metadata)
        style = metadata.get("remix_style") or REMIX_STYLE
        beat_times = self._beat_times(y, sr, detected_bpm)

        bass = self._build_bass_line(len(y), sr, beat_times, detected_bpm, style)
        drums = self._build_drums(len(y), sr, beat_times, style)
        wet = y.astype(np.float32) + (bass * REMIX_BASS_GAIN) + (drums * REMIX_DRUM_GAIN)
        wet = self._normalize(wet)

        # Tránh quét bản quyền tự động (ContentID Shield) bằng cách dãn tần số/tốc độ ngẫu nhiên
        bypass_copyright = metadata.get("bypass_copyright", True)
        if bypass_copyright:
            # Ngẫu nhiên chọn dãn âm thanh nhẹ nhàng từ 1.2% đến 1.8%
            import random
            factor = random.uniform(1.012, 1.018)
            print(f"[RemixService] Applying ContentID Shield (Pitch & Speed shift factor: {factor:.4f})")
            
            # Interpolation tuyến tính siêu tốc bằng numpy
            n_new = int(len(wet) / factor)
            wet = np.interp(
                np.linspace(0, len(wet) - 1, n_new),
                np.arange(len(wet)),
                wet
            ).astype(np.float32)

        output_path = ASSETS_DIR / f"remix_{job_id}.wav"
        sf.write(str(output_path), wet, sr)

        return {
            "source_audio_path": str(source),
            "remix_audio_path": str(output_path),
            "detected_bpm": round(float(detected_bpm), 2),
            "remix_style": style,
            "duration_seconds": round(float(len(wet) / sr), 3),
        }

    def _detect_bpm(self, y, sr, metadata: dict) -> float:
        if metadata.get("bpm"):
            try:
                return max(60.0, min(180.0, float(metadata["bpm"])))
            except (TypeError, ValueError):
                pass

        import librosa

        try:
            tempo = librosa.feature.rhythm.tempo(y=y, sr=sr, aggregate=None)
            value = float(np.median(tempo)) if len(tempo) else 100.0
            return max(70.0, min(160.0, value))
        except Exception:
            return 100.0

    def _beat_times(self, y, sr, bpm: float):
        import librosa

        try:
            _, beat_frames = librosa.beat.beat_track(y=y, sr=sr, bpm=bpm)
            times = librosa.frames_to_time(beat_frames, sr=sr)
            if len(times) >= 4:
                return times
        except Exception:
            pass

        duration = len(y) / sr
        step = 60.0 / bpm
        return np.arange(0.0, duration, step)

    def _build_bass_line(self, length: int, sr: int, beat_times, bpm: float, style: str):
        signal = np.zeros(length, dtype=np.float32)
        base_freq = 48.0 if style == "deep_house" else 55.0
        if style == "lofi_chill":
            base_freq = 43.65

        note_len = int(sr * min(0.32, (60.0 / bpm) * 0.8))
        envelope = np.exp(-np.linspace(0.0, 5.0, max(1, note_len))).astype(np.float32)
        t = np.arange(note_len, dtype=np.float32) / sr
        note = np.sin(2 * np.pi * base_freq * t).astype(np.float32) * envelope

        for index, beat in enumerate(beat_times):
            if index % 2 != 0 and style != "deep_house":
                continue
            start = int(beat * sr)
            end = min(length, start + note_len)
            if start < length and end > start:
                signal[start:end] += note[: end - start]
        return signal

    def _build_drums(self, length: int, sr: int, beat_times, style: str):
        signal = np.zeros(length, dtype=np.float32)
        kick = self._kick(sr)
        snare = self._snare(sr)
        hat = self._hat(sr)

        for index, beat in enumerate(beat_times):
            start = int(beat * sr)
            if index % 4 in (0, 2):
                self._mix_at(signal, kick, start)
            if index % 4 == 2:
                self._mix_at(signal, snare, start)
            if style != "lofi_chill":
                self._mix_at(signal, hat, start + int(sr * 0.12))
        return signal

    def _kick(self, sr: int):
        duration = 0.16
        t = np.linspace(0.0, duration, int(sr * duration), endpoint=False)
        freq = np.linspace(95.0, 42.0, len(t))
        env = np.exp(-t * 24.0)
        return (np.sin(2 * np.pi * freq * t) * env).astype(np.float32)

    def _snare(self, sr: int):
        duration = 0.12
        n = int(sr * duration)
        noise = np.random.default_rng(42).normal(0, 1, n).astype(np.float32)
        env = np.exp(-np.linspace(0.0, 7.0, n)).astype(np.float32)
        return noise * env * 0.35

    def _hat(self, sr: int):
        duration = 0.045
        n = int(sr * duration)
        noise = np.random.default_rng(84).normal(0, 1, n).astype(np.float32)
        env = np.exp(-np.linspace(0.0, 10.0, n)).astype(np.float32)
        return noise * env * 0.18

    def _mix_at(self, target, sample, start: int):
        if start >= len(target):
            return
        start = max(0, start)
        end = min(len(target), start + len(sample))
        if end > start:
            target[start:end] += sample[: end - start]

    def _normalize(self, audio):
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak > 0:
            audio = audio / max(peak, 1.0) * 0.95
        return np.clip(audio, -0.98, 0.98).astype(np.float32)
