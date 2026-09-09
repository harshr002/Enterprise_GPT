"""Central configuration, loaded from environment / .env file."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


def _load_dotenv() -> None:
    """Tiny .env loader (avoids an extra dependency)."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        # Do not override variables already set in the real environment.
        os.environ.setdefault(key, value)


_load_dotenv()


class Settings:
    """Resolved application settings."""

    def __init__(self) -> None:
        self.gemini_api_key: str = os.getenv("GEMINI_API_KEY", "").strip()
        self.chat_model: str = os.getenv("GEMINI_CHAT_MODEL", "gemini-2.0-flash")
        self.embed_model: str = os.getenv("GEMINI_EMBED_MODEL", "text-embedding-004")

        self.top_k: int = int(os.getenv("TOP_K", "5"))
        self.relevance_threshold: float = float(os.getenv("RELEVANCE_THRESHOLD", "0.62"))

        db_path = os.getenv("DATABASE_PATH", "./data/knowledge.db")
        self.database_path: Path = Path(db_path).resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

        self.cors_origins: list[str] = [
            o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()
        ]

        # Base URL for Gemini's REST API.
        self.gemini_base: str = "https://generativelanguage.googleapis.com/v1beta"

    @property
    def llm_ready(self) -> bool:
        """True when a real API key is configured."""
        return bool(self.gemini_api_key) and self.gemini_api_key != "your_gemini_api_key_here"


@lru_cache
def get_settings() -> Settings:
    return Settings()
