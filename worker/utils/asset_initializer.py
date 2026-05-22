import os
import sys
import urllib.request
from pathlib import Path

# Cấu hình encoding UTF-8 cho stdout của terminal Windows để tránh UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

# Thư mục gốc của project
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Các thư mục chứa tài nguyên
FONTS_DIR = BASE_DIR / "shared" / "fonts"
ASSETS_DIR = BASE_DIR / "worker" / "temp_assets"

# Các URL tải tài nguyên public
FONT_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/Montserrat-ExtraBold.ttf"
MUSIC_URL = "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3" # File nhạc sample ambient ổn định làm lofi background

def download_file(url: str, dest_path: Path, file_desc: str):
    """Hàm tải file từ URL có hiển thị tiến độ và xử lý lỗi cẩn thận"""
    print(f"[*] Bat dau tai {file_desc} tu: {url}")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        # Tải và lưu file
        urllib.request.urlretrieve(url, str(dest_path))
        print(f"[+] Da tai thanh cong {file_desc}! Luu tai: {dest_path}")
        return True
    except Exception as e:
        print(f"[-] Loi khi tai {file_desc}: {e}")
        return False

def initialize_assets():
    print("==================================================================")
    print("[*] CHUONG TRINH KHOI TAO TAI NGUYEN PREMIUM - AGENTTIKTOK")
    print("==================================================================")
    
    # 1. Khởi tạo Font Montserrat-ExtraBold tiếng Việt
    font_path = FONTS_DIR / "Montserrat-ExtraBold.ttf"
    if font_path.exists():
        print(f"[+] Font Montserrat-ExtraBold da ton tai tai: {font_path}")
    else:
        success = download_file(FONT_URL, font_path, "Font Montserrat-ExtraBold")
        if not success:
            print("[-] WARNING: Khong the tai font Montserrat. He thong se fallback ve font mac dinh.")

    # 2. Khởi tạo Nhạc nền Lofi Ambient
    music_path = ASSETS_DIR / "lofi_ambient.mp3"
    if music_path.exists():
        print(f"[+] Nhac nen lofi_ambient.mp3 da ton tai tai: {music_path}")
    else:
        success = download_file(MUSIC_URL, music_path, "Nhac nen lofi_ambient.mp3")
        if not success:
            print("[-] WARNING: Khong the tai nhac nen. Video se khong co nhac nen.")
            
    print("==================================================================")
    print("[+] Qua trinh khoi tao tai nguyen hoan tat!")
    print("==================================================================")

if __name__ == "__main__":
    initialize_assets()
