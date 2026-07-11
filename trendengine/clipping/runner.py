"""Run a clipping campaign end to end, and compute earnings.

Produces clips from a campaign's AUTHORIZED sources and queues each as a Draft
(reusing the whole existing pipeline: gate, publish, learning, metrics). In
shadow mode nothing is uploaded; in live mode it publishes to the campaign's
platforms. Earnings = accumulated views x the campaign's per-1K rate.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from trendengine.clipping.campaign import (Campaign, ensure_authorized,
                                           get_campaign, load_campaigns)
from trendengine.clipping.clipper import ClipGenerator
from trendengine.config import Config
from trendengine.db.database import session_scope
from trendengine.db.models import (STATUS_POSTED, STATUS_SHADOW, Draft,
                                   PostHistory, PostMetric)
from trendengine.llm import get_llm
from trendengine.logging_setup import get_logger
from trendengine.publishers import get_publisher

log = get_logger(__name__)


@dataclass
class ClipRunStats:
    campaign: str = ""
    clips: int = 0
    posted: int = 0
    shadowed: int = 0
    failed: int = 0
    draft_ids: list[int] = field(default_factory=list)
    note: str = ""

    def summary(self) -> str:
        return (f"campaign={self.campaign} clips={self.clips} posted={self.posted} "
                f"shadow={self.shadowed} failed={self.failed}"
                + (f" — {self.note}" if self.note else ""))


def run_clip_campaign(config: Config, campaign_id: str,
                      live: bool = False) -> ClipRunStats:
    stats = ClipRunStats(campaign=campaign_id)
    campaign = get_campaign(campaign_id)
    ensure_authorized(campaign)   # refuses unauthorized sources up front

    llm = get_llm(config)
    clipper = ClipGenerator(config)
    platform = (campaign.platforms or ["youtube"])[0]

    for url in campaign.source_urls:
        try:
            results = clipper.clip_source(campaign, url, llm)
        except Exception as exc:  # noqa: BLE001 - one bad source shouldn't kill the run
            log.error("Clipping failed for %s: %s", url, exc)
            stats.note = str(exc)[:200]
            continue

        for res in results:
            stats.clips += 1
            draft_id = _persist_clip(config, campaign, url, res, platform)
            stats.draft_ids.append(draft_id)
            if not live:
                _mark(draft_id, STATUS_SHADOW)
                stats.shadowed += 1
                continue
            try:
                _publish(config, platform, draft_id)
                stats.posted += 1
            except Exception as exc:  # noqa: BLE001
                _mark(draft_id, "failed", note=str(exc)[:300])
                stats.failed += 1
                log.error("Publish failed for clip #%d: %s", draft_id, exc)

    log.info("Clip run: %s", stats.summary())
    return stats


def campaign_earnings(config: Config) -> list[dict]:
    """Per-campaign accumulated views and estimated payout."""
    campaigns = load_campaigns()
    out = []
    with session_scope() as s:
        for cid, camp in campaigns.items():
            drafts = s.query(Draft).filter(Draft.campaign == cid,
                                          Draft.status == STATUS_POSTED).all()
            views = 0
            for d in drafts:
                m = (s.query(PostMetric).filter_by(draft_id=d.id)
                     .order_by(PostMetric.fetched_at.desc()).first())
                if m:
                    views += int(m.views or 0)
            out.append({
                "campaign": cid, "name": camp.name, "posts": len(drafts),
                "views": views, "rate_per_1k": camp.payout_per_1k_views,
                "estimated_payout": round(views / 1000.0 * camp.payout_per_1k_views, 2),
            })
    return out


# -- helpers ---------------------------------------------------------------

def _persist_clip(config, campaign: Campaign, url, res, platform) -> int:
    hashtags = " ".join(campaign.required_hashtags)
    with session_scope() as s:
        d = Draft(
            topic=res.moment.hook[:200] or campaign.name, platform=platform,
            caption=res.caption, hashtags=hashtags, campaign=campaign.id,
            source_url=url, clip_start=res.moment.start, clip_end=res.moment.end,
            video_path=str(res.path), status="pending", auto=True, score=1.0,
            llm_provider="clip", llm_model="ffmpeg")
        s.add(d)
        s.flush()
        return d.id


def _mark(draft_id: int, status: str, note: str = "") -> None:
    import datetime as dt
    with session_scope() as s:
        d = s.get(Draft, draft_id)
        if d:
            d.status = status
            if status in (STATUS_SHADOW, STATUS_POSTED):
                d.posted_at = dt.datetime.now(dt.timezone.utc)
            if note:
                d.gate_notes = (d.gate_notes + " | " + note).strip(" |")


def _publish(config, platform, draft_id: int) -> None:
    import datetime as dt
    publisher = get_publisher(config, platform)
    with session_scope() as s:
        d = s.get(Draft, draft_id)
        res = publisher.publish(d)
        if not res.ok:
            raise RuntimeError(res.message)
        d.status = STATUS_POSTED
        d.posted_at = dt.datetime.now(dt.timezone.utc)
        d.external_post_id = res.external_post_id
        s.add(PostHistory(draft_id=d.id, platform=platform, caption=d.caption,
                          external_post_id=res.external_post_id))
