"""Clipping campaigns + the authorization guardrail.

A campaign is a bundle of AUTHORIZED source content plus the rules and payout
for clipping it. The whole point of this file is `ensure_authorized`: the
clipper calls it before touching any source, so content you don't have rights to
simply cannot be processed by the tool.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from trendengine.config import PROJECT_ROOT
from trendengine.logging_setup import get_logger

log = get_logger(__name__)


class CampaignError(RuntimeError):
    """Bad or missing campaign configuration."""


class UnauthorizedSource(CampaignError):
    """A campaign lacks a valid rights basis — refuse to clip it."""


@dataclass
class Campaign:
    id: str
    name: str = ""
    authorized: bool = False
    authorization_note: str = ""
    source_urls: list[str] = field(default_factory=list)
    payout_per_1k_views: float = 0.0
    platforms: list[str] = field(default_factory=lambda: ["youtube"])
    required_hashtags: list[str] = field(default_factory=list)
    required_mention: str = ""
    tracking_tag: str = ""
    min_seconds: int = 15
    max_seconds: int = 60
    clips_per_source: int = 3

    @classmethod
    def from_dict(cls, d: dict) -> "Campaign":
        if not d.get("id"):
            raise CampaignError("campaign is missing an 'id'")
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    def is_authorized(self) -> bool:
        return bool(self.authorized) and bool(str(self.authorization_note).strip())

    def caption_suffix(self) -> str:
        """Required credit / tags / tracking the campaign mandates on every clip."""
        parts = []
        if self.required_mention:
            parts.append(f"Clip of {self.required_mention}")
        if self.tracking_tag:
            parts.append(self.tracking_tag)
        if self.required_hashtags:
            parts.append(" ".join(self.required_hashtags))
        return "\n".join(parts)


def ensure_authorized(campaign: Campaign) -> None:
    """Gate every clip run. Raises unless the campaign asserts a rights basis."""
    if not campaign.is_authorized():
        raise UnauthorizedSource(
            f"Campaign '{campaign.id}' is not authorized: set `authorized: true` "
            "AND an `authorization_note` describing your rights basis (license, "
            "program, or direct permission). The clipper will not process a "
            "source without it.")


def load_campaigns(path: str | Path | None = None) -> dict[str, Campaign]:
    campaigns_path = Path(path) if path else PROJECT_ROOT / "campaigns.yaml"
    if not campaigns_path.exists():
        return {}
    with open(campaigns_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    out: dict[str, Campaign] = {}
    for entry in raw.get("campaigns", []):
        c = Campaign.from_dict(entry)
        out[c.id] = c
    return out


def get_campaign(campaign_id: str, path: str | Path | None = None) -> Campaign:
    campaigns = load_campaigns(path)
    if campaign_id not in campaigns:
        available = ", ".join(campaigns) or "(none)"
        raise CampaignError(
            f"No campaign '{campaign_id}' in campaigns.yaml. Available: {available}")
    return campaigns[campaign_id]
