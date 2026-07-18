import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import time

def dump_html():
    url = "https://www.douyin.com/note/7361815152865955113"
    profile_dir = "worker/chrome_profile_test"
    
    with sync_playwright() as p:
        browser_context = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        try:
            page = browser_context.pages[0]
            Stealth().apply_stealth_sync(page)
            
            print("Navigating to note url...")
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(5)
            
            # Print page title
            print("Page title:", page.title())
            
            # Find all image tags
            images = page.locator("img").all()
            print(f"Found {len(images)} img tags")
            for i, img in enumerate(images[:10]):
                src = img.get_attribute("src")
                print(f"Img {i}: {src[:120] if src else 'None'}")
                
            # Find all audio/video tags
            audios = page.locator("audio").all()
            print(f"Found {len(audios)} audio tags")
            for i, aud in enumerate(audios):
                src = aud.get_attribute("src")
                print(f"Audio {i}: {src[:120] if src else 'None'}")
                
            videos = page.locator("video").all()
            print(f"Found {len(videos)} video tags")
            for i, vid in enumerate(videos):
                src = vid.get_attribute("src")
                print(f"Video {i}: {src[:120] if src else 'None'}")
                
            # Check for window._ROUTER_DATA
            router_data = page.evaluate("() => window._ROUTER_DATA || window.__INIT_DATA__")
            if router_data:
                print("Found ROUTER_DATA or INIT_DATA!")
                import json
                with open("worker/temp_assets/note_router_data.json", "w", encoding="utf-8") as f:
                    json.dump(router_data, f, ensure_ascii=False, indent=2)
                print("Saved router data to note_router_data.json")
            else:
                # Let's search inside script tags
                scripts = page.locator("script").all()
                print(f"Found {len(scripts)} script tags")
                for i, scr in enumerate(scripts):
                    text = scr.inner_text()
                    if "ROUTER_DATA" in text or "INIT_DATA" in text or "render_data" in text:
                        print(f"Script {i} contains matching text (len {len(text)})")
                        with open(f"worker/temp_assets/script_{i}.txt", "w", encoding="utf-8") as f:
                            f.write(text)
                            
        finally:
            browser_context.close()

if __name__ == "__main__":
    dump_html()
