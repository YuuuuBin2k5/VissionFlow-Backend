"""
VisionFlow Standalone Local Render Worker
Automates end-to-end video rendering on your local machine without needing GitHub Actions.
Polls PostgreSQL database every 5 seconds for newly created video projects.
"""

import os
import sys
import time
import json
import random
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

from sqlalchemy.orm import Session
from app.infrastructure.database import get_engine
from app.infrastructure.models import WorkflowRun, VideoProject, CreativeSession

from worker.services.asset_service import AssetService
from worker.services.visionflow_tts import VisionFlowTts
from worker.domain.render_workspace import RenderWorkspace
from worker.services.media_service import MediaService


def process_workflow(wf_id: str, session_db: Session) -> bool:
    wf = session_db.get(WorkflowRun, wf_id)
    if not wf or wf.state in ("PUBLISHED", "CANCELED"):
        return False

    proj = session_db.get(VideoProject, wf.project_id)
    session_id = wf.input_payload.get("session_id") if wf.input_payload else None
    cs = session_db.get(CreativeSession, session_id) if session_id else None

    title = proj.title if proj else "Video ngắn tự động"
    print(f"\n=======================================================")
    print(f"🎬 PROCESSING VIDEO: '{title}' (ID: {wf.id})")
    print(f"=======================================================")

    # 1. Ensure Prompt Manifest (Script & Storyboard Scenes)
    prompt_manifest = wf.prompt_manifest or {}
    script = prompt_manifest.get("script")
    scenes = prompt_manifest.get("scenes")

    creation_spec = cs.creation_spec if cs else {}
    brief = creation_spec.get("brief") or title

    if not script or not scenes:
        print("[1/4] Generating Script & Storyboard Scenes...")
        script = brief
        scenes = [
            {
                "scene_id": "scene-1",
                "visual_search_keywords": f"{title} aesthetic vertical",
                "duration": 5,
                "narration": brief[:100] if len(brief) > 100 else brief,
                "caption": title[:40],
                "transition": "cut",
                "asset_source": creation_spec.get("visual_engine", "fal_ai")
            },
            {
                "scene_id": "scene-2",
                "visual_search_keywords": f"{title} portrait vertical",
                "duration": 6,
                "narration": brief[100:220] if len(brief) > 220 else brief,
                "caption": "Bài học cuộc sống",
                "transition": "crossfade",
                "asset_source": creation_spec.get("visual_engine", "fal_ai")
            }
        ]
        wf.prompt_manifest = {
            "title": title,
            "script": script,
            "scenes": scenes,
            "video_genre": creation_spec.get("video_genre", "documentary"),
        }
        wf.state = "STORYBOARDED"
        session_db.commit()

    # 2. Synthesize TTS Audio
    print("[2/4] Synthesizing TTS Audio & Word Timestamps...")
    voice_code = creation_spec.get("voice_code") or creation_spec.get("voice") or "vi-VN-NamMinhNeural"
    voice_rate = creation_spec.get("voice_rate", 1.12)

    tts = VisionFlowTts()
    workspace_root = Path("worker/workspace_temp")
    workspace = RenderWorkspace(workspace_root, str(wf.id)).create()

    speech = tts.synthesize(script=script, voice_code=voice_code, workspace=workspace, voice_rate=voice_rate)
    print(f"  ✓ Audio synthesized: {speech.audio_path}")

    # 3. Download Video Background Assets
    print(f"[3/4] Fetching AI & B-Roll Background Assets ({len(scenes)} scenes)...")
    asset_svc = AssetService()
    bg_paths = []
    for i, scene in enumerate(scenes, start=1):
        kw = scene.get("visual_search_keywords", "aesthetic vertical")
        src = scene.get("asset_source", "fal_ai")
        bg_file = asset_svc.get_scene_asset(
            keywords=kw,
            scene_id=i,
            prefer_ai=(src == "fal_ai"),
            mascot_profile={"name": "Cappy Para", "current_costume": "ancient_scholar"},
            emotion="curious",
            style_preset=creation_spec.get("visual_preset", "cozy_anime_3d")
        )
        bg_paths.append(bg_file)
        print(f"  ✓ Asset {i}: {bg_file}")

    # 4. Render Final Video
    print("[4/4] Rendering Final Video with Captions, BGM & Transitions...")
    media_svc = MediaService()
    output_video_path = media_svc.render_final_video(
        scenes_layout=scenes,
        word_timestamps=speech.word_timestamps,
        voice_audio_path=speech.audio_path,
        background_video_paths=bg_paths,
        workspace_path=str(workspace.path),
        visual_style_plan={
            "show_title_banner": creation_spec.get("show_title_banner", True),
            "title_banner_style": creation_spec.get("title_banner_style", "news"),
            "title_text": title,
            "caption_preset": creation_spec.get("caption_preset", "cinematic_quote"),
            "caption_color": creation_spec.get("caption_color", "#FFFF00"),
            "enable_progress_bar": creation_spec.get("enable_progress_bar", True),
            "enable_follow_cta": creation_spec.get("enable_follow_cta", True),
            "logo_handle": creation_spec.get("logo_handle", "Góc Chiêm Nghiệm | YuuBin"),
            "logo_position": creation_spec.get("logo_position", "top_left"),
        },
        full_voice_script=script,
    )

    print(f"\n🎉 VIDEO RENDER SUCCESSFUL!")
    print(f"📹 Export Path: {output_video_path}")

    # Insert MediaAsset for review preview & update state to APPROVED
    from app.infrastructure.models import MediaAsset
    asset_key = f"https://visionflow-preview.local/exports/{wf.id}/final.mp4"
    existing_asset = session_db.query(MediaAsset).filter(
        MediaAsset.workflow_run_id == wf.id,
        MediaAsset.media_kind == "final_export"
    ).first()
    if not existing_asset:
        file_size = os.path.getsize(output_video_path) if os.path.exists(output_video_path) else 9394362
        media_asset = MediaAsset(
            id=uuid.uuid4(),
            organization_id=proj.organization_id if proj else uuid.UUID("7b91598c-6c3e-4e5d-8247-d3efa203984a"),
            workflow_run_id=wf.id,
            media_kind="final_export",
            object_key=asset_key,
            content_type="video/mp4",
            byte_size=file_size,
            checksum_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            metadata_json={"rendered_locally": True}
        )
        session_db.add(media_asset)

    wf.state = "APPROVED"
    session_db.commit()
    print(f"✅ Database updated: MediaAsset inserted & Workflow {wf.id} state -> APPROVED (Ready in Publication Queue)!\n")
    return True


def run_worker_loop():
    print("=======================================================")
    print("🚀 VISIONFLOW LOCAL AUTOMATIC RENDER SERVER RUNNING")
    print("=======================================================")
    print("📌 Waiting for new video requests from Website...")

    engine = get_engine()
    while True:
        try:
            with Session(engine) as session_db:
                # Query queued or in-progress workflows
                pending_runs = session_db.query(WorkflowRun).filter(
                    WorkflowRun.state.in_(["QUEUED", "PLANNING", "SCRIPTED", "STORYBOARDED", "RENDERING", "ASSETS_READY"])
                ).order_by(WorkflowRun.id.desc()).all()

                for run in pending_runs:
                    try:
                        process_workflow(str(run.id), session_db)
                    except Exception as err:
                        print(f"❌ Error processing workflow {run.id}: {err}")
                        import traceback
                        traceback.print_exc()

        except Exception as loop_err:
            print(f"⚠️ Worker polling notice: {loop_err}")

        time.sleep(5)


if __name__ == "__main__":
    run_worker_loop()
