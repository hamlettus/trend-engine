"""End-to-end clip campaign run with fakes (no yt-dlp/ffmpeg/network needed)."""
from pathlib import Path

from trendengine.clipping.campaign import Campaign
from trendengine.clipping.clipper import ClipResult, Moment
from trendengine.config import PROJECT_ROOT


def _authorized_campaign():
    return Campaign(id="testcamp", name="Test", authorized=True,
                    authorization_note="direct permission from creator",
                    source_urls=["https://youtube.com/watch?v=abc"],
                    payout_per_1k_views=2.0, platforms=["youtube"],
                    required_hashtags=["#clip"], required_mention="@creator",
                    min_seconds=15, max_seconds=60, clips_per_source=2)


def _fake_clip(idx):
    p = PROJECT_ROOT / "media_out" / "clips" / f"fake{idx}.mp4"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x00")
    return ClipResult(path=p, moment=Moment(10.0 + idx, 40.0 + idx, f"hook {idx}"),
                      caption=f"hook {idx}\n\nClip of @creator #clip")


def test_shadow_clip_run_queues_drafts(config, monkeypatch):
    monkeypatch.setattr("trendengine.clipping.runner.get_campaign",
                        lambda cid: _authorized_campaign())
    monkeypatch.setattr("trendengine.clipping.runner.get_llm", lambda cfg: object())
    monkeypatch.setattr(
        "trendengine.clipping.clipper.ClipGenerator.clip_source",
        lambda self, campaign, url, llm: [_fake_clip(0), _fake_clip(1)])

    from trendengine.clipping.runner import run_clip_campaign
    stats = run_clip_campaign(config, "testcamp", live=False)
    assert stats.clips == 2 and stats.shadowed == 2 and stats.posted == 0

    from trendengine.db.database import session_scope
    from trendengine.db.models import Draft, STATUS_SHADOW
    with session_scope() as s:
        clips = s.query(Draft).filter(Draft.campaign == "testcamp").all()
        assert len(clips) == 2
        d = clips[0]
        assert d.status == STATUS_SHADOW
        assert d.source_url and d.clip_start is not None and d.video_path
        assert "@creator" in d.caption and "#clip" in d.hashtags


def test_unauthorized_campaign_is_refused(config, monkeypatch):
    bad = Campaign(id="bad", authorized=False, authorization_note="",
                   source_urls=["https://x"], platforms=["youtube"])
    monkeypatch.setattr("trendengine.clipping.runner.get_campaign", lambda cid: bad)
    monkeypatch.setattr("trendengine.clipping.runner.get_llm", lambda cfg: object())

    from trendengine.clipping.campaign import UnauthorizedSource
    from trendengine.clipping.runner import run_clip_campaign
    import pytest
    with pytest.raises(UnauthorizedSource):
        run_clip_campaign(config, "bad", live=False)


def test_live_clip_run_publishes_and_earnings_accrue(config, monkeypatch):
    monkeypatch.setattr("trendengine.clipping.runner.get_campaign",
                        lambda cid: _authorized_campaign())
    monkeypatch.setattr("trendengine.clipping.runner.get_llm", lambda cfg: object())
    monkeypatch.setattr(
        "trendengine.clipping.clipper.ClipGenerator.clip_source",
        lambda self, campaign, url, llm: [_fake_clip(0)])

    from trendengine.publishers.base import PublishResult

    class FakePub:
        name = "youtube"
        def publish(self, draft):
            return PublishResult(ok=True, message="ok", external_post_id="vid9")
    monkeypatch.setattr("trendengine.clipping.runner.get_publisher",
                        lambda cfg, name=None: FakePub())
    # campaign_earnings reloads campaigns.yaml; point it at our test campaign.
    monkeypatch.setattr("trendengine.clipping.runner.load_campaigns",
                        lambda: {"testcamp": _authorized_campaign()})

    from trendengine.clipping.runner import campaign_earnings, run_clip_campaign
    stats = run_clip_campaign(config, "testcamp", live=True)
    assert stats.posted == 1

    # Log a metric snapshot, then earnings = views/1000 * rate.
    from trendengine.db.database import session_scope
    from trendengine.db.models import Draft, PostMetric
    with session_scope() as s:
        d = s.query(Draft).filter(Draft.campaign == "testcamp").one()
        s.add(PostMetric(draft_id=d.id, external_post_id="vid9", views=10000,
                         likes=100, comments=10, engagement_rate=0.011))

    rows = {e["campaign"]: e for e in campaign_earnings(config)}
    assert rows["testcamp"]["views"] == 10000
    assert rows["testcamp"]["estimated_payout"] == 20.0   # 10k views @ $2/1k
