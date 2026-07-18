import os
import sys
import subprocess
import json
from pathlib import Path

# Add project root to path
script_dir = Path(__file__).resolve().parent
sys.path.append(str(script_dir.parent.parent))

from worker.services.media_service import MediaService

def get_video_info(path: str):
    try:
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", "-show_format", path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)
        
        video_stream = next(s for s in data["streams"] if s["codec_type"] == "video")
        width = int(video_stream["width"])
        height = int(video_stream["height"])
        duration = float(data["format"]["duration"])
        return width, height, duration
    except Exception as e:
        print(f"Error reading video info: {e}")
        return None

def test_verified_render():
    print("=== STARTING SPLIT-SCREEN VERIFIED RENDER TEST ===")
    print(f"Current Working Directory: {os.getcwd()}")
    
    # Dynamically find temp_assets directory
    search_dirs = [
        Path("worker/temp_assets"),
        Path("AgentTiktok/worker/temp_assets"),
        script_dir.parent / "temp_assets",
        Path(__file__).resolve().parent.parent.parent / "worker" / "temp_assets"
    ]
    
    temp_assets_dir = None
    for d in search_dirs:
        if d.exists() and d.is_dir():
            temp_assets_dir = d.resolve()
            break
            
    if not temp_assets_dir:
        print("ERROR: Could not locate temp_assets directory in any search path!")
        sys.exit(1)
        
    print(f"Using temp_assets directory: {temp_assets_dir}")
    
    # Dynamically locate voice, music, and scene files
    voices = list(temp_assets_dir.glob("voice_*.mp3"))
    musics = list(temp_assets_dir.glob("music_video_*.mp3"))
    scenes = list(temp_assets_dir.glob("scene_*.mp4"))
    
    if not voices or not musics or len(scenes) < 2:
        print(f"ERROR: Not enough mock assets in {temp_assets_dir}!")
        print(f"Found: {len(voices)} voices, {len(musics)} musics, {len(scenes)} scenes.")
        sys.exit(1)
        
    voice_audio_path = str(voices[0])
    background_music_path = str(musics[0])
    top_video_paths = [str(scenes[0])]
    bottom_video_paths = [str(scenes[1]), str(scenes[2])] if len(scenes) >= 3 else [str(scenes[1]), str(scenes[1])]
    
    print(f"Voice: {voice_audio_path}")
    print(f"Music: {background_music_path}")
    print(f"Top B-roll: {top_video_paths[0]}")
    print(f"Bottom B-roll sequence: {bottom_video_paths}")

    media_svc = MediaService()

    # Mock scenes layout: 2 scenes
    scenes_layout = [
        {"scene_id": 1, "duration": 4.0, "visual_search_keywords": "vertical scenery", "sfx_trigger": "whoosh"},
        {"scene_id": 2, "duration": 4.0, "visual_search_keywords": "vertical cooking", "sfx_trigger": "pop"}
    ]
    
    # Mock detailed word timestamps
    word_timestamps = [
        {"word": "Hôm", "start_ms": 100, "end_ms": 400},
        {"word": "nay", "start_ms": 450, "end_ms": 800},
        {"word": "chúng", "start_ms": 850, "end_ms": 1200},
        {"word": "ta", "start_ms": 1250, "end_ms": 1600},
        {"word": "sẽ", "start_ms": 1650, "end_ms": 2000},
        {"word": "làm", "start_ms": 2050, "end_ms": 2400},
        {"word": "chủ", "start_ms": 2450, "end_ms": 2800},
        {"word": "cuộc", "start_ms": 2850, "end_ms": 3200},
        {"word": "sống", "start_ms": 3250, "end_ms": 3700},
        {"word": "và", "start_ms": 3800, "end_ms": 4100},
        {"word": "tạo", "start_ms": 4150, "end_ms": 4500},
        {"word": "ra", "start_ms": 4550, "end_ms": 4900},
        {"word": "những", "start_ms": 4950, "end_ms": 5300},
        {"word": "bí", "start_ms": 5350, "end_ms": 5700},
        {"word": "mật", "start_ms": 5750, "end_ms": 6200},
        {"word": "thành", "start_ms": 6250, "end_ms": 6600},
        {"word": "công", "start_ms": 6650, "end_ms": 7100},
        {"word": "mới", "start_ms": 7150, "end_ms": 7600}
    ]
    
    visual_style_plan = {
        "hook_text": "BÍ QUYẾT LÀM CHỦ CUỘC SỐNG",
        "cta_text": "Đăng ký kênh để xem thêm bài học hay!",
        "caption_max_words": 4,
        "caption_max_gap_ms": 520,
        "caption_style": "bold_punchy",
        "accent": "#00FF66"
    }
    
    metadata = {
        "hook_text_3s": "BÍ QUYẾT LÀM CHỦ",
        "cta_text": "Đăng ký kênh để xem thêm!",
        "is_split_screen": True
    }

    job_id = 999
    
    print("\n--- Running split-screen rendering ---")
    output_path = media_svc.render_split_screen_video(
        scenes_layout=scenes_layout,
        word_timestamps=word_timestamps,
        voice_audio_path=voice_audio_path,
        top_video_paths=top_video_paths,
        bottom_video_paths=bottom_video_paths,
        job_id=job_id,
        full_voice_script="Hôm nay chúng ta sẽ làm chủ cuộc sống và tạo ra những bí mật thành công mới",
        background_music_path=background_music_path,
        visual_style_plan=visual_style_plan,
        metadata=metadata
    )
    
    print(f"\nRender output path: {output_path}")
    
    # Verify the output file
    if not os.path.exists(output_path):
        print("ERROR: Output file does not exist!")
        sys.exit(1)
        
    print("\n--- Verifying Output Video Parameters ---")
    info = get_video_info(output_path)
    if info is None:
        print("ERROR: Could not probe output video parameters!")
        sys.exit(1)
        
    width, height, duration = info
    print(f"Output Width: {width}px (Expected: 1080)")
    print(f"Output Height: {height}px (Expected: 1920)")
    print(f"Output Duration: {duration:.2f}s")
    
    # Assertions
    if width != 1080 or height != 1920:
        print("ERROR: Resolution mismatch! Must be 1080x1920.")
        sys.exit(1)
        
    print("\n=== VERIFICATION SUCCESSFUL! ALL TESTS PASSED ===")

if __name__ == "__main__":
    test_verified_render()
