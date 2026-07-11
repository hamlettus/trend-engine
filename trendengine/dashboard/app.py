"""Local FastAPI approval dashboard.

Review, edit, approve, reject, prepare, and (manually) mark-posted drafts.
Also log performance feedback and trip the kill switch. Localhost only.
Nothing is ever marked posted without your explicit click.
"""
from __future__ import annotations

import base64
import datetime as dt
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from trendengine.config import Config
from trendengine.db.database import init_db, session_scope
from trendengine.db.models import (STATUS_APPROVED, STATUS_PENDING,
                                   STATUS_POSTED, STATUS_REJECTED, Draft,
                                   PerformanceFeedback, PostHistory)
from trendengine.logging_setup import get_logger, setup_logging
from trendengine.publishers import get_publisher
from trendengine.utils.killswitch import KillSwitch

log = get_logger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Password-protect the whole dashboard when DASHBOARD_PASSWORD is set.

    Off by default (localhost dev); the deploy script sets a password so the
    dashboard is safe to reach over the network from your phone.
    """

    def __init__(self, app, user: str, password: str) -> None:
        super().__init__(app)
        self.user = user
        self.password = password

    async def dispatch(self, request, call_next):
        if not self.password:
            return await call_next(request)
        header = request.headers.get("Authorization", "")
        if header.startswith("Basic "):
            try:
                user, _, pw = base64.b64decode(header[6:]).decode().partition(":")
                if (secrets.compare_digest(user, self.user)
                        and secrets.compare_digest(pw, self.password)):
                    return await call_next(request)
            except Exception:  # noqa: BLE001 - malformed header => challenge
                pass
        return Response("Authentication required", status_code=401,
                        headers={"WWW-Authenticate": 'Basic realm="trend-engine"'})


def create_app(config: Config | None = None) -> FastAPI:
    setup_logging()
    config = config or Config.load()
    init_db(config)

    app = FastAPI(title="trend-engine dashboard")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    kill = KillSwitch(config)

    # Network-facing protection (enabled when DASHBOARD_PASSWORD is set).
    dash_password = os.environ.get("DASHBOARD_PASSWORD", "")
    if dash_password:
        app.add_middleware(BasicAuthMiddleware,
                          user=os.environ.get("DASHBOARD_USER", "admin"),
                          password=dash_password)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, status: str = STATUS_PENDING):
        with session_scope() as session:
            drafts = (session.query(Draft)
                     .filter(Draft.status == status)
                     .order_by(Draft.score.desc(), Draft.created_at.desc())
                     .all())
            counts = {s: session.query(Draft).filter(Draft.status == s).count()
                      for s in (STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED,
                                STATUS_POSTED)}
            drafts_data = [_draft_dict(d) for d in drafts]
        return templates.TemplateResponse(request, "index.html", {
            "drafts": drafts_data, "status": status,
            "counts": counts, "kill_active": kill.is_active(),
            "niche": config.niche.get("name", ""),
        })

    @app.get("/draft/{draft_id}", response_class=HTMLResponse)
    def draft_detail(request: Request, draft_id: int):
        with session_scope() as session:
            d = session.get(Draft, draft_id)
            if d is None:
                return RedirectResponse("/", status_code=303)
            data = _draft_dict(d)
        return templates.TemplateResponse(request, "draft.html", {
            "d": data, "kill_active": kill.is_active(),
            "niche": config.niche.get("name", "")})

    @app.post("/draft/{draft_id}/edit")
    def edit_draft(draft_id: int, caption: str = Form(...),
                   hashtags: str = Form(""), media_path: str = Form("")):
        with session_scope() as session:
            d = session.get(Draft, draft_id)
            if d:
                d.caption = caption
                d.hashtags = hashtags
                d.media_path = media_path or None
        return RedirectResponse(f"/draft/{draft_id}", status_code=303)

    @app.post("/draft/{draft_id}/approve")
    def approve(draft_id: int):
        _set_status(draft_id, STATUS_APPROVED)
        return RedirectResponse(f"/draft/{draft_id}", status_code=303)

    @app.post("/draft/{draft_id}/reject")
    def reject(draft_id: int):
        _set_status(draft_id, STATUS_REJECTED)
        return RedirectResponse("/", status_code=303)

    @app.post("/draft/{draft_id}/prepare")
    def prepare(request: Request, draft_id: int):
        """Run the assisted publisher: export file + clipboard + (opt) browser."""
        message = ""
        with session_scope() as session:
            d = session.get(Draft, draft_id)
            if d is None:
                return RedirectResponse("/", status_code=303)
            if d.status not in (STATUS_APPROVED, STATUS_POSTED):
                message = "Approve the draft before preparing it."
            else:
                publisher = get_publisher(config)
                result = publisher.prepare(d)
                d.export_path = result.export_path
                message = result.message
        return RedirectResponse(
            f"/draft/{draft_id}?msg={_url(message)}", status_code=303)

    @app.post("/draft/{draft_id}/mark-posted")
    def mark_posted(draft_id: int, external_post_id: str = Form("")):
        """Explicit human action — the ONLY way a draft becomes 'posted'."""
        with session_scope() as session:
            d = session.get(Draft, draft_id)
            if d and d.status == STATUS_APPROVED:
                d.status = STATUS_POSTED
                d.posted_at = dt.datetime.now(dt.timezone.utc)
                session.add(PostHistory(
                    draft_id=d.id, platform=d.platform, caption=d.caption,
                    external_post_id=external_post_id or None))
        return RedirectResponse(f"/draft/{draft_id}", status_code=303)

    @app.get("/feedback", response_class=HTMLResponse)
    def feedback_form(request: Request):
        with session_scope() as session:
            posted = (session.query(Draft)
                     .filter(Draft.status == STATUS_POSTED)
                     .order_by(Draft.posted_at.desc()).all())
            posted_data = [_draft_dict(d) for d in posted]
            recent = (session.query(PerformanceFeedback)
                     .order_by(PerformanceFeedback.logged_at.desc()).limit(20).all())
            recent_data = [{
                "topic": f.topic, "platform": f.platform, "er": f.engagement_rate,
                "likes": f.likes, "reach": f.reach,
                "logged_at": f.logged_at,
            } for f in recent]
        return templates.TemplateResponse(request, "feedback.html", {
            "posted": posted_data, "recent": recent_data,
            "kill_active": kill.is_active(),
            "niche": config.niche.get("name", "")})

    @app.post("/feedback")
    def log_feedback(draft_id: int = Form(...), likes: int = Form(0),
                     comments: int = Form(0), shares: int = Form(0),
                     saves: int = Form(0), reach: int = Form(0)):
        with session_scope() as session:
            d = session.get(Draft, draft_id)
            topic = d.topic if d else ""
            platform = d.platform if d else ""
            fb = PerformanceFeedback(
                draft_id=draft_id if d else None, topic=topic, platform=platform,
                likes=likes, comments=comments, shares=shares, saves=saves, reach=reach)
            fb.engagement_rate = fb.compute_engagement_rate()
            session.add(fb)
        return RedirectResponse("/feedback", status_code=303)

    @app.get("/insights", response_class=HTMLResponse)
    def insights(request: Request):
        data = _gather_insights(config)
        data.update(request=request, kill_active=kill.is_active(),
                    niche=config.niche.get("name", ""))
        return templates.TemplateResponse(request, "insights.html", data)

    @app.get("/campaigns", response_class=HTMLResponse)
    def campaigns_page(request: Request):
        from trendengine.clipping.campaign import load_campaigns
        camps = load_campaigns()
        rows = [{
            "id": c.id, "name": c.name, "authorized": c.is_authorized(),
            "note": c.authorization_note, "platforms": ", ".join(c.platforms),
            "sources": len(c.source_urls), "rate": c.payout_per_1k_views,
            "clips": c.clips_per_source,
        } for c in camps.values()]
        return templates.TemplateResponse(request, "campaigns.html", {
            "campaigns": rows, "kill_active": kill.is_active(),
            "niche": config.niche.get("name", ""),
            "mode": config.raw.get("autopilot", {}).get("mode", "shadow")})

    @app.post("/campaigns/{campaign_id}/run")
    def run_campaign(campaign_id: str, live: str = Form("")):
        """Kick a clip run in the background — the phone-friendly trigger.

        Refuses unauthorized campaigns (the runner raises); shadow unless the
        live box is checked AND autopilot mode is live."""
        import threading
        go_live = bool(live) and config.raw.get("autopilot", {}).get("mode") == "live"

        def _job():
            from trendengine.clipping.runner import run_clip_campaign
            try:
                run_clip_campaign(config, campaign_id, live=go_live)
            except Exception as exc:  # noqa: BLE001
                log.error("Campaign run '%s' failed: %s", campaign_id, exc)

        threading.Thread(target=_job, daemon=True, name=f"clip-{campaign_id}").start()
        msg = (f"Started '{campaign_id}' ({'LIVE' if go_live else 'shadow'}). "
               "Clips will appear in the queue shortly.")
        return RedirectResponse(f"/campaigns?msg={_url(msg)}", status_code=303)

    @app.post("/killswitch/toggle")
    def toggle_kill():
        if kill.path.exists():
            kill.release()
        else:
            kill.engage()
        return RedirectResponse("/", status_code=303)

    return app


# -- helpers ---------------------------------------------------------------

def _draft_dict(d: Draft) -> dict:
    return {
        "id": d.id, "topic": d.topic, "platform": d.platform,
        "caption": d.caption, "hashtags": d.hashtags, "media_path": d.media_path,
        "rationale": d.rationale, "source_summary": d.source_summary,
        "status": d.status, "score": d.score,
        "llm": f"{d.llm_provider}:{d.llm_model}",
        "export_path": d.export_path,
        "created_at": d.created_at, "posted_at": d.posted_at,
    }


def _set_status(draft_id: int, status: str) -> None:
    with session_scope() as session:
        d = session.get(Draft, draft_id)
        if d:
            d.status = status


def _url(text: str) -> str:
    from urllib.parse import quote
    return quote(text or "")


def _gather_insights(config: Config) -> dict:
    """Collect everything the learning stack knows, shaped for the template.

    Bar widths (0-100%) are computed here so the template stays logic-free.
    """
    from trendengine.db.models import (BanditArm, CanaryState, PostMetric,
                                       ReferenceContent, SystemState, TitleSignal)
    from trendengine.learning import CorpusLearner, TitleModel, WeightLearner

    with session_scope() as s:
        weights, weight_samples = WeightLearner.load(s)
        canary = s.get(CanaryState, 1)
        n_ref = s.query(ReferenceContent).count()
        bootstrapped = s.get(SystemState, "bandit_bootstrapped") is not None
        n_posted = s.query(Draft).filter(Draft.status == STATUS_POSTED).count()
        n_shadow = s.query(Draft).filter(Draft.status == "shadow").count()
        n_metrics = s.query(PostMetric).count()

        # Bandit arms grouped by dimension, with a win-rate bar.
        arms_by_dim: dict[str, list[dict]] = {}
        for a in s.query(BanditArm).order_by(BanditArm.dimension, BanditArm.value).all():
            win = a.alpha / (a.alpha + a.beta) if (a.alpha + a.beta) else 0.0
            arms_by_dim.setdefault(a.dimension, []).append({
                "value": a.value, "win": win, "win_pct": round(win * 100, 1),
                "pulls": a.pulls, "mean_reward": round(a.mean_reward, 4)})
        # Mark the current best arm per dimension.
        for arms in arms_by_dim.values():
            top = max(arms, key=lambda x: x["win"])
            top["best"] = True

        # Title-model coefficients -> signed bars (share of max magnitude).
        signals = [{"feature": t.feature, "coef": t.coef} for t in
                   s.query(TitleSignal).order_by(TitleSignal.feature).all()]
        max_abs = max((abs(x["coef"]) for x in signals), default=0.0) or 1.0
        for x in signals:
            x["pct"] = round(abs(x["coef"]) / max_abs * 100, 1)
            x["positive"] = x["coef"] >= 0

    # Learned vs config weights (blended is what actually ranks topics).
    cfg_w = config.analysis.get("weights", {})
    weight_rows = []
    for f in ("frequency", "growth", "engagement"):
        weight_rows.append({
            "feature": f,
            "config": round(float(cfg_w.get(f, 0.0)), 3),
            "learned": round(float(weights.get(f, 0.0)), 3) if weights else None,
            "config_pct": round(float(cfg_w.get(f, 0.0)) * 100, 1),
            "learned_pct": round(float(weights.get(f, 0.0)) * 100, 1) if weights else 0,
        })

    title_hints = TitleModel(config).hints()
    winner_styles = (CorpusLearner(config).report().get("style_strength", {})
                     if n_ref else {})

    try:
        from trendengine.clipping.runner import campaign_earnings
        earnings = campaign_earnings(config)
    except Exception:  # noqa: BLE001 - earnings are best-effort
        earnings = []
    earnings_total = round(sum(e["estimated_payout"] for e in earnings), 2)

    return {
        "earnings": earnings, "earnings_total": earnings_total,
        "bootstrapped": bootstrapped, "n_ref": n_ref,
        "n_posted": n_posted, "n_shadow": n_shadow, "n_metrics": n_metrics,
        "canary": canary.current_per_day if canary else None,
        "weight_samples": weight_samples,
        "arms_by_dim": arms_by_dim, "title_signals": signals,
        "title_hints": title_hints, "weight_rows": weight_rows,
        "winner_styles": winner_styles,
        "mode": config.raw.get("autopilot", {}).get("mode", "shadow"),
    }
