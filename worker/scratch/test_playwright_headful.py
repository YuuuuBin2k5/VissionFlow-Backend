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

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import time

def extract_douyin_video_sync_headful(url: str, profile_dir: str) -> str:
    """Trích xuất link video stream trực tiếp từ Douyin sử dụng Stealth Playwright ở chế độ Headful"""
    with sync_playwright() as p:
        try:
            browser_context = p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=False, # RUN IN HEADFUL MODE TO BYPASS ANTI-BOT!
                channel="chrome",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--start-maximized",
                    "--no-sandbox"
                ]
            )
        except Exception:
            browser_context = p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=False, # RUN IN HEADFUL MODE TO BYPASS ANTI-BOT!
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--start-maximized",
                    "--no-sandbox"
                ]
            )
        
        try:
            page = browser_context.pages[0]
            Stealth().apply_stealth_sync(page)
            
            print(f"Opening URL in headful browser: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(5)  # Wait for JS player to initialize
            
            # Wait for video selector
            page.wait_for_selector("video", state="attached", timeout=10000)
            
            videos = page.locator("video")
            count = videos.count()
            print(f"Found {count} video elements.")
            
            # Check source elements
            for i in range(count):
                video = videos.nth(i)
                sources = video.locator("source")
                for j in range(sources.count()):
                    source_src = sources.nth(j).get_attribute("src")
                    if source_src:
                        if "uuu_265.mp4" in source_src or source_src.startswith("blob:"):
                            continue
                        print("Found high-quality stream URL in source:", source_src[:100])
                        return source_src
            
            # Check direct src attributes
            for i in range(count):
                video = videos.nth(i)
                src = video.get_attribute("src")
                if src:
                    if "uuu_265.mp4" in src or src.startswith("blob:"):
                        continue
                    print("Found direct stream URL in src:", src[:100])
                    return src
            
            raise RuntimeError("Không tìm thấy link video stream thực tế (chỉ phát hiện các blob URL).")
        finally:
            browser_context.close()

async def main():
    url = "https://www.douyin.com/jingxuan?modal_id=7634700902561058089"
    profile_dir = "D:\\Folder_Learning_2025_2026\\MyProject_DuAnCaNhan\\AgentTiktok\\worker\\chrome_profile_headful_test"
    
    print("Testing Playwright Headful Douyin extraction...")
    try:
        extracted = await asyncio.to_thread(extract_douyin_video_sync_headful, url, profile_dir)
        print("Success! Extracted Stream URL:", extracted)
    except Exception as e:
        print("Playwright headful failed with error:")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
