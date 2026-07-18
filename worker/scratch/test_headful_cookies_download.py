import asyncio
import os
import sys
import subprocess
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

def harvest_cookies_headful(url: str, profile_dir: str, cookies_path: str):
    print("Launching headful Playwright to harvest organic cookies...")
    with sync_playwright() as p:
        try:
            browser_context = p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=False, # Headful!
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
                headless=False, # Headful!
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--start-maximized",
                    "--no-sandbox"
                ]
            )
        
        try:
            page = browser_context.pages[0]
            Stealth().apply_stealth_sync(page)
            
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(6)  # Give it ample time to resolve anti-bot and get fully-baked cookies
            
            cookies = browser_context.cookies()
            with open(cookies_path, "w", encoding="utf-8") as f:
                f.write("# Netscape HTTP Cookie File\n")
                f.write("# This is a generated file! Do not edit.\n\n")
                for c in cookies:
                    domain = c.get("domain", "")
                    flag = "TRUE" if domain.startswith(".") else "FALSE"
                    path = c.get("path", "/")
                    secure = "TRUE" if c.get("secure", False) else "FALSE"
                    expires = c.get("expires", 0)
                    name = c.get("name", "")
                    value = c.get("value", "")
                    f.write(f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")
            print(f"Successfully harvested {len(cookies)} organic cookies into {cookies_path}")
        finally:
            browser_context.close()

async def main():
    url = "https://www.douyin.com/video/7634700902561058089"
    profile_dir = "D:\\Folder_Learning_2025_2026\\MyProject_DuAnCaNhan\\AgentTiktok\\worker\\chrome_profile_headful_test"
    cookies_path = "D:\\Folder_Learning_2025_2026\\MyProject_DuAnCaNhan\\AgentTiktok\\worker\\temp_assets\\douyin_cookies.txt"
    output_path = "D:\\Folder_Learning_2025_2026\\MyProject_DuAnCaNhan\\AgentTiktok\\worker\\output_videos\\test_download_headful.mp4"
    
    # 1. Harvest cookies
    await asyncio.to_thread(harvest_cookies_headful, "https://www.douyin.com", profile_dir, cookies_path)
    
    # 2. Run yt-dlp to download video
    print(f"Running yt-dlp to download {url} using organic cookies...")
    cmd = [
        sys.executable, "-m", "yt_dlp", "--no-warnings",
        "-f", "mp4", "--cookies", cookies_path,
        "-o", output_path,
        url
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print("Success!!! Video downloaded successfully to:", output_path)
    except subprocess.CalledProcessError as cpe:
        print("yt-dlp download failed!")
        print("Exit code:", cpe.returncode)
        print("Stderr:", cpe.stderr.strip())

if __name__ == "__main__":
    asyncio.run(main())
