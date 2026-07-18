import re
from pathlib import Path

def clean_file(filepath: Path):
    print(f"Cleaning {filepath}...")
    content = filepath.read_text(encoding="utf-8")
    
    # 1. Remove trailing spaces from each line
    lines = content.splitlines()
    cleaned_lines = [line.rstrip() for line in lines]
    
    # 2. Reconstruct content and make sure there is exactly one trailing blank line at EOF
    cleaned_content = "\n".join(cleaned_lines)
    if cleaned_content and not cleaned_content.endswith("\n"):
        cleaned_content += "\n"
        
    filepath.write_text(cleaned_content, encoding="utf-8")
    print(f"Done cleaning {filepath}.")

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    test_dir = root / "tests"
    clean_file(test_dir / "test_narration_handoff.py")
    clean_file(test_dir / "test_visionflow_control_plane_client.py")
