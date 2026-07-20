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
PIXABAY_API_KEY = os.environ.get("PIXABAY_API_KEY", "")
COVERR_API_KEY = os.environ.get("COVERR_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_API_KEYS = [k.strip() for k in os.environ.get("GEMINI_API_KEYS", "").replace('"', '').split(",") if k.strip()]
if GEMINI_API_KEY and GEMINI_API_KEY not in GEMINI_API_KEYS:
    GEMINI_API_KEYS.insert(0, GEMINI_API_KEY)

HUGGINGFACE_API_KEY = os.environ.get("HUGGINGFACE_API_KEY", "").replace('"', '')
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").replace('"', '')
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").replace('"', '')


# Cấu hình Cơ sở dữ liệu MySQL
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", 3306))
DB_USER = os.environ.get("DB_USER", "root")  # Khớp với cấu hình orchestrator dùng root
DB_PASSWORD = os.environ.get("DB_PASSWORD", "YOUR_DB_PASSWORD_HERE")
DB_NAME = os.environ.get("DB_NAME", "tiktok_agent_automation_db")

# Các thư mục lưu trữ media
ASSETS_DIR = BASE_DIR / "worker" / "temp_assets"
OUTPUT_DIR = BASE_DIR / "worker" / "output_videos"
LOCAL_ASSETS_DIR = BASE_DIR / "worker" / "local_assets"
COOKIES_PATH = BASE_DIR / "worker" / "cookies.json"
FONTS_DIR = BASE_DIR / "shared" / "fonts"

# Tự động tạo thư mục nếu chưa tồn tại
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LOCAL_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
(LOCAL_ASSETS_DIR / "cooking_long").mkdir(parents=True, exist_ok=True)
(LOCAL_ASSETS_DIR / "daily_life_bottom").mkdir(parents=True, exist_ok=True)
(LOCAL_ASSETS_DIR / "satisfying").mkdir(parents=True, exist_ok=True)
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
REACTIVE_RENDER_FPS = int(os.environ.get("REACTIVE_RENDER_FPS", "30"))
REACTIVE_RENDER_WIDTH = int(os.environ.get("REACTIVE_RENDER_WIDTH", "1080"))
REACTIVE_RENDER_HEIGHT = int(os.environ.get("REACTIVE_RENDER_HEIGHT", "1920"))
REACTIVE_MIN_FILE_SIZE_MB = float(os.environ.get("REACTIVE_MIN_FILE_SIZE_MB", "2"))
LYRIC_LANGUAGE = os.environ.get("LYRIC_LANGUAGE", "vi")
LYRIC_TRANSCRIPTION_MODEL = os.environ.get("LYRIC_TRANSCRIPTION_MODEL", "small")
MUSIC_VIRAL_MIN_DURATION = float(os.environ.get("MUSIC_VIRAL_MIN_DURATION", "60"))
MUSIC_VIRAL_MAX_DURATION = float(os.environ.get("MUSIC_VIRAL_MAX_DURATION", "180"))

# Trending-safe remix settings. V1 only remixes audio that the user supplied
# or explicitly confirmed they have rights to use.
REMIX_BASS_GAIN = float(os.environ.get("REMIX_BASS_GAIN", "0.22"))
REMIX_DRUM_GAIN = float(os.environ.get("REMIX_DRUM_GAIN", "0.16"))
REMIX_STYLE = os.environ.get("REMIX_STYLE", "trend_bass")
REMIX_REQUIRE_RIGHTS_CONFIRMATION = os.environ.get("REMIX_REQUIRE_RIGHTS_CONFIRMATION", "true").lower() == "true"

# Browser runtime settings for Playwright-based render and TikTok publishing.
# On ARM64 hosts such as Oracle Ampere A1, prefer bundled Playwright Chromium or
# a system Chromium path instead of channel="chrome", which may not exist.
BROWSER_CHANNEL = os.environ.get("BROWSER_CHANNEL", "").strip()
BROWSER_EXECUTABLE_PATH = os.environ.get("BROWSER_EXECUTABLE_PATH", "").strip()
BROWSER_EXTRA_ARGS = [
    arg.strip()
    for arg in os.environ.get("BROWSER_EXTRA_ARGS", "").split(",")
    if arg.strip()
]

# PostgreSQL Control Plane Adapter Feature Flag & URL
VISIONFLOW_USE_PG_ADAPTER = os.environ.get("VISIONFLOW_USE_PG_ADAPTER", "true").lower() == "true"
VISIONFLOW_CONTROL_PLANE_URL = os.environ.get("VISIONFLOW_CONTROL_PLANE_URL", "https://visionflow-control-plane-free.onrender.com/api/v1")
VISIONFLOW_ORGANIZATION_ID = os.environ.get("VISIONFLOW_ORGANIZATION_ID", "7b91598c-6c3e-4e5d-8247-d3efa203984a")

# Narration handoff mode config & validation
VISIONFLOW_NARRATION_HANDOFF_MODE = os.environ.get("VISIONFLOW_NARRATION_HANDOFF_MODE", "control_plane").lower()
APP_ENV = os.environ.get("APP_ENV", "development").lower()


class ConfigurationError(ValueError):
    """Raised when a worker config is missing or invalid."""


def validate_config() -> None:
    mode = os.environ.get("VISIONFLOW_NARRATION_HANDOFF_MODE", "legacy").lower()
    app_env = os.environ.get("APP_ENV", "development").lower()

    if mode not in {"legacy", "shadow", "control_plane"}:
        raise ConfigurationError(f"Invalid VISIONFLOW_NARRATION_HANDOFF_MODE: {mode}")

    if app_env == "production" and mode in {"shadow", "control_plane"}:
        raise ConfigurationError("Shadow or Control Plane handoff mode is not allowed in production environment")

    if mode in {"shadow", "control_plane"}:
        org_id = os.environ.get("VISIONFLOW_ORGANIZATION_ID", "").strip()
        if not org_id:
            raise ConfigurationError("VISIONFLOW_ORGANIZATION_ID is required for shadow/control_plane mode")
        import uuid
        try:
            uuid.UUID(org_id)
        except ValueError:
            raise ConfigurationError("VISIONFLOW_ORGANIZATION_ID must be a valid UUID")

        cp_url = os.environ.get("VISIONFLOW_CONTROL_PLANE_URL", "").strip()
        if not cp_url:
            raise ConfigurationError("VISIONFLOW_CONTROL_PLANE_URL is required for shadow/control_plane mode")
