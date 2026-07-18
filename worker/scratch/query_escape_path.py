with open("worker/services/media_service.py", "r", encoding="utf-8") as f:
    for i, line in enumerate(f):
        if "def _escape_ffmpeg_path" in line:
            print(f"Found at line: {i+1}")
