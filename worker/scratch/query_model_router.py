with open("worker/services/model_router.py", "r", encoding="utf-8") as f:
    for i, line in enumerate(f):
        if "comment" in line.lower() or "seo_tags_metadata" in line.lower():
            ascii_line = line.strip().encode("ascii", "ignore").decode("ascii")
            print(f"{i+1}: {ascii_line}")
