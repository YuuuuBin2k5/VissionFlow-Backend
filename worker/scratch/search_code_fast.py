import os
from pathlib import Path

root_dir = Path("d:/Folder_Learning_2025_2026/MyProject_DuAnCaNhan/AgentBot")
search_paths = [root_dir / "worker/services", root_dir / "worker/scratch", root_dir / "worker/domain", root_dir / "worker/application"]
keywords = ["douyin", "translation", "trans"]

for s_path in search_paths:
    if not s_path.exists():
        continue
    for root, dirs, files in os.walk(s_path):
        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                        for kw in keywords:
                            if kw in content.lower():
                                print(f"Found '{kw}' in {os.path.relpath(file_path, root_dir)}")
                                break
                except Exception:
                    pass
