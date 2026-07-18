import os
from pathlib import Path

workspace_root = Path("d:/Folder_Learning_2025_2026/MyProject_DuAnCaNhan/AgentBot")
for root, dirs, files in os.walk(workspace_root):
    if "node_modules" in root or ".git" in root or "chrome_profile" in root:
        continue
    for f in files:
        if f.endswith(".log") or "pm2" in f or "nodemon" in f:
            print(os.path.join(root, f))
