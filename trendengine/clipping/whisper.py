"""Whisper transcription fallback for caption-less sources.

When yt-dlp finds no captions on a source video, we extract its audio and
transcribe it so the clipper can still find moments and burn subtitles.

Default backend is **Groq** (`whisper-large-v3`, free tier) — it reuses the same
GROQ_API_KEY as the LLM, so nothing new to set up. OpenAI's `whisper-1` works
too (set media.whisper_backend: openai + OPENAI_API_KEY). Audio is compressed to
mono 16 kHz so it stays well under the 25 MB upload cap for typical clips.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import requests

from trendengine.clipping.transcript import Segment
from trendengine.config import Config
from trendengine.logging_setup import get_logger

log = get_logger(__name__)

_UPLOAD_CAP_MB = 25

_ENDPOINTS = {
    "groq": ("https://api.groq.com/openai/v1/audio/transcriptions", "GROQ_API_KEY",
             "whisper-large-v3"),
    "openai": ("https://api.openai.com/v1/audio/transcriptions", "OPENAI_API_KEY",
               "whisper-1"),
}


class WhisperError(RuntimeError):
    """Audio extraction or transcription failed."""


def extract_audio(video_path: Path, out_path: Path) -> Path:
    """Extract compressed mono 16 kHz audio (small, transcription-friendly)."""
    if shutil.which("ffmpeg") is None:
        raise WhisperError("ffmpeg not found — needed to extract audio.")
    cmd = ["ffmpeg", "-y", "-i", str(video_path), "-vn", "-ac", "1",
           "-ar", "16000", "-c:a", "aac", "-b:a", "32k", str(out_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out_path.exists():
        raise WhisperError(f"audio extraction failed: {proc.stderr[-300:]}")
    return out_path


def _parse_segments(payload: dict) -> list[Segment]:
    segs = []
    for s in payload.get("segments", []) or []:
        try:
            segs.append(Segment(float(s["start"]), float(s["end"]),
                                str(s.get("text", "")).strip()))
        except (KeyError, TypeError, ValueError):
            continue
    return segs


def transcribe(audio_path: Path, config: Config) -> list[Segment]:
    """Transcribe audio to timestamped Segments via the configured backend."""
    media = config.raw.get("media", {})
    backend = (media.get("whisper_backend", "groq") or "groq").lower()
    if backend not in _ENDPOINTS:
        raise WhisperError(f"unknown whisper_backend '{backend}' (groq|openai)")
    url, key_env, default_model = _ENDPOINTS[backend]
    api_key = Config.env(key_env)
    if not api_key:
        raise WhisperError(
            f"{key_env} not set — needed for the {backend} Whisper fallback "
            f"(free key: https://console.groq.com/keys)." if backend == "groq"
            else f"{key_env} not set — needed for the {backend} Whisper fallback.")

    size_mb = audio_path.stat().st_size / 1e6
    if size_mb > _UPLOAD_CAP_MB:
        raise WhisperError(
            f"audio is {size_mb:.0f} MB, over the {_UPLOAD_CAP_MB} MB cap — this "
            "source is too long for single-shot transcription (chunking TODO).")

    model = media.get("whisper_model") or default_model
    with open(audio_path, "rb") as fh:
        try:
            resp = requests.post(
                url, headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (audio_path.name, fh)},
                data={"model": model, "response_format": "verbose_json"},
                timeout=int(media.get("whisper_timeout_seconds", 180)))
        except requests.exceptions.RequestException as exc:
            raise WhisperError(f"{backend} transcription request failed: {exc}") from exc

    if resp.status_code == 401:
        raise WhisperError(f"{backend} rejected {key_env} (401).")
    if resp.status_code != 200:
        raise WhisperError(f"{backend} transcription error {resp.status_code}: "
                          f"{resp.text[:200]}")
    segments = _parse_segments(resp.json())
    log.info("Whisper (%s) transcribed %d segments from %s",
             backend, len(segments), audio_path.name)
    return segments
