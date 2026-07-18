import subprocess
import sys

def test_browser(browser_name):
    url = "https://www.douyin.com/jingxuan?modal_id=7634700902561058089"
    print(f"Testing yt-dlp with --cookies-from-browser {browser_name}...")
    
    cmd = [
        sys.executable, "-m", "yt_dlp", "--no-warnings",
        "--get-title", "--cookies-from-browser", browser_name,
        url
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"Success! {browser_name} cookies worked. Title found:", res.stdout.strip())
        return True
    except subprocess.CalledProcessError as cpe:
        print(f"Failed with --cookies-from-browser {browser_name}!")
        print("Exit code:", cpe.returncode)
        print("Stderr:", cpe.stderr.strip())
        return False

def main():
    for browser in ["chrome", "edge", "firefox"]:
        if test_browser(browser):
            print(f"\n--- SUCCESS WITH {browser.upper()} ---")
            break
        print("-" * 50)
        
if __name__ == "__main__":
    main()
