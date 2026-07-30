import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

os.environ["ENVIRONMENT"] = "development"
os.environ["DATABASE_URL"] = "postgresql://neondb_owner:npg_Di3nJLmsh5cB@ep-green-salad-aoq7advi-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
os.environ["GEMINI_API_KEY"] = "AIzaSyCNu2LQSzyBW6ACixl1D6SLy07_vdeu0ho"
os.environ["PEXELS_API_KEY"] = "j3CIlOLR1RdRejkZPi56CCmJALu9axEyFjik0U77W3semlJtXFpMqgVp"

sys.path.insert(0, os.path.abspath("worker"))
sys.path.insert(0, os.path.abspath("services/control-plane"))

from sqlalchemy.orm import Session
from app.infrastructure.database import get_engine
from start_render_worker import process_workflow

engine = get_engine()
with Session(engine) as session:
    wf_id = "0b551143-eaac-407a-9e44-8d0c7fd9c744"
    print(f"🎬 Processing local render for workflow: {wf_id}")
    process_workflow(wf_id, session)
