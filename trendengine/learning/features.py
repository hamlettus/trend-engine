"""Content-feature extraction — shared by the public reference corpus AND our
own drafts, so the same "what works" signal is measured consistently on both.

These map a piece of content onto the SAME axes the bandit optimises
(caption style, hashtag count, post hour), which is what lets us warm-start the
bandit from external winners instead of waiting on our own post history.
"""
from __future__ import annotations

import re

_NUM_LIST = re.compile(r"^\s*\d+\b|\b\d+\s+(things|ways|tips|reasons|tools|steps|"
                       r"tricks|hacks|rules|signs|mistakes)\b", re.IGNORECASE)
_HOOK_STARTS = ("why", "how", "the", "this", "stop", "never", "you", "what")
_HASHTAG = re.compile(r"#\w+")


def classify_style(text: str) -> str:
    """Bucket a title/caption into one of the caption_style bandit arms."""
    t = (text or "").strip().lower()
    if not t:
        return "bold_claim"
    if "?" in t:
        return "question"
    if _NUM_LIST.search(t):
        return "listicle"
    if t.split()[0] in _HOOK_STARTS:
        return "hook_first"
    return "bold_claim"


def count_hashtags(text: str) -> int:
    return len(_HASHTAG.findall(text or ""))


def nearest(value: float, options: list) -> str:
    """Snap a value to the nearest configured arm option (returned as str)."""
    if not options:
        return str(value)
    best = min(options, key=lambda o: abs(float(o) - float(value)))
    return str(best)


def hour_bucket(hour: int, slots: list[int]) -> int:
    if not slots:
        return int(hour)
    return int(min(slots, key=lambda s: abs(int(s) - int(hour))))


def percentiles(values: list[float]) -> list[float]:
    """Rank each value to a 0..1 percentile (min-max of ranks)."""
    import numpy as np
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [1.0]
    order = np.argsort(values)
    ranks = np.empty(n, dtype=float)
    ranks[order] = np.arange(n, dtype=float)
    return list(ranks / (n - 1))


def content_features(title: str, hashtags_text: str = "") -> dict:
    """Transferable virality features that exist for BOTH external content and
    our drafts (used for reporting and the optional content-weight model)."""
    title = title or ""
    return {
        "title_len": len(title),
        "word_count": len(title.split()),
        "has_number": 1 if re.search(r"\d", title) else 0,
        "has_question": 1 if "?" in title else 0,
        "hashtag_count": count_hashtags(f"{title} {hashtags_text}"),
    }


def derive_arms(title: str, hashtags_text: str, publish_hour: int,
                arms_spec: dict) -> dict:
    """Map a public item onto the engine's bandit-arm value space."""
    style = classify_style(title)
    hc = count_hashtags(f"{title} {hashtags_text}")
    arms = {}
    if "caption_style" in arms_spec:
        arms["caption_style"] = style
    if "hashtag_count" in arms_spec:
        arms["hashtag_count"] = nearest(hc, arms_spec["hashtag_count"])
    if "post_hour" in arms_spec:
        arms["post_hour"] = str(hour_bucket(publish_hour, arms_spec["post_hour"]))
    return arms
