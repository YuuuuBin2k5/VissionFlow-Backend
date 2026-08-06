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

engine = create_engine(os.environ["DATABASE_URL"])

with Session(engine) as session:
    conns = session.scalars(select(PublisherConnection)).all()
    print(f"Total publisher connections in DB: {len(conns)}")
    for c in conns:
        print(f"\nID: {c.id}")
        print(f"  Org ID: {c.organization_id}")
        print(f"  Provider: {c.provider}")
        print(f"  Account ID: {c.provider_account_id}")
        print(f"  Status: {c.status}")
        print(f"  Token length: {len(c.encrypted_refresh_token) if c.encrypted_refresh_token else 0}")
