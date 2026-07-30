import sys
import os

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.abspath("worker"))

from worker.services.viral_audio_master import master_voice_only

voice_file = "worker/workspace_temp/visionflow/0b551143-eaac-407a-9e44-8d0c7fd9c744/voice.mp3"
out_file = "worker/workspace_temp/visionflow/0b551143-eaac-407a-9e44-8d0c7fd9c744/mastered_test.aac"

if os.path.exists(voice_file):
    print("Testing master_voice_only with modern FFmpeg v7.1...")
    res = master_voice_only(voice_file, out_file)
    print(f"✅ Success! Mastered output saved to: {res}")
else:
    print(f"Voice file not found at {voice_file}")
