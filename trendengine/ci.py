"""Batch entry point for the serverless (GitHub Actions) path.

There's no live dashboard on the free serverless path, so this runs the
configured clip campaigns, ingests performance, and writes a phone-viewable
Markdown summary to state/SUMMARY.md (which the workflow commits back to the
repo — you read it in the GitHub mobile app). Clips are uploaded as workflow
artifacts.
"""
from __future__ import annotations

import datetime as dt

from trendengine.clipping.runner import campaign_earnings, run_clip_campaign
from trendengine.config import PROJECT_ROOT, Config
from trendengine.db.database import session_scope
from trendengine.db.models import Draft
from trendengine.learning import PerformanceIngestor, ThompsonBandit, WeightLearner
from trendengine.logging_setup import get_logger

log = get_logger(__name__)


def run_ci(config: Config) -> dict:
    ap = config.raw.get("autopilot", {})
    ids = ap.get("clip_campaigns", []) or []
    live = ap.get("mode") == "live"

    results: list[str] = []
    for cid in ids:
        try:
            results.append(run_clip_campaign(config, cid, live=live).summary())
        except Exception as exc:  # noqa: BLE001 - one campaign shouldn't kill the run
            results.append(f"campaign={cid} ERROR: {exc}")
            log.error("CI campaign %s failed: %s", cid, exc)

    ingest = {}
    if config.raw.get("learning", {}).get("enabled", True):
        try:
            ingest = PerformanceIngestor(config).run()
        except Exception as exc:  # noqa: BLE001
            log.error("CI ingest failed: %s", exc)

    summary = _write_summary(config, results, ingest, live)
    log.info("CI run complete: %s", results or "no campaigns")
    return {"campaigns": results, "ingest": ingest, "summary": str(summary)}


def _write_summary(config: Config, results: list[str], ingest: dict, live: bool):
    state_dir = PROJECT_ROOT / "state"
    state_dir.mkdir(exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    out = [f"# trend-engine — run summary",
           f"\n_Last run: **{now}** · mode: **{'LIVE' if live else 'shadow (not posting)'}**_\n",
           "## This run"]
    out += [f"- {r}" for r in results] or ["- No campaigns configured "
            "(set `autopilot.clip_campaigns` in config.yaml)."]
    out.append(f"\n_Performance ingest: {ingest or '(none)'}_\n")

    with session_scope() as s:
        clips = (s.query(Draft).filter(Draft.campaign.isnot(None))
                 .order_by(Draft.created_at.desc()).limit(10).all())
        clip_rows = [(c.campaign, c.status, (c.topic or "")[:48],
                      c.external_post_id or "") for c in clips]
        weights, samples = WeightLearner.load(s)

    out.append("## Recent clips")
    if clip_rows:
        out += ["| campaign | status | moment | posted id |", "|---|---|---|---|"]
        out += [f"| {c} | {st} | {t} | {pid} |" for c, st, t, pid in clip_rows]
    else:
        out.append("_None yet — add an authorized campaign to `campaigns.yaml`._")

    out.append("\n## Earnings (estimated)")
    earn = campaign_earnings(config)
    if earn:
        out += ["| campaign | posts | views | est $ |", "|---|---|---|---|"]
        total = 0.0
        for e in earn:
            total += e["estimated_payout"]
            out.append(f"| {e['campaign']} | {e['posts']} | {e['views']:,} | "
                       f"${e['estimated_payout']:.2f} |")
        out.append(f"| **total** | | | **${total:.2f}** |")
    else:
        out.append("_No campaigns._")

    out.append("\n## What it's learned")
    out.append(f"- Learned scoring weights ({samples} posts): {weights or '(none yet)'}")
    for a in sorted(ThompsonBandit(config).snapshot(),
                    key=lambda x: x["win_rate"], reverse=True)[:5]:
        out.append(f"- best `{a['dimension']}` → **{a['value']}** "
                   f"(win {a['win_rate']}, {a['pulls']} uses)")

    path = state_dir / "SUMMARY.md"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path
