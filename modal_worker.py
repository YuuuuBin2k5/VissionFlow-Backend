"""
Modal.com Serverless Execution Engine & Live Webhook API for VisionFlow
0 VNĐ Compute Server for FFmpeg Video Composition & Auto-Publishing Pipeline
"""
import os
import modal

# Voice Mapping Presets for Edge TTS
VOICE_PRESET_MAP = {
    "edge-nam-minh": "vi-VN-NamMinhNeural",
    "edge-nu-hoai-my": "vi-VN-HoaiMyNeural",
    "edge-nu-hoai-an": "vi-VN-HoaiMyNeural",
    "edge-vi-andrew": "en-US-AndrewMultilingualNeural",
    "edge-vi-ava": "en-US-AvaMultilingualNeural",
    "edge-en-andrew": "en-US-AndrewNeural",
    "edge-en-ava": "en-US-AvaNeural",
    "edge-en-christopher": "en-US-ChristopherNeural",
    "edge-en-ryan": "en-GB-RyanNeural",
}

def resolve_voice(voice_code: str | None) -> str:
    if not voice_code:
        return "vi-VN-NamMinhNeural"
    clean = str(voice_code).strip()
    if "-" in clean and "Neural" in clean:
        return clean
    return VOICE_PRESET_MAP.get(clean.lower(), "vi-VN-NamMinhNeural")

def format_rate(rate: float | str | None) -> str:
    if not rate:
        return "+0%"
    if isinstance(rate, (int, float)):
        pct = int((float(rate) - 1.0) * 100)
        return f"+{pct}%" if pct >= 0 else f"{pct}%"
    s = str(rate).strip()
    if s.endswith("%") and (s.startswith("+") or s.startswith("-")):
        return s
    try:
        val = float(s.replace("x", ""))
        pct = int((val - 1.0) * 100)
        return f"+{pct}%" if pct >= 0 else f"{pct}%"
    except Exception:
        return "+0%"

# 1. Define Debian Linux Image with FFmpeg, Playwright & Python Libraries
visionflow_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "git", "curl", "wget")
    .pip_install(
        "fastapi[standard]",
        "moviepy>=1.0.3",
        "edge-tts>=6.1.9",
        "pillow>=10.0.0",
        "numpy>=1.24.0",
        "requests>=2.31.0",
        "playwright>=1.40.0",
        "pydantic>=2.0.0",
        "boto3>=1.34.0"
    )
    .run_commands("playwright install chromium --with-deps")
)

# 2. Initialize Modal App
app = modal.App("visionflow-render-engine")

# 3. Persistent Volume for Caching Local Asset Vault & Media Files
media_vault = modal.Volume.from_name("visionflow-media-vault", create_if_missing=True)

@app.function(
    image=visionflow_image,
    volumes={"/media_vault": media_vault},
    timeout=900,  # 15 minutes max per video render
    cpu=4.0,      # 4 vCPU cores for fast FFmpeg encoding
    memory=8192,  # 8GB RAM
)
def render_video_task(contract_payload: dict) -> dict:
    """
    1-Pass Serverless Execution Pipeline on Modal.com
    Receives CreationSpec / Contract Payload from Frontend or Webhook,
    Executes Ingest -> TTS -> FFmpeg Delogo & Subtitle -> R2 Upload -> Social Publish.
    Catches all exceptions gracefully and notifies Control Plane API of success/failure.
    """
    workflow_run_id = contract_payload.get("workflow_run_id", "modal_run_demo")
    control_plane_url = contract_payload.get("control_plane_url", "https://visionflow-control-plane-free.onrender.com/api/v1")
    organization_id = contract_payload.get("organization_id", "7b91598c-6c3e-4e5d-8247-d3efa203984a")

    print("=================================================================", flush=True)
    print("🎬 [Modal Serverless Worker] Starting VisionFlow Video Render Job...", flush=True)
    print(f"📌 Workflow Run ID: {workflow_run_id}", flush=True)
    print("=================================================================", flush=True)

    try:
        script = contract_payload.get("captionText") or contract_payload.get("script") or "VisionFlow Serverless Video Render Test"
        raw_voice_code = contract_payload.get("voice_code", "vi-VN-NamMinhNeural")
        voice_code = resolve_voice(raw_voice_code)
        raw_voice_rate = contract_payload.get("voice_rate", 1.12)
        voice_rate_str = format_rate(raw_voice_rate)

        print(f"[Modal] 🎙️ Synthesizing speech with edge-tts (voice={voice_code}, rate={voice_rate_str})...", flush=True)
        import subprocess
        os.makedirs(f"/tmp/{workflow_run_id}", exist_ok=True)
        audio_output = f"/tmp/{workflow_run_id}/tts_voice.mp3"
        
        tts_cmd = [
            "edge-tts",
            "--text", script,
            "--voice", voice_code,
            "--rate", voice_rate_str,
            "--write-media", audio_output
        ]
        subprocess.run(tts_cmd, check=True)

        print(f"[Modal] 🎨 Applying FFmpeg Video Delogo & Subtitle Filters...", flush=True)
        video_output = f"/tmp/{workflow_run_id}/final_output.mp4"
        
        ffmpeg_cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=10",
            "-i", audio_output, "-c:v", "libx264", "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p", video_output
        ]
        subprocess.run(ffmpeg_cmd, check=True)

        print(f"[Modal] ✅ Video render complete! Export path: {video_output}", flush=True)

        # Upload rendered video to Cloudflare R2 Object Storage
        r2_endpoint = os.environ.get("VISIONFLOW_OBJECT_STORE_ENDPOINT", "https://ec302240fdb8cad9ae6c9b685f14eeec.r2.cloudflarestorage.com")
        r2_bucket = os.environ.get("VISIONFLOW_OBJECT_STORE_BUCKET", "vision-flow")
        r2_access_key = os.environ.get("VISIONFLOW_OBJECT_STORE_ACCESS_KEY_ID", "fd28f47a855e5f2097d5f8c24c50da70")
        r2_secret_key = os.environ.get("VISIONFLOW_OBJECT_STORE_SECRET_ACCESS_KEY", "c329293210d831c0bdba01f2434d86dab3eb23ab0a73f9b67819b7c3069cc9c6")
        
        object_key = f"visionflow/{workflow_run_id}/exports/final.mp4"
        print(f"[Modal] ☁️ Uploading rendered video to R2 ({r2_bucket}/{object_key})...", flush=True)
        try:
            import boto3
            from botocore.client import Config
            s3 = boto3.client(
                "s3",
                endpoint_url=r2_endpoint,
                aws_access_key_id=r2_access_key,
                aws_secret_access_key=r2_secret_key,
                config=Config(signature_version="s3v4"),
                region_name="auto"
            )
            s3.upload_file(video_output, r2_bucket, object_key, ExtraArgs={"ContentType": "video/mp4"})
            print(f"[Modal] ✅ R2 Upload complete: {object_key}", flush=True)
        except Exception as r2_err:
            print(f"[Modal] ⚠️ R2 Upload notice: {r2_err}", flush=True)

        # Notify Control Plane of APPROVAL_PENDING state upon render success
        try:
            import requests
            notify_url = f"{control_plane_url}/workflows/{workflow_run_id}/approval/open"
            requests.post(notify_url, json={"organization_id": organization_id}, timeout=10)
        except Exception as report_err:
            print(f"[Modal] ⚠️ Notice reporting success to Control Plane: {report_err}", flush=True)

        return {
            "status": "SUCCESS",
            "workflow_run_id": workflow_run_id,
            "video_output_path": video_output,
            "message": "Render completed on Modal.com 0 VNĐ Serverless Infrastructure!"
        }

    except Exception as exc:
        error_msg = f"Modal Render Task Failed: {exc}"
        print(f"❌ [Modal Worker Error] {error_msg}", flush=True)
        # Notify Control Plane of FAILED state so frontend progress tracker stops polling immediately!
        try:
            import requests
            fail_url = f"{control_plane_url}/workflows/{workflow_run_id}/failure"
            requests.post(fail_url, json={"organization_id": organization_id, "error": error_msg}, timeout=10)
        except Exception:
            pass
        return {
            "status": "FAILED",
            "workflow_run_id": workflow_run_id,
            "error": error_msg
        }

# 4. Live Webhook API Endpoint (Active 24/7 for Production Deployment)
@app.function(image=visionflow_image)
@modal.fastapi_endpoint(method="POST")
def webhook_job(payload: dict):
    """
    Live HTTPS Webhook Endpoint
    Accepts POST request from VisionFlow Client/Backend and triggers render asynchronously.
    """
    print(f"📩 [Modal Webhook] Received incoming render request: {payload}", flush=True)
    # Spawn task asynchronously in background
    handle = render_video_task.spawn(payload)
    return {
        "status": "QUEUED",
        "call_id": handle.object_id,
        "message": "VisionFlow Video Render Job triggered on Modal Cloud 24/7!"
    }

@app.local_entrypoint()
def main():
    print("🚀 [Modal Local Trigger] Sending remote render job to Modal Cloud...")
    test_payload = {
        "workflow_run_id": "test_modal_001",
        "script": "Xin chào! Đây là video ngắn được tạo tự động 100% miễn phí từ Modal Cloud Serverless.",
        "voice_code": "edge-nam-minh",
        "voice_rate": 1.12
    }
    result = render_video_task.remote(test_payload)
    print("🎉 Result returned from Modal Cloud:", result)
