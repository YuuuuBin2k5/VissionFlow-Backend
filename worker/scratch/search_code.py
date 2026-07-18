import os
import re
from pathlib import Path

root_dir = Path("d:/Folder_Learning_2025_2026/MyProject_DuAnCaNhan/AgentBot")
keywords = ["douyin", "trans", "tiktok"]

results = []
for root, dirs, files in os.walk(root_dir):
    if "node_modules" in root or ".git" in root or "chrome_profile" in root:
        continue
    for file in files:
        if file.endswith(".py") or file.endswith(".ts") or file.endswith(".js"):
            file_path = os.path.join(root, file)
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    for kw in keywords:
                        if kw in content.lower():
                            results.append((file_path, kw))
            except Exception:
                pass

print(f"Found {len(results)} matches:")
seen_files = set()
for path, kw in results:
    rel_path = os.path.relpath(path, root_dir)
    if rel_path not in seen_files:
        print(f"- {rel_path} (matched '{kw}')")
        seen_files.add(rel_path)
