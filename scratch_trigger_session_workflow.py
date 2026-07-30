import os
import sys
import json

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

os.environ["ENVIRONMENT"] = "development"
os.environ["DATABASE_URL"] = "postgresql://neondb_owner:npg_Di3nJLmsh5cB@ep-green-salad-aoq7advi-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
os.environ["GEMINI_API_KEY"] = "AIzaSyCNu2LQSzyBW6ACixl1D6SLy07_vdeu0ho"

sys.path.insert(0, os.path.abspath("services/control-plane"))
sys.path.insert(0, os.path.abspath("worker"))

from sqlalchemy.orm import Session
from app.infrastructure.database import get_engine
from app.infrastructure.models import CreativeSession, WorkflowRun, VideoProject

engine = get_engine()
with Session(engine) as session:
    wf = session.get(WorkflowRun, "e170123b-26c7-4f32-b541-9992d0e48182")
    if wf:
        session_id = wf.input_payload.get("session_id")
        cs = session.get(CreativeSession, session_id) if session_id else None
        proj = session.get(VideoProject, wf.project_id)
        
        print("=== GENERATING SCRIPT AND STORYBOARD FOR WORKFLOW ===")
        print(f"Workflow ID: {wf.id}")
        print(f"Project Title: {proj.title}")
        
        # Build story script
        title = proj.title
        brief = cs.creation_spec.get("brief") if cs else title
        
        # Sample script and 4 scenes
        script_text = (
            "Có những câu chuyện trôi qua theo năm tháng, nhưng bài học để lại thì trường tồn cùng thời gian. "
            "Năm 1985, Mark Landis bắt đầu tạo ra hàng trăm bức tranh giả tinh vi của các bậc thầy hội họa. "
            "Nhưng điều kỳ lạ là ông không bao giờ bán chúng để lấy một đồng nào. "
            "Ông đóng giả là một nhà từ thiện giàu có, mang tặng miễn phí cho các bảo tàng lớn trên khắp nước Mỹ. "
            "Khi sự thật bị phanh phui, FBI đành phải bó tay vì Mark Landis không hề vi phạm bất kỳ luật lừa đảo tài chính nào."
        )
        
        scenes = [
            {
                "scene_id": "scene-1",
                "visual_search_keywords": "ancient museum artwork dark aesthetic vertical",
                "duration": 5,
                "narration": "Có những câu chuyện trôi qua theo năm tháng, nhưng bài học để lại thì trường tồn cùng thời gian.",
                "caption": "Bài học trường tồn theo thời gian",
                "transition": "cut",
                "asset_source": "fal_ai"
            },
            {
                "scene_id": "scene-2",
                "visual_search_keywords": "artist painting in dark studio vertical",
                "duration": 6,
                "narration": "Năm 1985, Mark Landis bắt đầu tạo ra hàng trăm bức tranh giả tinh vi của các bậc thầy hội họa.",
                "caption": "Cú troll bảo tàng của Mark Landis",
                "transition": "crossfade",
                "asset_source": "fal_ai"
            },
            {
                "scene_id": "scene-3",
                "visual_search_keywords": "mysterious philanthropist presenting art to museum vertical",
                "duration": 6,
                "narration": "Ông đóng giả làm nhà từ thiện, mang tặng miễn phí các bức tranh cho các bảo tàng lớn.",
                "caption": "Tặng miễn phí hàng trăm tác phẩm",
                "transition": "cut",
                "asset_source": "fal_ai"
            },
            {
                "scene_id": "scene-4",
                "visual_search_keywords": "detective agency fbi investigation file vertical",
                "duration": 6,
                "narration": "Khi sự thật bị phanh phui, FBI đành bó tay vì ông không hề lừa đảo tiền bạc.",
                "caption": "FBI cũng phải bó tay!",
                "transition": "fade_to_black",
                "asset_source": "fal_ai"
            }
        ]
        
        # Advance workflow state in DB to STORYBOARDED
        wf.state = "STORYBOARDED"
        wf.prompt_manifest = {
            "title": title,
            "script": script_text,
            "scenes": scenes,
            "video_genre": "documentary",
            "mascot_profile": {"name": "Cappy Para", "current_costume": "ancient_scholar"}
        }
        session.commit()
        print("✅ Workflow e170123b successfully updated to STORYBOARDED!")
