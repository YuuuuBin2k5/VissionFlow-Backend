import subprocess
import sys

def main():
    url = "https://www.douyin.com/video/7634700902561058089"
    print("Testing yt-dlp with --cookies-from-browser firefox and normalized URL...")
    
    cmd = [
        sys.executable, "-m", "yt_dlp", "--no-warnings",
        "--get-title", "--cookies-from-browser", "firefox",
        url
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print("Success! Firefox cookies worked. Title found:", res.stdout.strip())
    except subprocess.CalledProcessError as cpe:
        print("Failed with --cookies-from-browser firefox!")
        print("Exit code:", cpe.returncode)
        print("Stderr:", cpe.stderr.strip())

if __name__ == "__main__":
    main()
