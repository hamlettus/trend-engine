"""Content hashing for deduplication."""
from __future__ import annotations

import hashlib
import re

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")


def normalize_text(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — for stable hashing."""
    text = (text or "").lower()
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


def content_hash(source: str, title: str, url: str) -> str:
    """Stable SHA-256 for a piece of discovered content.

    URL is normalized (strip query/fragment) so the same article surfaced with
    tracking params dedupes correctly.
    """
    clean_url = (url or "").split("?")[0].split("#")[0].rstrip("/").lower()
    basis = f"{source}|{normalize_text(title)}|{clean_url}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()
