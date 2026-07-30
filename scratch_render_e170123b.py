import os
import sys
import json
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Environment Setup
os.environ["ENVIRONMENT"] = "development"
os.environ["DATABASE_URL"] = "postgresql://neondb_owner:npg_Di3nJLmsh5cB@ep-green-salad-aoq7advi-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
os.environ["GEMINI_API_KEY"] = "AIzaSyCNu2LQSzyBW6ACixl1D6SLy07_vdeu0ho"
os.environ["PEXELS_API_KEY"] = "j3CIlOLR1RdRejkZPi56CCmJALu9axEyFjik0U77W3semlJtXFpMqgVp"

sys.path.insert(0, os.path.abspath("worker"))
sys.path.insert(0, os.path.abspath("services/control-plane"))

from worker.services.asset_service import AssetService
from worker.services.visionflow_tts import VisionFlowTts
from worker.domain.render_workspace import RenderWorkspace
from worker.services.media_service import MediaService

print("=======================================================")
print("🎬 STARTING LOCAL VIDEO RENDER FOR WORKFLOW e170123b")
print("=======================================================")

from sqlalchemy.orm import Session
from app.infrastructure.database import get_engine
from app.infrastructure.models import WorkflowRun, VideoProject, CreativeSession

engine = get_engine()
with Session(engine) as session:
    wf = session.get(WorkflowRun, "e170123b-26c7-4f32-b541-9992d0e48182")
    proj = session.get(VideoProject, wf.project_id)
    session_id = wf.input_payload.get("session_id")
    cs = session.get(CreativeSession, session_id) if session_id else None

    prompt_manifest = wf.prompt_manifest or {}
    script = prompt_manifest.get("script", "Nội dung video ngắn tự động")
    scenes = prompt_manifest.get("scenes", [])
    
    print(f"\n[1/4] Synthesizing TTS Audio & Word Timestamps...")
    tts = VisionFlowTts()
    workspace_root = Path("worker/workspace_temp")
    workspace = RenderWorkspace(workspace_root, str(wf.id)).create()
    
    speech = tts.synthesize(script=script, voice_code="vi-VN-NamMinhNeural", workspace=workspace, voice_rate=1.12)
    print(f"✅ Audio generated: {speech.audio_path}")
    
    print(f"\n[2/4] Fetching AI & Stock Video Background Assets ({len(scenes)} scenes)...")
    asset_svc = AssetService()
    bg_paths = []
    for i, scene in enumerate(scenes, start=1):
        kw = scene.get("visual_search_keywords", "aesthetic vertical")
        src = scene.get("asset_source", "fal_ai")
        print(f"  Scene {i}: Keywords='{kw}' Source='{src}'")
        bg_file = asset_svc.get_scene_asset(
            keywords=kw,
            scene_id=i,
            prefer_ai=(src == "fal_ai"),
            mascot_profile={"name": "Cappy Para", "current_costume": "ancient_scholar"},
            emotion="curious",
            style_preset="cozy_anime_3d"
        )
        bg_paths.append(bg_file)
        print(f"  ✓ Asset {i}: {bg_file}")

    print(f"\n[3/4] Rendering Final Video with Captions, BGM & Transitions...")
    media_svc = MediaService()
    output_video_path = media_svc.render_final_video(
        scenes_layout=scenes,
        word_timestamps=speech.word_timestamps,
        voice_audio_path=speech.audio_path,
        background_video_paths=bg_paths,
        workspace_path=str(workspace.path),
        visual_style_plan={
            "show_title_banner": True,
            "title_banner_style": "news",
            "title_text": proj.title,
            "caption_preset": "cinematic_quote",
            "caption_color": "#FFFF00",
            "enable_progress_bar": True,
            "enable_follow_cta": True,
            "logo_handle": "Góc Chiêm Nghiệm | YuuBin",
            "logo_position": "top_left",
        },
        full_voice_script=script,
    )
    
    print(f"\n=======================================================")
    print(f"🎉 LOCAL VIDEO RENDER SUCCESSFUL!")
    print(f"📹 Final Rendered Video Path: {output_video_path}")
    print(f"=======================================================")
    
    # Update workflow state in DB
    wf.state = "ASSETS_READY"
    session.commit()
    print("✅ Workflow e170123b state updated to ASSETS_READY in DB!")
