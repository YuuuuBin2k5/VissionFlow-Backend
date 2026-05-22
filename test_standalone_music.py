import os
import sys

# Reconfigure stdout and stderr to use UTF-8 to prevent Unicode crashes on Windows console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
if sys.stderr.encoding != 'utf-8':
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

import json
from pathlib import Path

# Thêm thư mục gốc vào path để import
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from worker.services.music_reactive_service import MusicReactiveService
from worker.services.trending_music_service import TrendingMusicService
from worker.services.llm_service import LLMService

def test_music_reactive_services():
    print("==================================================================")
    print("[*] BAT DAU KIEM THU STANDALONE MUSIC VIDEO SERVICES")
    print("==================================================================")
    
    # Khởi tạo các services
    trending_music = TrendingMusicService()
    llm = LLMService()
    
    # 1. Kiểm tra Trending Music Song details resolver (Auto Trend)
    print("\n[1] Kiem tra resolve_trending_song_details (Che do tu dong):")
    song, artist = trending_music.resolve_trending_song_details("HOT TRENDING", "AUTO DETECT")
    print(f"--> Da giai quyet: Song = '{song}', Artist = '{artist}'")
    assert song != "HOT TRENDING", "Loi: Khong tu dong cào hoac fallback song hot trend"
    assert artist != "AUTO DETECT", "Loi: Khong tu dong cào hoac fallback artist hot trend"
    
    # 2. Kiểm tra Mood Analysis bang Gemini
    print("\n[2] Kiem tra analyze_music_mood via Gemini:")
    analysis = llm.analyze_music_mood(song, artist)
    print(f"--> Gemini response: {json.dumps(analysis, indent=2, ensure_ascii=False)}")
    assert "mood" in analysis, "Loi: Thieu mood trong Gemini output"
    assert "caption" in analysis, "Loi: Thieu caption trong Gemini output"
    assert "visual_keywords" in analysis, "Loi: Thieu visual_keywords trong Gemini output"
    
    # 3. Kiểm tra Download/Copy Audio track
    print("\n[3] Kiem tra download_mood_audio:")
    mood = analysis["mood"]
    audio_path = trending_music.download_mood_audio(mood, 9999)
    print(f"--> Tep am thanh da luu tai: {audio_path}")
    assert Path(audio_path).exists(), f"Loi: File am thanh khong ton tai tai {audio_path}"
    
    print("\n==================================================================")
    print("[+] TAT CA CAC THANH PHAN STANDALONE HOAT DONG HOAN HAO! ✅")
    print("==================================================================")

if __name__ == "__main__":
    test_music_reactive_services()
