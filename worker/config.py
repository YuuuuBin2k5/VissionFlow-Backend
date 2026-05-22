import os
from pathlib import Path
from dotenv import load_dotenv

# Thư mục gốc của Project
BASE_DIR = Path(__file__).resolve().parent.parent

# Tải cấu hình từ file .env nếu có
load_dotenv(BASE_DIR / "worker" / ".env")
load_dotenv(BASE_DIR / "orchestrator" / ".env")  # Fallback to orchestrator .env if running from workspace root

# Cấu hình API Keys
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Cấu hình Cơ sở dữ liệu MySQL
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", 3306))
DB_USER = os.environ.get("DB_USER", "root")  # Khớp với cấu hình orchestrator dùng root
DB_PASSWORD = os.environ.get("DB_PASSWORD", "YOUR_DB_PASSWORD_HERE")
DB_NAME = os.environ.get("DB_NAME", "tiktok_agent_automation_db")

# Các thư mục lưu trữ media
ASSETS_DIR = BASE_DIR / "worker" / "temp_assets"
OUTPUT_DIR = BASE_DIR / "worker" / "output_videos"
COOKIES_PATH = BASE_DIR / "worker" / "cookies.json"
FONTS_DIR = BASE_DIR / "shared" / "fonts"

# Tự động tạo thư mục nếu chưa tồn tại
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
FONTS_DIR.mkdir(parents=True, exist_ok=True)

# Lấy giọng đọc mặc định của Edge-TTS
DEFAULT_TTS_VOICE = "vi-VN-HoaiMyNeural" # Giọng đọc nữ tiếng Việt cực kỳ tự nhiên
BACKUP_TTS_VOICE = "vi-VN-NamMinhNeural"   # Giọng đọc nam ấm áp

# Safe TikTok posting schedule.
SCHEDULE_TIMEZONE = os.environ.get("SCHEDULE_TIMEZONE", "Asia/Bangkok")
POSTING_SCHEDULE_PRESET = os.environ.get("POSTING_SCHEDULE_PRESET", "office_student")
POSTING_SCHEDULE_PRESETS = {
    "office_student": ("11:30", "19:30"),
    "deep_night": ("12:00", "22:00"),
}
MIN_HOURS_BETWEEN_POSTS = int(os.environ.get("MIN_HOURS_BETWEEN_POSTS", "4"))

# Render engine selection: classic keeps the current MoviePy flow,
# music_reactive enables the V2 audio-reactive browser render flow.
RENDER_ENGINE = os.environ.get("RENDER_ENGINE", "classic")
REACTIVE_RENDER_FPS = int(os.environ.get("REACTIVE_RENDER_FPS", "24"))
REACTIVE_RENDER_WIDTH = int(os.environ.get("REACTIVE_RENDER_WIDTH", "1080"))
REACTIVE_RENDER_HEIGHT = int(os.environ.get("REACTIVE_RENDER_HEIGHT", "1920"))
REACTIVE_MIN_FILE_SIZE_MB = float(os.environ.get("REACTIVE_MIN_FILE_SIZE_MB", "2"))
LYRIC_LANGUAGE = os.environ.get("LYRIC_LANGUAGE", "vi")
LYRIC_TRANSCRIPTION_MODEL = os.environ.get("LYRIC_TRANSCRIPTION_MODEL", "small")
MUSIC_VIRAL_MIN_DURATION = float(os.environ.get("MUSIC_VIRAL_MIN_DURATION", "30"))
MUSIC_VIRAL_MAX_DURATION = float(os.environ.get("MUSIC_VIRAL_MAX_DURATION", "60"))

# Trending-safe remix settings. V1 only remixes audio that the user supplied
# or explicitly confirmed they have rights to use.
REMIX_BASS_GAIN = float(os.environ.get("REMIX_BASS_GAIN", "0.22"))
REMIX_DRUM_GAIN = float(os.environ.get("REMIX_DRUM_GAIN", "0.16"))
REMIX_STYLE = os.environ.get("REMIX_STYLE", "trend_bass")
REMIX_REQUIRE_RIGHTS_CONFIRMATION = os.environ.get("REMIX_REQUIRE_RIGHTS_CONFIRMATION", "true").lower() == "true"
