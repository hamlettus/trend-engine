"""Transcript handling for clipping: parse captions, window them, write SRT.

We use the source video's own captions (fetched by yt-dlp, free) both to let the
LLM pick the strongest moments and to burn accurate subtitles into each clip —
captions materially lift short-form retention.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_TS = re.compile(r"(\d{2}):(\d{2}):(\d{2})[.,](\d{3})")
_CUE = re.compile(
    r"(\d{2}:\d{2}:\d{2}[.,]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[.,]\d{3})")
_TAG = re.compile(r"<[^>]+>")


@dataclass
class Segment:
    start: float   # seconds
    end: float
    text: str


def _to_seconds(ts: str) -> float:
    m = _TS.search(ts)
    if not m:
        return 0.0
    h, mm, s, ms = (int(m.group(i)) for i in range(1, 5))
    return h * 3600 + mm * 60 + s + ms / 1000.0


def _to_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_vtt(text: str) -> list[Segment]:
    """Parse WebVTT/SRT caption text into de-duplicated Segments.

    YouTube auto-captions repeat rolling lines; we keep the last text per cue
    and drop empties so the transcript reads cleanly.
    """
    segments: list[Segment] = []
    lines = text.splitlines()
    i = 0
    last_text = None
    while i < len(lines):
        cue = _CUE.search(lines[i])
        if not cue:
            i += 1
            continue
        start, end = _to_seconds(cue.group(1)), _to_seconds(cue.group(2))
        i += 1
        buf = []
        while i < len(lines) and lines[i].strip() and not _CUE.search(lines[i]):
            buf.append(_TAG.sub("", lines[i]).strip())
            i += 1
        content = " ".join(t for t in buf if t).strip()
        if content and content != last_text:
            segments.append(Segment(start, end, content))
            last_text = content
    return segments


def window(segments: list[Segment], start: float, end: float) -> list[Segment]:
    """Segments overlapping [start, end], clipped to the window."""
    out = []
    for s in segments:
        if s.end <= start or s.start >= end:
            continue
        out.append(Segment(max(s.start, start), min(s.end, end), s.text))
    return out


def to_srt(segments: list[Segment], offset: float = 0.0) -> str:
    """Render segments as SRT (times shifted by -offset so a clip starts at 0)."""
    blocks = []
    for idx, s in enumerate(segments, 1):
        blocks.append(f"{idx}\n{_to_ts(s.start - offset)} --> "
                      f"{_to_ts(s.end - offset)}\n{s.text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def digest(segments: list[Segment], max_chars: int = 6000) -> str:
    """Compact timestamped transcript for the moment-selection LLM prompt."""
    lines = []
    total = 0
    for s in segments:
        line = f"[{int(s.start)}s] {s.text}"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)


def duration(segments: list[Segment]) -> float:
    return segments[-1].end if segments else 0.0
