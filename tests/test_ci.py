"""Serverless (CI) batch runner + its env overrides."""
import os

from trendengine.config import Config


def test_llm_provider_env_override(config, monkeypatch):
    from trendengine.llm import get_llm
    from trendengine.llm.groq_client import GroqClient
    config.raw["llm"]["provider"] = "ollama"       # config says ollama…
    monkeypatch.setenv("LLM_PROVIDER", "groq")     # …but env wins
    assert isinstance(get_llm(config), GroqClient)


def test_db_path_env_override(monkeypatch, tmp_path):
    target = tmp_path / "state" / "trendengine.sqlite3"
    monkeypatch.setenv("TRENDENGINE_DB", str(target))
    assert Config.load().db_path() == target


def test_run_ci_writes_summary_with_no_campaigns(config):
    """A run with nothing configured still produces a clean summary, no crash."""
    from pathlib import Path
    from trendengine.ci import run_ci
    from trendengine.config import PROJECT_ROOT

    summary = PROJECT_ROOT / "state" / "SUMMARY.md"
    existed = summary.exists()
    before = summary.read_text() if existed else None
    try:
        res = run_ci(config)
        assert res["campaigns"] == []              # none configured
        text = Path(res["summary"]).read_text()
        assert "run summary" in text
        assert "Earnings" in text and "What it's learned" in text
    finally:
        if before is not None:
            summary.write_text(before)
        elif summary.exists():
            summary.unlink()


def test_run_ci_runs_configured_campaign(config, monkeypatch):
    """With a campaign set, run_ci drives the clip runner and reflects it."""
    from pathlib import Path
    from trendengine.clipping.campaign import Campaign
    from trendengine.clipping.clipper import ClipResult, Moment
    from trendengine.config import PROJECT_ROOT

    config.raw["autopilot"]["clip_campaigns"] = ["c1"]
    config.raw["autopilot"]["mode"] = "shadow"
    camp = Campaign(id="c1", name="C1", authorized=True,
                    authorization_note="licensed", source_urls=["https://x"],
                    platforms=["youtube"], required_hashtags=["#c"],
                    payout_per_1k_views=1.0, clips_per_source=1)
    monkeypatch.setattr("trendengine.clipping.runner.get_campaign", lambda cid: camp)
    monkeypatch.setattr("trendengine.clipping.runner.get_llm", lambda cfg: object())
    clip_path = PROJECT_ROOT / "media_out" / "clips" / "c1.mp4"
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    clip_path.write_bytes(b"\x00")
    monkeypatch.setattr(
        "trendengine.clipping.clipper.ClipGenerator.clip_source",
        lambda self, campaign, url, llm: [ClipResult(
            path=clip_path, moment=Moment(1.0, 30.0, "hook"), caption="hook #c")])

    summary = PROJECT_ROOT / "state" / "SUMMARY.md"
    before = summary.read_text() if summary.exists() else None
    try:
        res = run_ci(config)
        assert any("c1" in r for r in res["campaigns"])
        assert "shadow=1" in " ".join(res["campaigns"])
        assert "c1" in Path(res["summary"]).read_text()
    finally:
        if before is not None:
            summary.write_text(before)
        elif summary.exists():
            summary.unlink()


# run_ci is imported at module scope inside tests to keep import side effects local
from trendengine.ci import run_ci  # noqa: E402
