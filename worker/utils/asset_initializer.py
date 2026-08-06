import os
import sys
import subprocess
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

def initialize_sfx_library():
    """Tự động sinh bộ thư viện hiệu ứng âm thanh phụ SFX (Whoosh, Pop, Riser, Impact, 432Hz Focus)."""
    audio_dir = ASSETS_DIR / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    print(f"[*] Kiểm tra và khởi tạo thư viện SFX tại: {audio_dir}")

    sfx_configs = {
        "sfx_whoosh.wav": [
            'ffmpeg', '-y', '-f', 'lavfi', '-i', 'aevalsrc=random(0)-0.5:d=0.35',
            '-af', 'lowpass=f=1800,afade=t=in:ss=0:d=0.15,afade=t=out:st=0.15:d=0.20,volume=1.5',
            str(audio_dir / "sfx_whoosh.wav")
        ],
        "sfx_swish.wav": [
            'ffmpeg', '-y', '-f', 'lavfi', '-i', 'aevalsrc=random(0)-0.5:d=0.25',
            '-af', 'lowpass=f=2400,afade=t=in:ss=0:d=0.10,afade=t=out:st=0.10:d=0.15,volume=1.3',
            str(audio_dir / "sfx_swish.wav")
        ],
        "sfx_pop.wav": [
            'ffmpeg', '-y', '-f', 'lavfi', '-i', 'sine=f=800:d=0.12',
            '-af', 'afade=t=out:st=0.04:d=0.08,volume=1.8',
            str(audio_dir / "sfx_pop.wav")
        ],
        "sfx_riser.wav": [
            'ffmpeg', '-y', '-f', 'lavfi', '-i', 'sine=f=300:d=0.5',
            '-af', 'afade=t=in:ss=0:d=0.4,volume=1.2',
            str(audio_dir / "sfx_riser.wav")
        ],
        "sfx_impact.wav": [
            'ffmpeg', '-y', '-f', 'lavfi', '-i', 'sine=f=75:d=0.6',
            '-af', 'afade=t=out:st=0.1:d=0.5,volume=2.2',
            str(audio_dir / "sfx_impact.wav")
        ],
        "focus_432hz.mp3": [
            'ffmpeg', '-y', '-f', 'lavfi', '-i', 'sine=f=432:d=5',
            '-af', 'volume=0.05',
            str(audio_dir / "focus_432hz.mp3")
        ],
    }

    for filename, cmd in sfx_configs.items():
        file_path = audio_dir / filename
        if not file_path.exists() or file_path.stat().st_size == 0:
            try:
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode == 0:
                    print(f"[+] Đã tạo SFX âm thanh phụ: {filename}")
                else:
                    print(f"[-] Warning: SFX generation failed for {filename}: {res.stderr[:200]}")
            except Exception as e:
                print(f"[-] Warning: Failed to run FFmpeg for SFX {filename}: {e}")
        else:
            print(f"[+] SFX {filename} đã sẵn sàng.")


def initialize_bgm_library():
    """Khởi tạo kho nhạc nền mặc định (Relaxing, Uplifting, Cinematic, Acoustic)."""
    bgm_dir = ASSETS_DIR / "audio" / "bgm"
    bgm_dir.mkdir(parents=True, exist_ok=True)
    print(f"[*] Kiểm tra và khởi tạo kho nhạc nền BGM tại: {bgm_dir}")

    bgm_configs = {
        "relaxing_chill.mp3": [
            'ffmpeg', '-y', '-f', 'lavfi', '-i',
            'aevalsrc=sin(2*PI*432*t)*0.1+sin(2*PI*540*t)*0.08+sin(2*PI*648*t)*0.06:d=60',
            '-af', 'afade=t=in:ss=0:d=2.0,afade=t=out:st=58.0:d=2.0,volume=0.35',
            str(bgm_dir / "relaxing_chill.mp3")
        ],
        "uplifting_happy.mp3": [
            'ffmpeg', '-y', '-f', 'lavfi', '-i',
            'aevalsrc=sin(2*PI*528*t)*0.12+sin(2*PI*660*t)*0.1+sin(2*PI*792*t)*0.08:d=60',
            '-af', 'afade=t=in:ss=0:d=2.0,afade=t=out:st=58.0:d=2.0,volume=0.35',
            str(bgm_dir / "uplifting_happy.mp3")
        ],
        "cinematic_inspiring.mp3": [
            'ffmpeg', '-y', '-f', 'lavfi', '-i',
            'aevalsrc=sin(2*PI*216*t)*0.15+sin(2*PI*324*t)*0.12+sin(2*PI*432*t)*0.10:d=60',
            '-af', 'afade=t=in:ss=0:d=2.0,afade=t=out:st=58.0:d=2.0,volume=0.40',
            str(bgm_dir / "cinematic_inspiring.mp3")
        ],
        "acoustic_peaceful.mp3": [
            'ffmpeg', '-y', '-f', 'lavfi', '-i',
            'aevalsrc=sin(2*PI*320*t)*0.12+sin(2*PI*400*t)*0.1+sin(2*PI*480*t)*0.08:d=60',
            '-af', 'afade=t=in:ss=0:d=2.0,afade=t=out:st=58.0:d=2.0,volume=0.35',
            str(bgm_dir / "acoustic_peaceful.mp3")
        ],
    }

    for filename, cmd in bgm_configs.items():
        file_path = bgm_dir / filename
        if not file_path.exists() or file_path.stat().st_size == 0:
            try:
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode == 0:
                    print(f"[+] Đã tạo nhạc nền BGM preset: {filename}")
                else:
                    print(f"[-] Warning: BGM generation failed for {filename}: {res.stderr[:200]}")
            except Exception as e:
                print(f"[-] Warning: Failed to run FFmpeg for BGM {filename}: {e}")
        else:
            print(f"[+] Nhạc nền BGM preset {filename} đã sẵn sàng.")


def initialize_assets():
    import subprocess
    print("==================================================================")
    print("[*] CHUONG TRINH KHOI TAO TAI NGUYEN PREMIUM - VISIONFLOW")
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
            
    # 3. Khởi tạo Thư viện Hiệu ứng Âm thanh Phụ (SFX Transitions & Focus 432Hz)
    initialize_sfx_library()
    # 4. Khởi tạo Kho Nhạc Nền Preset BGM
    initialize_bgm_library()

    print("==================================================================")
    print("[+] Qua trinh khoi tao tai nguyen hoan tat!")
    print("==================================================================")

if __name__ == "__main__":
    initialize_assets()
