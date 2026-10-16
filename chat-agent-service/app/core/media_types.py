"""Accepted chat media types: MIME -> file extension (image) / input_audio format (audio)."""
from __future__ import annotations

IMAGE_MIMES: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}

# Values are the OpenAI/OpenRouter `input_audio.format` names (also used as file extension).
AUDIO_FORMATS: dict[str, str] = {
    "audio/wav": "wav",
    "audio/mpeg": "mp3",
    "audio/ogg": "ogg",
    "audio/flac": "flac",
    "audio/aac": "aac",
    "audio/mp4": "m4a",
}

_ALIASES = {
    "image/jpg": "image/jpeg",
    "audio/x-wav": "audio/wav",
    "audio/wave": "audio/wav",
    "audio/vnd.wave": "audio/wav",
    "audio/mp3": "audio/mpeg",
    "audio/x-flac": "audio/flac",
    "audio/x-m4a": "audio/mp4",
    "audio/m4a": "audio/mp4",
}


def normalize_mime(mime: str | None) -> str:
    mime = (mime or "").split(";")[0].strip().lower()
    return _ALIASES.get(mime, mime)
