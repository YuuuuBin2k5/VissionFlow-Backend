import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

os.environ["ENVIRONMENT"] = "development"
assert os.environ.get("DATABASE_URL"), "DATABASE_URL is required"
assert os.environ.get("GEMINI_API_KEY"), "GEMINI_API_KEY is required"
assert os.environ.get("PEXELS_API_KEY"), "PEXELS_API_KEY is required"

sys.path.insert(0, os.path.abspath("worker"))
sys.path.insert(0, os.path.abspath("services/control-plane"))

from sqlalchemy.orm import Session
from app.infrastructure.database import get_engine
from start_render_worker import process_workflow

engine = get_engine()
with Session(engine) as session:
    wf_id = "0b26b772-43a7-4e94-bdb3-f5414eaa2fba"
    print(f"🎬 Processing render for workflow: {wf_id}")
    process_workflow(wf_id, session)
