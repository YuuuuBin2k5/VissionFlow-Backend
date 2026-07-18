import os
import sys
import asyncio
import subprocess
import json
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from worker.services.lyric_transcription_service import LyricTranscriptionService

async def main():
    video_path = r"D:\Folder_Learning_2025_2026\MyProject_DuAnCaNhan\AgentTiktok\worker\output_videos\dub_source_de192cdc9f2c4e2ebe2fc50508b9c4e6.mp4"
    if not os.path.exists(video_path):
        print(f"Error: Source video not found at {video_path}")
        return

    temp_audio = r"D:\Folder_Learning_2025_2026\MyProject_DuAnCaNhan\AgentTiktok\worker\output_videos\test_125_audio.mp3"
    print("Extracting audio from video...")
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "libmp3lame", "-q:a", "2", temp_audio
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    print(f"Audio extracted to {temp_audio}")

    print("Transcribing audio using Whisper (language=None)...")
    transcriber = LyricTranscriptionService()
    # Now that we fixed lyric_transcription_service.py, passing language=None will trigger auto-detect!
    timeline = transcriber.transcribe_lyrics(temp_audio, language=None)
    
    print(f"Total segments transcribed: {len(timeline)}")
    
    output_log_path = r"D:\Folder_Learning_2025_2026\MyProject_DuAnCaNhan\AgentTiktok\worker\scratch\transcription_result_125.txt"
    with open(output_log_path, "w", encoding="utf-8") as f:
        f.write(f"Total segments transcribed: {len(timeline)}\n")
        f.write("=== RAW TIMELINE SEGMENTS ===\n")
        for idx, seg in enumerate(timeline):
            f.write(f"[{idx}] {seg['start']:.2f}s - {seg['end']:.2f}s (duration: {seg['end']-seg['start']:.2f}s): {seg['text']}\n")
    
    print(f"ASR result successfully saved to {output_log_path}")

    # Clean up temp audio
    if os.path.exists(temp_audio):
        os.remove(temp_audio)

if __name__ == "__main__":
    asyncio.run(main())
