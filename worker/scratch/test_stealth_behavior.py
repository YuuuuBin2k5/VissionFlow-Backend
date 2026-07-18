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
import random

def harvest_stealth_cookies(url: str, profile_dir: str, cookies_path: str):
    print("Launching headless Playwright with human behavior simulation...")
    with sync_playwright() as p:
        browser_context = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=True, # Keep it headless so it runs silently in background!
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
                "--no-sandbox"
            ]
        )
        
        try:
            page = browser_context.pages[0]
            Stealth().apply_stealth_sync(page)
            
            print(f"Navigating to Douyin main page to establish session...")
            page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=20000)
            time.sleep(3)
            
            # Simulate human behavior
            print("Simulating human interactions (scroll, mouse moves)...")
            # 1. Mouse moves
            for _ in range(5):
                x = random.randint(100, 800)
                y = random.randint(100, 600)
                page.mouse.move(x, y)
                time.sleep(0.3)
                
            # 2. Page scrolls
            page.evaluate("window.scrollBy(0, 400)")
            time.sleep(1.5)
            page.evaluate("window.scrollBy(0, -200)")
            time.sleep(1)
            
            # Navigate to the actual video page to get video-specific cookies
            print(f"Navigating to video page: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(4)
            
            # Additional scrolls on video page
            page.evaluate("window.scrollBy(0, 100)")
            time.sleep(1)
            
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
            print(f"Successfully harvested {len(cookies)} cookies into {cookies_path}")
        finally:
            browser_context.close()

async def main():
    url = "https://www.douyin.com/video/7634700902561058089"
    profile_dir = "D:\\Folder_Learning_2025_2026\\MyProject_DuAnCaNhan\\AgentTiktok\\worker\\chrome_profile_stealth_behavior"
    cookies_path = "D:\\Folder_Learning_2025_2026\\MyProject_DuAnCaNhan\\AgentTiktok\\worker\\temp_assets\\douyin_cookies.txt"
    output_path = "D:\\Folder_Learning_2025_2026\\MyProject_DuAnCaNhan\\AgentTiktok\\worker\\output_videos\\test_download_stealth.mp4"
    
    # 1. Harvest cookies with stealth behavior
    await asyncio.to_thread(harvest_stealth_cookies, url, profile_dir, cookies_path)
    
    # 2. Run yt-dlp to download video
    print(f"Running yt-dlp to download {url} using stealth-behavior cookies...")
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
