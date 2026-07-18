with open("worker/services/media_service.py", "r", encoding="utf-8") as f:
    for i, line in enumerate(f):
        if "top_clip" in line or "bottom_clip" in line:
            ascii_line = line.strip().encode("ascii", "ignore").decode("ascii")
            print(f"{i+1}: {ascii_line}")
