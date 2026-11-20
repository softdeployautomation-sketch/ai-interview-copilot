"""
Cloud transcription via Groq's Whisper API (free tier).
Eliminates the need for local Whisper model downloads + heavy faster-whisper install.

Falls back gracefully — if no GROQ_API_KEY, the caller should use local Whisper instead.
"""

from __future__ import annotations

import os
from pathlib import Path

import requests


def groq_api_key() -> str | None:
    """Return the Groq API key if configured, else None."""
    key = (os.environ.get("GROQ_API_KEY") or os.environ.get("OPENAI_COMPAT_API_KEY") or "").strip()
    return key or None


def groq_whisper_model() -> str:
    """Whisper model name for Groq. Default: whisper-large-v3-turbo (fastest, free)."""
    return os.environ.get("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")


def is_available() -> bool:
    """True if Groq cloud transcription is configured and ready."""
    return groq_api_key() is not None


def transcribe_path(audio_path: str | Path, language: str | None = None) -> tuple[str, dict]:
    """
    Transcribe an audio file using Groq's cloud Whisper API.

    Returns (text, meta) — same shape as the local Whisper transcribe_path()
    so callers can drop this in without other changes.
    """
    path = Path(audio_path)
    if not path.is_file():
        raise FileNotFoundError(str(path))

    key = groq_api_key()
    if not key:
        raise RuntimeError(
            "No GROQ_API_KEY configured. Get a free key at https://console.groq.com/keys "
            "and set it in your .env file."
        )

    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {key}"}
    data = {"model": groq_whisper_model(), "response_format": "verbose_json"}
    if language:
        data["language"] = language

    with open(path, "rb") as f:
        files = {"file": (path.name, f, "audio/webm")}
        resp = requests.post(url, headers=headers, data=data, files=files, timeout=120)

    if resp.status_code != 200:
        # Try to parse error nicely
        try:
            err = resp.json().get("error", {}).get("message", resp.text)
        except (ValueError, AttributeError):
            err = resp.text
        raise RuntimeError(f"Groq transcription failed ({resp.status_code}): {err}")

    payload = resp.json()
    text = (payload.get("text") or "").strip()
    meta = {
        "language": payload.get("language"),
        "duration": payload.get("duration"),
        "provider": "groq",
        "model": groq_whisper_model(),
    }
    return text, meta
