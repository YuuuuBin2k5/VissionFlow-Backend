import os
import glob

files = glob.glob("**/*.env*", recursive=True)
for f in files:
    try:
        with open(f, 'r', encoding='utf-8', errors='ignore') as fp:
            for line in fp:
                if 'REDIS' in line:
                    print(f"{f}: {line.strip()}")
    except Exception:
        pass
