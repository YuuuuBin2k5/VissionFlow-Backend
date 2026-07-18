import subprocess
import sys
import os

def main():
    url = "https://www.douyin.com/video/7634700902561058089"
    cookies_path = "D:\\Folder_Learning_2025_2026\\MyProject_DuAnCaNhan\\AgentTiktok\\worker\\temp_assets\\douyin_cookies.txt"
    output_path = "D:\\Folder_Learning_2025_2026\\MyProject_DuAnCaNhan\\AgentTiktok\\worker\\output_videos\\test_download.mp4"
    
    print(f"Testing download using generated cookies with normalized URL: {url}...")
    if not os.path.exists(cookies_path):
        print("Cookies file does not exist!")
        return
        
    cmd = [
        sys.executable, "-m", "yt_dlp", "--no-warnings",
        "-f", "mp4", "--cookies", cookies_path,
        "-o", output_path,
        url
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print("Success! Video downloaded to:", output_path)
    except subprocess.CalledProcessError as cpe:
        print("Failed to download using cookies!")
        print("Exit code:", cpe.returncode)
        print("Stderr:", cpe.stderr.strip())

if __name__ == "__main__":
    main()
