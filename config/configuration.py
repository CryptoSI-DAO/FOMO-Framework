"""
Environment Configurations for FOMO Radio
"""
import os
from pathlib import Path

# Load .env file if it exists
_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists():
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _val = _line.split("=", 1)
                _val = _val.strip().strip('"').strip("'")
                os.environ.setdefault(_key.strip(), _val)

# LLM Configuration (OpenRouter)
LLM_API_KEY = os.environ.get("OPENROUTER_API_KEY", os.environ.get("LLM_API_KEY", ""))
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "openrouter/owl-alpha")

# Report Configuration
REPORT_DIR = os.environ.get("REPORT_DIR", "/workspace/app-ideas/ideas")

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Folder Configuration
MEDIA_FOLDER = "media"
LOG_FOLDER = "logs"
TEMP_VIDEO_FILE = "media/temp_mp4.mp4"
