"""Text-to-speech voiceover, free and local.

Backends:
  * "say"   — macOS built-in `say` (zero install, offline). Default.
  * "piper" — https://github.com/rhasspy/piper (open-source neural TTS; better
              voices). Point media.piper_voice at a downloaded .onnx voice.
  * "none"  — silent video (captions only).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from trendengine.config import Config
from trendengine.logging_setup import get_logger

log = get_logger(__name__)


def synthesize(text: str, out_path: Path, config: Config) -> Path | None:
    """Write a voiceover audio file for `text`. Returns the path, or None if
    TTS is disabled/unavailable (caller then makes a silent video)."""
    backend = (config.raw.get("media", {}).get("tts", "say") or "say").lower()
    text = text.strip()
    if not text or backend == "none":
        return None

    if backend == "say":
        if shutil.which("say") is None:
            log.warning("TTS 'say' not found (macOS only) — silent video.")
            return None
        aiff = out_path.with_suffix(".aiff")
        subprocess.run(["say", "-o", str(aiff), text], check=True)
        return aiff

    if backend == "piper":
        piper = shutil.which("piper")
        voice = config.raw.get("media", {}).get("piper_voice", "")
        if not piper or not voice:
            log.warning("piper or piper_voice not configured — silent video.")
            return None
        wav = out_path.with_suffix(".wav")
        proc = subprocess.run(
            [piper, "--model", voice, "--output_file", str(wav)],
            input=text.encode("utf-8"), check=True)
        return wav if proc.returncode == 0 else None

    log.warning("Unknown TTS backend '%s' — silent video.", backend)
    return None
