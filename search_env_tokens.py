import glob, os

for path in glob.glob("**/.env*", recursive=True) + glob.glob("../**/.env*", recursive=True):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "YOUTUBE" in line or "TOKEN" in line or "CLIENT" in line or "SECRET" in line:
                    print(f"{path}: {line.strip()[:60]}")
    except Exception:
        pass
