"""Compose a vertical Short (1080x1920) from a draft, using ffmpeg.

Pipeline (all local/free):
  caption -> spoken script -> TTS voiceover -> ffmpeg burns wrapped captions
  over a background, synced to the audio duration -> H.264 mp4.

The ffmpeg command is built by a pure function (`build_ffmpeg_cmd`) so it can be
unit-tested without ffmpeg installed. Quality is intentionally basic — this is
the free baseline; swap in Piper voices, stock footage, or a real editor later.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import textwrap
from pathlib import Path

from trendengine.config import PROJECT_ROOT, Config
from trendengine.logging_setup import get_logger
from trendengine.media import MediaError
from trendengine.media.tts import synthesize

log = get_logger(__name__)

_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]", flags=re.UNICODE)


def script_from_caption(caption: str, max_seconds: int) -> str:
    """Spoken script: drop hashtags/emoji/URLs, keep enough for the duration
    (~2.5 words/sec)."""
    text = re.sub(r"#\w+", "", caption or "")
    text = re.sub(r"https?://\S+", "", text)
    text = _EMOJI.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    max_words = int(max_seconds * 2.5)
    words = text.split()
    if len(words) > max_words:
        text = " ".join(words[:max_words])
    return text


def wrap_caption(caption: str, width: int = 22, max_lines: int = 10) -> str:
    """Wrap for on-screen display (big text, few chars per line)."""
    clean = _EMOJI.sub("", caption or "")
    clean = re.sub(r"\s+", " ", clean).strip()
    lines = textwrap.wrap(clean, width=width)[:max_lines]
    return "\n".join(lines)


def _drawtext_escape(text: str) -> str:
    # ffmpeg drawtext metacharacters.
    return (text.replace("\\", "\\\\").replace(":", "\\:")
            .replace("'", "’").replace("%", "\\%"))


def build_ffmpeg_cmd(out_path: Path, duration: float, media_cfg: dict,
                     text_file: Path, audio_path: Path | None,
                     title_file: Path | None = None) -> list[str]:
    """Build the ffmpeg argument list. Pure/testable — no execution."""
    res = media_cfg.get("resolution", "1080x1920")
    fps = int(media_cfg.get("fps", 30))
    bg = media_cfg.get("background", "gradient")
    color = media_cfg.get("background_color", "#0f1216").lstrip("#")
    font = media_cfg.get("font", "")

    cmd = ["ffmpeg", "-y"]
    # -- background input --
    if bg == "image" and media_cfg.get("background_image"):
        cmd += ["-loop", "1", "-t", f"{duration:.2f}", "-i",
                media_cfg["background_image"]]
    else:
        # Solid colour (reliable everywhere). "gradient" degrades to solid.
        cmd += ["-f", "lavfi", "-t", f"{duration:.2f}",
                "-i", f"color=c=0x{color}:s={res}:r={fps}"]

    # -- audio input --
    if audio_path is not None:
        cmd += ["-i", str(audio_path)]

    # -- drawtext filter(s): body (centered) + optional title (top) --
    fontfile = f":fontfile='{font}'" if font else ""
    body = (f"drawtext=textfile='{text_file}'{fontfile}:fontcolor=white:"
            f"fontsize=54:line_spacing=14:x=(w-text_w)/2:y=(h-text_h)/2:"
            f"box=1:boxcolor=black@0.35:boxborderw=28")
    filters = [body]
    if title_file is not None:
        filters.insert(0,
            f"drawtext=textfile='{title_file}'{fontfile}:fontcolor=white:"
            f"fontsize=64:x=(w-text_w)/2:y=180:box=1:boxcolor=black@0.5:boxborderw=24")
    cmd += ["-vf", ",".join(filters)]

    # -- output --
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps)]
    if audio_path is not None:
        cmd += ["-c:a", "aac", "-b:a", "128k", "-shortest"]
    cmd += ["-t", f"{duration:.2f}", str(out_path)]
    return cmd


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


class ShortGenerator:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.media = config.raw.get("media", {})

    def render(self, caption: str, topic: str, draft_id: int) -> Path:
        if not self.media.get("enabled", True):
            raise MediaError("media.enabled is false — cannot render a Short.")
        if shutil.which("ffmpeg") is None:
            raise MediaError(
                "ffmpeg not found. Install it (macOS: `brew install ffmpeg`) to "
                "render Shorts, or set autopilot.mode: shadow to skip rendering.")

        work = PROJECT_ROOT / self.media.get("work_dir", "media_out")
        work.mkdir(parents=True, exist_ok=True)
        stem = work / f"draft_{draft_id}"

        max_seconds = int(self.media.get("max_seconds", 55))
        # 1) voiceover
        script = script_from_caption(caption, max_seconds)
        audio = synthesize(script, stem, self.config) if script else None
        # 2) duration
        duration = _probe_duration(audio) if audio else None
        if not duration:
            duration = min(max_seconds, max(6.0, len(script.split()) / 2.5))
        duration = min(duration, max_seconds)
        # 3) caption + title text files
        text_file = stem.with_suffix(".txt")
        text_file.write_text(_drawtext_escape(wrap_caption(caption)), encoding="utf-8")
        title_file = stem.with_name(f"{stem.name}_title.txt")
        title_file.write_text(_drawtext_escape(wrap_caption(topic, width=18, max_lines=2)),
                              encoding="utf-8")
        # 4) render
        out_path = stem.with_suffix(".mp4")
        cmd = build_ffmpeg_cmd(out_path, duration, self.media, text_file,
                               audio, title_file)
        log.info("Rendering Short for draft #%d (%.1fs)…", draft_id, duration)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not out_path.exists():
            raise MediaError(f"ffmpeg failed: {proc.stderr[-500:]}")
        return out_path
