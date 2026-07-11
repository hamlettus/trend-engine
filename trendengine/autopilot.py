"""Autopilot: the fully autonomous loop (no human approver).

Per cycle:
  discover -> dedup -> analyse -> for each top topic within today's canary budget:
    pick bandit arms -> compose draft -> AUTOMATED GATE -> (live) render + upload
                                                        -> (shadow) record only

Automated gates replace the human: a bad draft is rejected in code, not by you.
Safety: kill switch, canary daily cap + ramp, per-run budget, shadow mode.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from trendengine.analysis.aggregator import TrendAnalyzer
from trendengine.config import Config
from trendengine.db.database import session_scope
from trendengine.db.models import (STATUS_FAILED, STATUS_POSTED, STATUS_REJECTED,
                                   STATUS_SHADOW, CanaryState, Draft, PostHistory)
from trendengine.generation.drafter import Drafter
from trendengine.guardrails.gate import QualityGate
from trendengine.learning.bandit import ThompsonBandit
from trendengine.llm import get_llm
from trendengine.llm.base import LLMError
from trendengine.logging_setup import get_logger
from trendengine.pipeline import _dedup
from trendengine.publishers import get_publisher
from trendengine.sources import build_sources
from trendengine.utils.killswitch import KillSwitch

log = get_logger(__name__)


@dataclass
class AutopilotStats:
    attempted: int = 0
    gated_out: int = 0
    posted: int = 0
    shadowed: int = 0
    failed: int = 0
    drafts: list[int] = field(default_factory=list)
    halted: bool = False
    note: str = ""

    def summary(self) -> str:
        if self.halted:
            return f"HALTED: {self.note}"
        return (f"attempted={self.attempted} posted={self.posted} "
                f"shadow={self.shadowed} gated_out={self.gated_out} "
                f"failed={self.failed}")


def _start_of_utc_day() -> dt.datetime:
    now = dt.datetime.now(dt.timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def bucket_hour(hour: int, slots: list[int]) -> int:
    """Snap an hour to the nearest configured post-hour slot (for attribution)."""
    if not slots:
        return hour
    return min(slots, key=lambda s: abs(s - hour))


def _canary_budget(config: Config) -> int:
    """Posts still allowed today under the canary ramp."""
    cfg = config.raw.get("autopilot", {}).get("canary", {})
    start = int(cfg.get("start_per_day", 1))
    with session_scope() as s:
        state = s.get(CanaryState, 1)
        if state is None:
            state = CanaryState(id=1, current_per_day=start)
            s.add(state)
            s.flush()
        allowed = int(state.current_per_day)
        used = (s.query(Draft)
                .filter(Draft.auto.is_(True),
                        Draft.status.in_([STATUS_POSTED, STATUS_SHADOW]),
                        Draft.created_at >= _start_of_utc_day())
                .count())
    return max(0, allowed - used)


def _maybe_ramp_canary(config: Config) -> None:
    """Grow daily volume by one step per day while engagement stays healthy."""
    cfg = config.raw.get("autopilot", {}).get("canary", {})
    max_per_day = int(cfg.get("max_per_day", 4))
    step = int(cfg.get("ramp_step", 1))
    healthy = float(cfg.get("healthy_engagement_rate", 0.02))
    today = _start_of_utc_day()

    from trendengine.db.models import PostMetric
    import numpy as np
    with session_scope() as s:
        state = s.get(CanaryState, 1)
        if state is None:
            return
        if state.last_ramped_on and state.last_ramped_on >= today:
            return  # already considered today
        rates = [m.engagement_rate for m in s.query(PostMetric).all()
                 if m.engagement_rate is not None]
        # Only ramp once we have real, healthy engagement evidence.
        if rates and float(np.median(rates)) >= healthy and state.current_per_day < max_per_day:
            state.current_per_day = min(max_per_day, state.current_per_day + step)
            log.info("Canary ramped to %d posts/day.", state.current_per_day)
        state.last_ramped_on = today


def run_autopilot(config: Config, force_live: bool | None = None) -> AutopilotStats:
    stats = AutopilotStats()
    ap = config.raw.get("autopilot", {})
    if not ap.get("enabled", False):
        stats.note = "autopilot.enabled is false"
        return stats

    if KillSwitch(config).is_active():
        stats.halted = True
        stats.note = "kill switch active"
        return stats

    mode = ap.get("mode", "shadow")
    live = (mode == "live") if force_live is None else force_live
    budget = _canary_budget(config)
    if budget <= 0:
        stats.note = "canary budget for today is exhausted"
        log.info(stats.note)
        return stats

    keywords = config.keywords
    items = []
    for source in build_sources(config):
        items.extend(source.collect(keywords))
    fresh, _ = _dedup(items)
    if not fresh:
        stats.note = "no fresh items"
        return stats

    topics = TrendAnalyzer(config).analyze(fresh)
    if not topics:
        stats.note = "no topics"
        return stats

    try:
        llm = get_llm(config)
    except Exception as exc:  # noqa: BLE001
        stats.note = f"LLM unavailable: {exc}"
        log.error(stats.note)
        return stats

    drafter = Drafter(config, llm)
    bandit = ThompsonBandit(config)
    gate = QualityGate(config, llm)
    publisher = get_publisher(config, ap.get("publisher", "youtube"))
    slots = config.raw.get("learning", {}).get("bandit_arms", {}).get("post_hour", [])
    platform = "youtube" if ap.get("publisher") == "youtube" else \
        config.generation.get("platform", "instagram")

    for topic in topics:
        if stats.posted + stats.shadowed >= budget:
            break
        stats.attempted += 1

        arms = bandit.select()
        arms["post_hour"] = bucket_hour(dt.datetime.now().hour, slots)

        try:
            composed = drafter.compose(topic, arms)
        except LLMError as exc:
            log.error("compose failed for '%s': %s", topic.topic, exc)
            continue
        if not composed.caption:
            continue

        result = gate.check(topic.score, composed.caption,
                            " ".join(composed.hashtags), topic.topic)
        draft_id = _persist(config, topic, composed, arms, result, platform,
                            llm, gated_out=not result.passed)
        if not result.passed:
            stats.gated_out += 1
            log.info("Gated out '%s': %s", topic.topic, result.notes)
            continue

        stats.drafts.append(draft_id)
        if not live:
            _mark(draft_id, STATUS_SHADOW)
            stats.shadowed += 1
            log.info("[shadow] would post draft #%d ('%s')", draft_id, topic.topic)
            continue

        # LIVE: render + upload.
        try:
            outcome = _render_and_upload(config, publisher, draft_id)
            stats.posted += 1
            log.info("[live] posted draft #%d -> %s", draft_id, outcome)
        except Exception as exc:  # noqa: BLE001
            _mark(draft_id, STATUS_FAILED, note=str(exc)[:500])
            stats.failed += 1
            log.error("Publish failed for draft #%d: %s", draft_id, exc)

    _maybe_ramp_canary(config)
    log.info("Autopilot cycle: %s", stats.summary())
    return stats


# -- persistence helpers ---------------------------------------------------

def _persist(config, topic, composed, arms, gate_result, platform, llm,
             gated_out: bool) -> int:
    with session_scope() as s:
        draft = Draft(
            topic=topic.topic, platform=platform, caption=composed.caption,
            hashtags=" ".join(composed.hashtags), rationale=composed.rationale,
            source_summary=composed.source_summary, score=topic.score,
            features=composed.features, arms=arms, auto=True,
            gate_score=gate_result.score, gate_notes=gate_result.notes,
            status=STATUS_REJECTED if gated_out else "pending",
            llm_provider=llm.provider, llm_model=llm.model)
        s.add(draft)
        s.flush()
        return draft.id


def _mark(draft_id: int, status: str, note: str = "") -> None:
    with session_scope() as s:
        d = s.get(Draft, draft_id)
        if d:
            d.status = status
            if status in (STATUS_SHADOW, STATUS_POSTED):
                d.posted_at = dt.datetime.now(dt.timezone.utc)
            if note:
                d.gate_notes = (d.gate_notes + " | " + note).strip(" |")


def _render_and_upload(config: Config, publisher, draft_id: int) -> str:
    from trendengine.media import ShortGenerator

    with session_scope() as s:
        d = s.get(Draft, draft_id)
        caption, topic = d.caption, d.topic

    video = ShortGenerator(config).render(caption, topic, draft_id)
    with session_scope() as s:
        d = s.get(Draft, draft_id)
        d.video_path = str(video)

    with session_scope() as s:
        d = s.get(Draft, draft_id)
        res = publisher.publish(d)
        if not res.ok:
            raise RuntimeError(res.message)
        d.status = STATUS_POSTED
        d.posted_at = dt.datetime.now(dt.timezone.utc)
        d.external_post_id = res.external_post_id
        s.add(PostHistory(draft_id=d.id, platform=d.platform, caption=d.caption,
                          external_post_id=res.external_post_id))
        return res.message
