import json
from pathlib import Path

import numpy as np

from worker.config import ASSETS_DIR, MUSIC_VIRAL_MAX_DURATION, MUSIC_VIRAL_MIN_DURATION


class AudioSignalService:
    def _load_librosa(self):
        try:
            import librosa
            return librosa
        except ImportError as exc:
            raise RuntimeError(
                "Missing audio-reactive dependencies. Install librosa, scipy, and soundfile from worker/requirements.txt."
            ) from exc

    def extract_audio_reactive_data(self, audio_path: str, fps: int = 24) -> dict:
        librosa = self._load_librosa()
        y, sr = librosa.load(audio_path, sr=22050, mono=True)
        hop_length = max(1, int(sr / fps))
        stft = np.abs(librosa.stft(y, hop_length=hop_length))
        freqs = librosa.fft_frequencies(sr=sr)
        duration = float(librosa.get_duration(y=y, sr=sr))

        def band_energy(low: float, high: float) -> list:
            mask = (freqs >= low) & (freqs <= high)
            if not np.any(mask):
                return [0.0] * stft.shape[1]
            energy = np.mean(stft[mask, :], axis=0)
            max_value = float(np.max(energy)) if len(energy) else 0.0
            if max_value > 0:
                energy = energy / max_value
            return np.clip(energy, 0.0, 1.0).astype(float).tolist()

        rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop_length)[0]
        onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)
        frame_times = librosa.frames_to_time(np.arange(len(onset)), sr=sr, hop_length=hop_length)
        beat_times = self._detect_beat_times(librosa, y, sr)
        onset_events = self._detect_onset_events(onset, frame_times)
        cut_events = self._build_cut_events(onset_events, beat_times, duration)
        drop_events = self._build_drop_events(onset_events, rms, frame_times)

        return {
            "fps": fps,
            "duration": duration,
            "bass": band_energy(20, 250),
            "mid": band_energy(250, 4000),
            "treble": band_energy(4000, 10000),
            "beat_events": beat_times,
            "onset_events": onset_events,
            "cut_events": cut_events,
            "drop_events": drop_events,
        }

    def _detect_beat_times(self, librosa, y: np.ndarray, sr: int) -> list:
        try:
            _, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
            return [round(float(t), 3) for t in librosa.frames_to_time(beat_frames, sr=sr).astype(float).tolist()]
        except Exception:
            return []

    def _detect_onset_events(self, onset: np.ndarray, frame_times: np.ndarray) -> list:
        if len(onset) == 0:
            return []
        normalized = onset / (np.max(onset) or 1.0)
        threshold = max(0.42, float(np.percentile(normalized, 88)))
        candidates = []
        for index in range(1, len(normalized) - 1):
            value = float(normalized[index])
            if value >= threshold and value >= normalized[index - 1] and value >= normalized[index + 1]:
                candidates.append({"time": round(float(frame_times[index]), 3), "strength": round(value, 4)})
        candidates.sort(key=lambda item: item["strength"], reverse=True)
        return sorted(candidates[:80], key=lambda item: item["time"])

    def _build_cut_events(self, onset_events: list, beat_times: list, duration: float) -> list:
        source_events = onset_events or [{"time": beat_time, "strength": 0.5} for beat_time in beat_times]
        cuts = []
        last_cut = -10.0
        for event in sorted(source_events, key=lambda item: item.get("time", 0.0)):
            time_value = float(event.get("time", 0.0))
            if time_value < 0.7 or time_value > duration - 0.5:
                continue
            gap = time_value - last_cut
            if gap < 1.2:
                continue
            if gap > 3.5 and cuts:
                bridged = min(duration - 0.5, last_cut + 3.2)
                if bridged - last_cut >= 1.2:
                    cuts.append({"time": round(bridged, 3), "strength": 0.35, "type": "bridge"})
                    last_cut = bridged
            cuts.append({"time": round(time_value, 3), "strength": float(event.get("strength", 0.5)), "type": "onset"})
            last_cut = time_value
        return cuts[:32]

    def _build_drop_events(self, onset_events: list, rms: np.ndarray, frame_times: np.ndarray) -> list:
        if len(rms) == 0:
            return []
        normalized_rms = rms / (np.max(rms) or 1.0)
        drops = []
        for event in onset_events:
            time_value = float(event.get("time", 0.0))
            frame_index = int(np.searchsorted(frame_times, time_value))
            frame_index = min(max(0, frame_index), len(normalized_rms) - 1)
            bass_proxy = float(normalized_rms[frame_index])
            strength = float(event.get("strength", 0.0))
            if strength >= 0.72 or (strength >= 0.58 and bass_proxy >= 0.68):
                drops.append({
                    "time": round(time_value, 3),
                    "strength": round(max(strength, bass_proxy), 4),
                    "type": "drop",
                })
        return drops[:24]

    def select_viral_segment(
        self,
        audio_path: str,
        target_duration: float = 30.0,
        advisor_hint: dict | None = None,
        min_duration: float = MUSIC_VIRAL_MIN_DURATION,
        max_duration: float = MUSIC_VIRAL_MAX_DURATION,
    ) -> dict:
        """
        Chọn đoạn có khả năng viral dựa trên năng lượng RMS/onset/beat.
        Đây là tín hiệu từ chính file audio người dùng cung cấp, không phụ thuộc nguồn ngoài.
        """
        librosa = self._load_librosa()
        y, sr = librosa.load(audio_path, sr=22050, mono=True)
        duration = float(librosa.get_duration(y=y, sr=sr))
        if duration <= 0:
            raise RuntimeError("Audio file is empty or unreadable.")

        min_duration = min(max(1.0, min_duration), duration)
        max_duration = min(max(min_duration, max_duration), duration)
        target_duration = min(max(min_duration, target_duration), max_duration)

        hop_length = 512
        rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop_length)[0]
        onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)
        energy = rms / (np.max(rms) or 1.0)
        onset_energy = onset / (np.max(onset) or 1.0)
        combined = (energy * 0.72) + (onset_energy[: len(energy)] * 0.28)
        frame_times = librosa.frames_to_time(np.arange(len(combined)), sr=sr, hop_length=hop_length)
        frame_step = float(frame_times[1] - frame_times[0]) if len(frame_times) > 1 else 0.023

        if duration <= min_duration + 2.0:
            start = 0.0
            end = duration
            selection_method = "full_audio_short_source"
        elif advisor_hint:
            start, end = self._segment_from_advisor_hint(
                advisor_hint=advisor_hint,
                duration=duration,
                combined_energy=combined,
                frame_times=frame_times,
                min_duration=min_duration,
                max_duration=max_duration,
            )
            selection_method = "gemini_hint_energy_extended"
        else:
            window_frames = max(1, int(target_duration / frame_step))
            skip_intro_s = min(8.0, max(0.0, duration - target_duration))
            best_score = -1.0
            best_index = 0
            for index in range(0, max(1, len(combined) - window_frames)):
                start_time = float(frame_times[index])
                if start_time < skip_intro_s:
                    continue
                end_time = start_time + target_duration
                if end_time > duration:
                    break
                window = combined[index:index + window_frames]
                score = float(np.mean(window) + np.percentile(window, 90) * 0.35)
                if score > best_score:
                    best_score = score
                    best_index = index
            start = float(frame_times[best_index])
            end = min(duration, start + target_duration)
            start, end = self._extend_while_hook_continues(start, end, duration, combined, frame_times, max_duration)
            selection_method = "energy_onset_peak_extended"

        try:
            tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
            beat_times = librosa.frames_to_time(beat_frames, sr=sr).astype(float).tolist()
        except Exception:
            tempo = 100.0
            beat_times = []

        return {
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 3),
            "source_duration": round(duration, 3),
            "detected_bpm": round(float(np.asarray(tempo).mean()), 2),
            "beat_times": [round(t - start, 3) for t in beat_times if start <= t <= end],
            "selection_method": selection_method,
            "gemini_hint": advisor_hint,
        }

    def _segment_from_advisor_hint(
        self,
        advisor_hint: dict,
        duration: float,
        combined_energy: np.ndarray,
        frame_times: np.ndarray,
        min_duration: float,
        max_duration: float,
    ) -> tuple[float, float]:
        hint_start = max(0.0, min(float(advisor_hint.get("start", 0.0)), duration))
        hint_end = max(hint_start, min(float(advisor_hint.get("end", hint_start + min_duration)), duration))
        peak_start = max(hint_start, min(float(advisor_hint.get("peak_start", hint_start)), duration))
        peak_end = max(peak_start, min(float(advisor_hint.get("peak_end", hint_end)), duration))

        start = min(hint_start, peak_start)
        end = max(hint_end, peak_end)
        if end - start < min_duration:
            center = (peak_start + peak_end) / 2 if peak_end > peak_start else (start + end) / 2
            start = max(0.0, center - (min_duration / 2))
            end = min(duration, start + min_duration)
            start = max(0.0, end - min_duration)

        if end - start > max_duration:
            center = (peak_start + peak_end) / 2 if peak_end > peak_start else (start + end) / 2
            start = max(0.0, center - (max_duration / 2))
            end = min(duration, start + max_duration)
            start = max(0.0, end - max_duration)

        return self._extend_while_hook_continues(start, end, duration, combined_energy, frame_times, max_duration)

    def _extend_while_hook_continues(
        self,
        start: float,
        end: float,
        duration: float,
        combined_energy: np.ndarray,
        frame_times: np.ndarray,
        max_duration: float,
    ) -> tuple[float, float]:
        if len(combined_energy) < 3:
            return start, end

        current_mask = (frame_times >= start) & (frame_times <= end)
        current_energy = combined_energy[current_mask]
        if len(current_energy) == 0:
            return start, end

        threshold = max(0.28, float(np.percentile(current_energy, 58)) * 0.82)
        step = 1.5
        while end + step <= duration and end - start + step <= max_duration:
            next_mask = (frame_times >= end) & (frame_times < end + step)
            next_energy = combined_energy[next_mask]
            if len(next_energy) == 0 or float(np.mean(next_energy)) < threshold:
                break
            end += step

        return round(start, 3), round(min(duration, end), 3)

    def trim_audio_segment(self, audio_path: str, job_id: int, segment: dict) -> str:
        import soundfile as sf

        librosa = self._load_librosa()
        start = float(segment.get("start", 0.0))
        duration = float(segment.get("duration", 30.0))
        y, sr = librosa.load(audio_path, sr=44100, mono=False, offset=start, duration=duration)
        output_path = Path(ASSETS_DIR) / f"music_segment_{job_id}.wav"
        sf.write(output_path, y.T if getattr(y, "ndim", 1) > 1 else y, sr)
        return str(output_path)

    def build_caption_timeline(self, caption: str, segment: dict) -> list:
        base_phrases = [
            caption,
            "Giữ lại khoảnh khắc này",
            "Một đoạn nhạc chạm đúng cảm xúc",
            "Để giai điệu tự kể chuyện",
            "Replay nếu đoạn này cũng chạm vào bạn",
        ]
        phrases = []
        seen = set()
        for phrase in base_phrases:
            clean = " ".join(str(phrase or "").split()).strip()
            if clean and clean.lower() not in seen:
                phrases.append(clean[:72])
                seen.add(clean.lower())

        duration = float(segment.get("duration", 30.0))
        beat_times = [float(t) for t in segment.get("beat_times", []) if 0 <= float(t) <= duration]
        if len(beat_times) < 6:
            step = max(3.2, duration / 6)
            starts = list(np.arange(0.4, max(0.5, duration - 1.2), step))
        else:
            starts = beat_times[::max(2, int(len(beat_times) / 6))][:6]

        timeline = []
        for idx, start in enumerate(starts[:6]):
            end = starts[idx + 1] - 0.18 if idx + 1 < len(starts[:6]) else min(duration, start + 4.0)
            if end <= start:
                end = min(duration, start + 2.8)
            timeline.append({
                "start": round(float(start), 3),
                "end": round(float(end), 3),
                "text": phrases[idx % len(phrases)],
            })
        return timeline

    def extract_to_json(self, audio_path: str, job_id: int, fps: int = 24) -> str:
        data = self.extract_audio_reactive_data(audio_path, fps=fps)
        output_path = Path(ASSETS_DIR) / f"audio_reactive_{job_id}.json"
        output_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return str(output_path)
