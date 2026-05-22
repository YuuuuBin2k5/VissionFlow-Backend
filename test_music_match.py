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

from worker.services.trending_music_service import TrendingMusicService

def test_music_topic_matcher():
    print("==================================================================")
    print("[*] BAT DAU KIEM THU AI TOPIC-MUSIC MATCHER & COPYRIGHT SYSTEM")
    print("==================================================================")
    
    trending_music = TrendingMusicService()
    
    # Test case 1: Video buồn hoài niệm học đường
    topic_1 = "90% bạn cấp 3 sẽ biến mất khi lên Đại học"
    print(f"\n[Test Case 1] Chu de: '{topic_1}'")
    song_1, artist_1, mood_1 = trending_music.resolve_trending_song_for_topic(topic_1)
    print(f"--> KET QUA KHOI PHUC:")
    print(f"    ▪️ Bài hát: {song_1}")
    print(f"    ▪️ Nghệ sĩ: {artist_1}")
    print(f"    ▪️ Mood: {mood_1}")
    
    # Test case 2: Mẹo Excel công sở
    topic_2 = "3 mẹo x3 hiệu suất Excel cho dân văn phòng"
    print(f"\n[Test Case 2] Chu de: '{topic_2}'")
    song_2, artist_2, mood_2 = trending_music.resolve_trending_song_for_topic(topic_2)
    print(f"--> KET QUA KHOI PHUC:")
    print(f"    ▪️ Bài hát: {song_2}")
    print(f"    ▪️ Nghệ sĩ: {artist_2}")
    print(f"    ▪️ Mood: {mood_2}")

    print("\n==================================================================")
    print("[+] HOAN THANH KIEM THU CHUC NANG GOI Y NHAC THEO CHU DE! ✅")
    print("==================================================================")

if __name__ == "__main__":
    test_music_topic_matcher()
