"""ClipGenerator: authorized source video -> short vertical clips.

Pipeline: download the authorized source (+ captions) with yt-dlp -> ask the
local LLM to pick the strongest moments from the transcript -> ffmpeg cuts each
window, center-crops to 9:16, and burns the caption subtitles.

Pure, testable units: `parse_moments` (LLM output -> validated windows) and
`build_clip_cmd` (ffmpeg args). The download/render steps shell out and are
mocked in tests (no yt-dlp/ffmpeg needed to test the logic).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from trendengine.clipping import ClipError
from trendengine.clipping.campaign import Campaign, ensure_authorized
from trendengine.clipping.transcript import (Segment, digest, parse_vtt, to_srt,
                                             window)
from trendengine.config import PROJECT_ROOT, Config
from trendengine.generation.drafter import _parse_llm_json
from trendengine.llm.base import LLMClient, LLMError
from trendengine.logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class Moment:
    start: float
    end: float
    hook: str

    @property
    def length(self) -> float:
        return self.end - self.start


@dataclass
class ClipResult:
    path: Path
    moment: Moment
    caption: str


def parse_moments(raw: str, min_s: int, max_s: int, limit: int,
                  source_duration: float = 0.0) -> list[Moment]:
    """Validate LLM-proposed windows: clamp length to [min_s, max_s], drop
    out-of-range/degenerate ones, cap to `limit`."""
    try:
        data = _parse_llm_json(raw if raw.strip().startswith("{")
                               else '{"clips": %s}' % raw)
    except ValueError:
        return []
    items = data.get("clips", data if isinstance(data, list) else [])
    moments: list[Moment] = []
    for it in items:
        try:
            start = float(it["start"])
            end = float(it["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end <= start:
            continue
        # Clamp to max length; skip if below the minimum.
        if end - start > max_s:
            end = start + max_s
        if end - start < min_s:
            continue
        if source_duration and start >= source_duration:
            continue
        moments.append(Moment(start, end, str(it.get("hook", "")).strip()))
        if len(moments) >= limit:
            break
    return moments


def build_clip_cmd(src: str, out: str, start: float, end: float,
                   resolution: str = "1080x1920", srt: str | None = None,
                   font: str | None = None) -> list[str]:
    """ffmpeg args to cut [start,end], center-crop to 9:16, scale, burn subs.

    `-ss`/`-t` before `-i` gives a fast seek; the crop makes any aspect ratio
    vertical without distortion (crop first, then scale)."""
    w, h = resolution.split("x")
    # Center-crop to a 9:16 column, then scale to the target size.
    vf = f"crop='min(iw,ih*9/16)':ih,scale={w}:{h}:flags=bicubic"
    if srt:
        style = "FontSize=14,Outline=1,Alignment=2,MarginV=120"
        force = f":force_style='{style}'"
        fontdir = f":fontsdir='{Path(font).parent}'" if font else ""
        vf += f",subtitles='{srt}'{fontdir}{force}"
    return [
        "ffmpeg", "-y",
        "-ss", f"{start:.2f}", "-t", f"{end - start:.2f}", "-i", src,
        "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        out,
    ]


_MOMENT_SYSTEM = (
    "You find the most clippable moments in a video transcript — self-contained, "
    "hooky segments that stop the scroll. You reply with ONLY JSON.")


def build_moment_prompt(segments: list[Segment], campaign: Campaign) -> str:
    return f"""\
From this timestamped transcript, pick the {campaign.clips_per_source} best
moments to cut into short vertical clips. Each must be a self-contained, engaging
segment between {campaign.min_seconds} and {campaign.max_seconds} seconds.

Prefer: strong hooks, surprising claims, emotional peaks, complete stories or
tips. Avoid: mid-sentence starts, filler, dead air.

TRANSCRIPT (seconds in brackets):
{digest(segments)}

Respond with ONLY JSON:
{{"clips": [{{"start": <seconds>, "end": <seconds>, "hook": "why this clips well"}}]}}
"""


class ClipGenerator:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.media = config.raw.get("media", {})
        self.work = PROJECT_ROOT / self.media.get("work_dir", "media_out") / "clips"

    # -- download (yt-dlp) -------------------------------------------------
    def download(self, url: str) -> tuple[Path, list[Segment]]:
        if shutil.which("yt-dlp") is None:
            raise ClipError("yt-dlp not found. Install it: `pip install yt-dlp`.")
        self.work.mkdir(parents=True, exist_ok=True)
        stem = self.work / _safe_stem(url)
        # Download video + auto/uploaded English subs in one call.
        cmd = ["yt-dlp", "-f", "mp4/best", "--write-auto-sub", "--write-sub",
               "--sub-lang", "en.*", "--sub-format", "vtt",
               "-o", f"{stem}.%(ext)s", url]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise ClipError(f"yt-dlp failed: {proc.stderr[-400:]}")
        video = next(iter(sorted(self.work.glob(f"{stem.name}.mp4"))), None)
        if video is None:
            raise ClipError("yt-dlp produced no mp4 (source may be unavailable).")
        vtt = next(iter(sorted(self.work.glob(f"{stem.name}*.vtt"))), None)
        segments = parse_vtt(vtt.read_text(encoding="utf-8")) if vtt else []
        return video, segments

    # -- moment selection (LLM) --------------------------------------------
    def select_moments(self, segments: list[Segment], campaign: Campaign,
                       llm: LLMClient) -> list[Moment]:
        if not segments:
            return []
        from trendengine.clipping.transcript import duration
        prompt = build_moment_prompt(segments, campaign)
        try:
            raw = llm.generate(prompt, system=_MOMENT_SYSTEM, temperature=0.4)
        except LLMError as exc:
            raise ClipError(f"moment selection failed: {exc}") from exc
        return parse_moments(raw, campaign.min_seconds, campaign.max_seconds,
                             campaign.clips_per_source, duration(segments))

    # -- render ------------------------------------------------------------
    def render_clip(self, video: Path, moment: Moment,
                    segments: list[Segment], idx: int) -> Path:
        if shutil.which("ffmpeg") is None:
            raise ClipError("ffmpeg not found (macOS: `brew install ffmpeg`).")
        self.work.mkdir(parents=True, exist_ok=True)
        srt_path = None
        seg = window(segments, moment.start, moment.end)
        if seg:
            srt_path = self.work / f"{video.stem}_{idx}.srt"
            srt_path.write_text(to_srt(seg, offset=moment.start), encoding="utf-8")
        out = self.work / f"{video.stem}_clip{idx}.mp4"
        cmd = build_clip_cmd(str(video), str(out), moment.start, moment.end,
                             self.media.get("resolution", "1080x1920"),
                             srt=str(srt_path) if srt_path else None,
                             font=self.media.get("font") or None)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not out.exists():
            raise ClipError(f"ffmpeg clip failed: {proc.stderr[-400:]}")
        return out

    # -- one source end to end ---------------------------------------------
    def clip_source(self, campaign: Campaign, url: str,
                    llm: LLMClient) -> list[ClipResult]:
        ensure_authorized(campaign)   # HARD gate — no rights, no clipping
        video, segments = self.download(url)
        moments = self.select_moments(segments, campaign, llm)
        results: list[ClipResult] = []
        for idx, moment in enumerate(moments):
            path = self.render_clip(video, moment, segments, idx)
            caption = _clip_caption(moment, campaign)
            results.append(ClipResult(path=path, moment=moment, caption=caption))
        log.info("Clipped %d segments from %s", len(results), url)
        return results


def _clip_caption(moment: Moment, campaign: Campaign) -> str:
    head = moment.hook or "Watch this 👀"
    suffix = campaign.caption_suffix()
    return f"{head}\n\n{suffix}".strip()


def _safe_stem(url: str) -> str:
    import hashlib
    return "src_" + hashlib.sha256(url.encode()).hexdigest()[:12]
