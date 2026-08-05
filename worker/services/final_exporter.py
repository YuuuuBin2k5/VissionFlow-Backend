import os
import gc
import subprocess
from pathlib import Path
from worker.services.cockpit_bridge import update_task_progress

try:
    from proglog import ProgressBarLogger
    class CockpitMoviePyLogger(ProgressBarLogger):
        def __init__(self, task_id: str):
            super().__init__()
            self.task_id = task_id
            self.last_pct = -1

        def callback(self, **changes):
            bars = self.state.get("bars", {})
            if "t" in bars:
                bar = bars["t"]
                if bar["total"] > 0:
                    pct = int((bar["index"] / bar["total"]) * 100)
                    if pct != self.last_pct and pct % 5 == 0:
                        self.last_pct = pct
                        update_task_progress(self.task_id, "COMPOSITING", pct)
except ImportError:
    class CockpitMoviePyLogger:
        def __init__(self, task_id: str):
            pass

class FinalExporter:
    def __init__(self):
        pass

    def mutate_file_hash(self, file_path: str):
        """
        Ghi đè một byte rác ngẫu nhiên vào cuối file để thay đổi mã băm MD5 hoàn toàn (Anti-Reused Content).
        """
        if not file_path or not os.path.exists(file_path):
            return
        try:
            import random
            with open(file_path, "ab") as f:
                f.write(bytes([random.randint(0, 255)]))
            print(f"[FinalExporter] Scrambled MD5 hash successfully for: {file_path}")
        except Exception as e:
            print(f"[FinalExporter Warning] Failed to modify file MD5 checksum: {e}")

    def export_video(self, final_video_clip, output_path: str, job_id: int, temp_audio_path: str) -> str:
        """
        Đóng gói và kết xuất video ra file .mp4 chất lượng cao sử dụng libx264 và aac.
        """
        logger = CockpitMoviePyLogger(str(job_id))

        try:
            update_task_progress(str(job_id), "COMPOSITING", 0)
            final_video_clip.write_videofile(
                output_path,
                fps=24,
                codec="libx264",
                audio_codec="aac",
                temp_audiofile=temp_audio_path,
                remove_temp=False,
                logger=logger,
                preset="ultrafast",
                threads=4,
            )
            update_task_progress(str(job_id), "READY", 100)

            # Thay đổi mã băm MD5 để tránh nhận diện trùng lặp
            self.mutate_file_hash(output_path)

            return output_path
        except Exception as e:
            # Giải phóng RAM khi có sự cố tràn bộ nhớ
            gc.collect()
            raise e

    def export_visionflow_video(self, final_video_clip, output_path: str, temp_audio_path: str) -> str:
        """Export without legacy job progress or MySQL-facing telemetry."""
        try:
            gc.collect()
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            final_video_clip.write_videofile(
                output_path, fps=24, codec="libx264", audio_codec="aac",
                temp_audiofile=temp_audio_path, remove_temp=False, logger=None,
                preset="ultrafast", threads=4,
            )
            # Safe cleanup for Windows file locks
            if temp_audio_path and os.path.exists(temp_audio_path):
                try:
                    os.remove(temp_audio_path)
                except Exception as clean_err:
                    print(f"[FinalExporter Notice] Temp audio cleanup deferred: {clean_err}")
            return output_path
        except Exception:
            gc.collect()
            raise
