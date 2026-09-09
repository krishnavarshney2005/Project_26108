"""
ai-engine/src/llm_config.py

Single source of truth for Gemini configuration in the AI engine.

Why this exists:
  - The model name used to be hardcoded as a string literal in four different
    files. When Google changes model availability, that meant editing every
    call site. It now lives in one place and is overridable via the
    GEMINI_MODEL environment variable.
  - The API key used to be read from AI_ENGINE_GEMINI_KEY, which nothing set,
    so every LLM call silently fell back to regex/mock. Key resolution now
    matches the backend (GOOGLE_API_KEY) while still honouring the older names
    for backwards compatibility.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Optionally load a local .env so `GOOGLE_API_KEY=...` in ai-engine/.env
# (or the process environment on Render) is picked up automatically.
# python-dotenv is optional — if it isn't installed we just rely on the
# real environment.
try:  # pragma: no cover - trivial import guard
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass


# Default is the model that is currently available on the API. Override with
# the GEMINI_MODEL env var if Google deprecates it (verify with
# `client.models.list()` before changing the default).
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")

# Env var names checked in priority order. GOOGLE_API_KEY is the primary name
# (shared with the backend); the rest are accepted for backwards compatibility.
_API_KEY_ENV_NAMES = (
    "GOOGLE_API_KEY",
    "AI_ENGINE_GEMINI_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY_2",
)


def get_gemini_api_key() -> Optional[str]:
    """Return the first Gemini API key found across the supported env vars."""
    for name in _API_KEY_ENV_NAMES:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def get_gemini_client():
    """
    Return a configured google-genai Client.

    Raises
    ------
    RuntimeError
        If no API key is set in any of the supported environment variables.
    """
    api_key = get_gemini_api_key()
    if not api_key:
        raise RuntimeError(
            "No Gemini API key configured. Set GOOGLE_API_KEY "
            "(see ai-engine/.env.example)."
        )
    from google import genai

    return genai.Client(api_key=api_key)
