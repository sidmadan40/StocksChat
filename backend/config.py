"""Application configuration loaded from the project .env file."""

from pathlib import Path
import os

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / ".env"

# Load .env once when the config module is imported.
load_dotenv(ENV_FILE, override=False)


def _get_env(name: str, default: str = "") -> str:
    """Return a trimmed env var with a safe string fallback."""
    value = os.getenv(name, default)
    if value is None:
        return default
    return value.strip()


GEMINI_API_KEY = _get_env("GEMINI_API_KEY")
APCA_API_KEY_ID = _get_env("APCA_API_KEY_ID")
APCA_API_SECRET_KEY = _get_env("APCA_API_SECRET_KEY")
APCA_API_BASE_URL = _get_env("APCA_API_BASE_URL", "https://paper-api.alpaca.markets/v2")


def validate_required_config() -> None:
    """Raise a clear error if required API configuration values are missing."""
    required = {
        "GEMINI_API_KEY": GEMINI_API_KEY,
        "APCA_API_KEY_ID": APCA_API_KEY_ID,
        "APCA_API_SECRET_KEY": APCA_API_SECRET_KEY,
        "APCA_API_BASE_URL": APCA_API_BASE_URL,
    }

    missing = [name for name, value in required.items() if not value]
    if missing:
        missing_list = ", ".join(missing)
        raise RuntimeError(
            "Startup blocked: missing required environment variables: "
            f"{missing_list}. Please set them in .env before starting the app."
        )