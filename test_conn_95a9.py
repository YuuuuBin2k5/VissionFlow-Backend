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
import requests

engine = create_engine(os.environ["DATABASE_URL"])
conn_id = uuid.UUID("95a928dc-fe24-4c5b-9cb3-2afef3e6fc09")

with Session(engine) as session:
    conn = session.scalar(select(PublisherConnection).where(PublisherConnection.id == conn_id))
    print("Testing connection:", conn.id)
    cipher = PublisherTokenCipher.from_env()
    try:
        dec = cipher.decrypt(conn.encrypted_refresh_token)
        print("Decrypted token successfully! Prefix:", dec[:15])
        
        # Test refreshing access token with Google
        client_id = os.getenv("VISIONFLOW_YOUTUBE_CLIENT_ID")
        client_secret = os.getenv("VISIONFLOW_YOUTUBE_CLIENT_SECRET")
        resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": dec,
                "grant_type": "refresh_token",
            },
            timeout=10,
        )
        print("Google OAuth Response Status:", resp.status_code)
        print("Google OAuth Response Data:", resp.json() if resp.status_code == 200 else resp.text)
    except Exception as e:
        print("Error:", e)
