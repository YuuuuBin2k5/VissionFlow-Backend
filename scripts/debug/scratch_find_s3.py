import os
import glob

files = glob.glob("**/*.env*", recursive=True) + glob.glob("**/config*.py", recursive=True) + glob.glob("**/overlay_uploads.py", recursive=True)
for f in files:
    try:
        with open(f, 'r', encoding='utf-8', errors='ignore') as fp:
            for line in fp:
                if 'OBJECT_STORE' in line or 'BUCKET' in line or 'R2' in line or 'S3' in line:
                    print(f"{f}: {line.strip()}")
    except Exception:
        pass
