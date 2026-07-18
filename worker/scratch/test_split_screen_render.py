import os
import sys
from pathlib import Path

# Thêm thư mục gốc vào path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from worker.services.media_service import MediaService

def test():
    media_svc = MediaService()
    
    # Sử dụng các file có sẵn trong worker/temp_assets
    voice_audio_path = "worker/temp_assets/voice_190.mp3"
    top_video_paths = ["worker/temp_assets/scene_10_1166.mp4"]
    bottom_video_paths = ["worker/temp_assets/scene_10_1908.mp4"]
    background_music_path = "worker/temp_assets/music_video_190_cozy_chill.mp3"
    
    # Kiểm tra sự tồn tại của files
    for path_str in [voice_audio_path, top_video_paths[0], bottom_video_paths[0], background_music_path]:
        if not os.path.exists(path_str):
            print(f"Error: File {path_str} does not exist. Check worker/temp_assets directory.")
            return

    # Mock data
    scenes_layout = [{"scene_id": 1, "visual_search_keywords": "vertical cooking"}]
    word_timestamps = [
        {"word": "Xin", "start_ms": 100, "end_ms": 500},
        {"word": "chào", "start_ms": 550, "end_ms": 900},
        {"word": "các", "start_ms": 950, "end_ms": 1200},
        {"word": "bạn", "start_ms": 1250, "end_ms": 1500},
        {"word": "đến", "start_ms": 1550, "end_ms": 1800},
        {"word": "với", "start_ms": 1850, "end_ms": 2100},
        {"word": "kênh", "start_ms": 2150, "end_ms": 2400},
        {"word": "của", "start_ms": 2450, "end_ms": 2700},
        {"word": "mình", "start_ms": 2750, "end_ms": 3100},
    ]
    visual_style_plan = {
        "hook_text": "HOOK TEXT TEST",
        "cta_text": "CTA TEXT TEST",
        "caption_max_words": 4,
        "caption_max_gap_ms": 500
    }
    metadata = {
        "hook_text_3s": "HOOK TEXT TEST",
        "cta_text": "CTA TEXT TEST",
        "is_split_screen": True
    }

    print("Running render_split_screen_video...")
    output_path = media_svc.render_split_screen_video(
        scenes_layout=scenes_layout,
        word_timestamps=word_timestamps,
        voice_audio_path=voice_audio_path,
        top_video_paths=top_video_paths,
        bottom_video_paths=bottom_video_paths,
        job_id=999,
        full_voice_script="Xin chào các bạn đến với kênh của mình",
        background_music_path=background_music_path,
        visual_style_plan=visual_style_plan,
        metadata=metadata
    )
    print("SUCCESS RENDERING SPLIT SCREEN TO:", output_path)

if __name__ == "__main__":
    test()
