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


def _probe_duration(audio_path: Path) -> float | None:
    if shutil.which("ffprobe") is None:
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(audio_path)],
            capture_output=True, text=True, check=True)
        return float(out.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        return None


def _extract_chunk(audio_path: Path, start: float, dur: float, out: Path) -> Path:
    cmd = ["ffmpeg", "-y", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}",
           "-i", str(audio_path), "-ac", "1", "-ar", "16000",
           "-c:a", "aac", "-b:a", "32k", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out.exists():
        raise WhisperError(f"chunk extraction failed: {proc.stderr[-200:]}")
    return out


def _request(audio_path: Path, url: str, api_key: str, model: str,
             backend: str, timeout: int) -> dict:
    """One transcription request. Raises WhisperError on any failure."""
    with open(audio_path, "rb") as fh:
        try:
            resp = requests.post(
                url, headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (audio_path.name, fh)},
                data={"model": model, "response_format": "verbose_json"},
                timeout=timeout)
        except requests.exceptions.RequestException as exc:
            raise WhisperError(f"{backend} transcription request failed: {exc}") from exc
    if resp.status_code == 401:
        raise WhisperError(f"{backend} rejected the API key (401).")
    if resp.status_code != 200:
        raise WhisperError(f"{backend} transcription error {resp.status_code}: "
                          f"{resp.text[:200]}")
    return resp.json()


def transcribe(audio_path: Path, config: Config) -> list[Segment]:
    """Transcribe audio to timestamped Segments via the configured backend.

    Audio over the upload cap is split into time chunks, transcribed separately,
    and stitched back into absolute source time. Per-chunk failures are tolerated
    (a partial transcript is still useful); it only errors if every chunk fails.
    """
    media = config.raw.get("media", {})
    backend = (media.get("whisper_backend", "groq") or "groq").lower()
    if backend not in _ENDPOINTS:
        raise WhisperError(f"unknown whisper_backend '{backend}' (groq|openai)")
    url, key_env, default_model = _ENDPOINTS[backend]
    api_key = Config.env(key_env)
    if not api_key:
        raise WhisperError(
            f"{key_env} not set — needed for the {backend} Whisper fallback "
            + ("(free key: https://console.groq.com/keys)." if backend == "groq" else "."))
    model = media.get("whisper_model") or default_model
    timeout = int(media.get("whisper_timeout_seconds", 180))

    size_mb = audio_path.stat().st_size / 1e6
    if size_mb <= _UPLOAD_CAP_MB:
        segments = _parse_segments(
            _request(audio_path, url, api_key, model, backend, timeout))
        log.info("Whisper (%s) transcribed %d segments from %s",
                 backend, len(segments), audio_path.name)
        return segments

    # -- too big: chunk it --
    chunk_s = float(media.get("whisper_chunk_seconds", 600))
    # Prefer a real probe; else estimate from size at ~0.24 MB/min (our bitrate).
    duration = _probe_duration(audio_path) or (size_mb / 0.24) * 60.0
    log.info("Whisper: audio %.0f MB (~%.0f min) — chunking at %.0fs.",
             size_mb, duration / 60, chunk_s)

    segments: list[Segment] = []
    failures = chunks = 0
    start = 0.0
    while start < duration:
        chunks += 1
        span = min(chunk_s, duration - start)
        chunk = audio_path.with_name(f"{audio_path.stem}_chunk{chunks}.m4a")
        try:
            _extract_chunk(audio_path, start, span, chunk)
            payload = _request(chunk, url, api_key, model, backend, timeout)
            for seg in _parse_segments(payload):
                segments.append(Segment(seg.start + start, seg.end + start, seg.text))
        except WhisperError as exc:
            failures += 1
            log.warning("Whisper chunk %d failed: %s", chunks, exc)
        finally:
            chunk.unlink(missing_ok=True)
        start += chunk_s

    if not segments and failures:
        raise WhisperError(f"all {chunks} transcription chunks failed.")
    log.info("Whisper (%s) transcribed %d segments across %d chunks (%d failed).",
             backend, len(segments), chunks, failures)
    return segments
