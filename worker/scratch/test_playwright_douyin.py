import asyncio
import os
import sys
from pathlib import Path

# Add project root absolute path
sys.path.append("D:\\Folder_Learning_2025_2026\\MyProject_DuAnCaNhan\\AgentTiktok")

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

from worker.main import extract_douyin_video_sync

async def main():
    url = "https://www.douyin.com/jingxuan?modal_id=7634700902561058089"
    profile_dir = "D:\\Folder_Learning_2025_2026\\MyProject_DuAnCaNhan\\AgentTiktok\\worker\\chrome_profile_test"
    
    print("Testing Playwright Douyin extraction...")
    try:
        extracted = await asyncio.to_thread(extract_douyin_video_sync, url, profile_dir)
        print("Success! Extracted Stream URL:", extracted)
    except Exception as e:
        print("Playwright failed with error:")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
