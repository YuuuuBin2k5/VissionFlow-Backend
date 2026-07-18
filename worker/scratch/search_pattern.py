import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

def print_file(filepath: Path, start_line: int = 1, end_line: int = 9999):
    print(f"\n=== Content of {filepath.name} lines {start_line}-{end_line} ===")
    lines = filepath.read_text(encoding="utf-8", errors="ignore").splitlines()
    for idx in range(start_line - 1, min(len(lines), end_line)):
        print(f"{idx+1}: {lines[idx]}")

if __name__ == "__main__":
    src = Path("D:/Folder_Learning_2025_2026/MyProject_DuAnCaNhan/AgentBot/AgentTiktok/services/control-plane")
    print_file(src / "app" / "routers" / "auth.py", 140, 160)
    # Also check legacy_mapping_repository to understand exactly how OutboxEvent is inserted for mapping
    print_file(src / "app" / "infrastructure" / "legacy_mapping_repository.py", 120, 145)
    # Check begin_manual_publish to understand how it emits outbox events
    print_file(src / "app" / "application" / "begin_manual_publish.py", 1, 60)
