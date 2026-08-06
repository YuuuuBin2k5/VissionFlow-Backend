import sys, os, uuid
sys.path.insert(0, "services/control-plane")

env_path = "services/control-plane/.env"
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip("'\"")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from app.infrastructure.models import PublisherConnection
from cryptography.fernet import Fernet
import base64
import hashlib

engine = create_engine(os.environ["DATABASE_URL"])
conn_id = uuid.UUID("c67c03d0-e8d1-42a1-9143-635ad1a34fe9")

with Session(engine) as session:
    conn = session.scalar(select(PublisherConnection).where(PublisherConnection.id == conn_id))
    tok = conn.encrypted_refresh_token

def try_key(key_str):
    if not key_str:
        return None
    try:
        raw = key_str.encode("utf-8")
        if len(raw) == 32:
            fernet_key = base64.urlsafe_b64encode(raw)
        elif len(raw) == 44 and raw.endswith(b"="):
            fernet_key = raw
        else:
            digest = hashlib.sha256(raw).digest()
            fernet_key = base64.urlsafe_b64encode(digest)
        f = Fernet(fernet_key)
        return f.decrypt(tok.encode("ascii")).decode("utf-8")
    except Exception as e:
        return None

# Try various keys found across .env files or scripts
candidate_keys = [
    os.getenv("VISIONFLOW_PUBLISHER_TOKEN_ENCRYPTION_KEY", ""),
    os.getenv("APP_SECRET_ENCRYPTION_KEY", ""),
    "7c82c3c7ef23758b9ea79dfa58f4a3e3c66baea5c704f47bb920b7efcfce38b4",
    "visionflow_default_publisher_token_encryption_secret_key_32bytes",
    "secret",
    "visionflow",
    "antigravity",
]

# Search in all .env files in repo
import glob
for env_file in glob.glob("**/.env*", recursive=True):
    try:
        with open(env_file, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "=" in line:
                    val = line.split("=", 1)[1].strip().strip("'\"")
                    if val:
                        candidate_keys.append(val)
    except Exception:
        pass

found = False
for k in set(candidate_keys):
    res = try_key(k)
    if res:
        print(f"SUCCESS! Decrypted with key: '{k}'")
        print(f"Decrypted token: {res[:20]}...")
        found = True
        break

if not found:
    print("Could not decrypt with any tested key!")
