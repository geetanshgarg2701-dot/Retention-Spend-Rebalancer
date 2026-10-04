"""Where the Gemini key and model name come from. The key is never printed or logged.

Order: real environment variables first, then a local .env file, then Streamlit secrets.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

ENV_PATH = Path(__file__).parent.parent / ".env"
PLACEHOLDER = "your-key-here"


def load_env(path: Optional[Path] = None) -> bool:
    """Load a local .env file without overriding variables that are already set. True if a file was read."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False
    target = Path(path) if path else ENV_PATH
    return bool(target.exists() and load_dotenv(target, override=False))


def _secret(name: str) -> Optional[str]:
    try:
        import streamlit as st

        value = st.secrets.get(name)
    except Exception:
        return None
    return str(value) if value else None


def get_settings() -> tuple[Optional[str], Optional[str]]:
    """The key and model name, or None for either one that is missing or still the placeholder."""
    load_env()
    key = os.environ.get("GEMINI_API_KEY") or _secret("GEMINI_API_KEY")
    model = os.environ.get("GEMINI_MODEL") or _secret("GEMINI_MODEL")
    if not key or key == PLACEHOLDER:
        key = None
    return key, model or None


def ai_available() -> bool:
    key, model = get_settings()
    return bool(key and model)
