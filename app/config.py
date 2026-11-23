"""Settings read from environment variables (loaded from the .env file).

Values are read every time a function is called, so changing .env and
restarting the server (or setting env vars in tests) always takes effect.
"""
import os

from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def serpapi_key() -> str:
    return _get("SERPAPI_KEY")


def jsearch_key() -> str:
    return _get("JSEARCH_KEY")


def gemini_api_key() -> str:
    return _get("GEMINI_API_KEY")


def gemini_model() -> str:
    return _get("GEMINI_MODEL", "gemini-2.5-flash")


def db_path() -> str:
    return _get("DB_PATH", "jobmatch.db")


def app_passcode() -> str:
    """If set, the app and API require this passcode. Empty = no passcode."""
    return _get("APP_PASSCODE")


def passcode_mandatory() -> bool:
    """True on the online server (REQUIRE_PASSCODE=true): refuse to start without a passcode."""
    return _get("REQUIRE_PASSCODE").lower() in ("1", "true", "yes")


def cors_origins() -> list[str]:
    """Comma-separated list of allowed frontend origins. '*' allows all."""
    raw = _get("CORS_ORIGINS", "*")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]
