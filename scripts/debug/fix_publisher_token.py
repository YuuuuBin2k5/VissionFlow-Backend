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
from app.core.publisher_token_cipher import PublisherTokenCipher

raw_token = os.environ["YOUTUBE_REFRESH_TOKEN"]
if not raw_token.strip():
    raise RuntimeError("YOUTUBE_REFRESH_TOKEN is required")
cipher = PublisherTokenCipher.from_env()
encrypted = cipher.encrypt(raw_token)

engine = create_engine(os.environ["DATABASE_URL"])
conn_id = uuid.UUID("c67c03d0-e8d1-42a1-9143-635ad1a34fe9")

with Session(engine) as session:
    conn = session.scalar(select(PublisherConnection).where(PublisherConnection.id == conn_id))
    if conn:
        conn.encrypted_refresh_token = encrypted
        conn.status = "active"
        session.commit()
        print("Updated publisher_connections:", conn_id)
        print("Status:", conn.status)
        print("Verify decryption:", cipher.decrypt(conn.encrypted_refresh_token) == raw_token)
