"""APScheduler wiring: run the pipeline on a jittered interval with a kill switch."""
from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from trendengine.config import Config
from trendengine.logging_setup import get_logger
from trendengine.pipeline import run_once
from trendengine.utils.killswitch import KillSwitch

log = get_logger(__name__)


def _job(config: Config) -> None:
    kill = KillSwitch(config)
    if kill.is_active():
        log.warning("Scheduled run skipped — kill switch active.")
        return
    try:
        stats = run_once(config)
        log.info("Scheduled run: %s", stats.summary())
    except Exception as exc:  # noqa: BLE001 - keep the scheduler alive
        log.exception("Scheduled run crashed: %s", exc)


def build_scheduler(config: Config) -> BackgroundScheduler:
    sched = config.schedule
    interval_min = int(sched.get("interval_minutes", 180))
    jitter = int(sched.get("jitter_seconds", 900))
    run_on_start = bool(sched.get("run_on_start", True))

    scheduler = BackgroundScheduler(timezone="UTC")
    trigger = IntervalTrigger(minutes=interval_min, jitter=jitter)
    scheduler.add_job(
        _job, trigger=trigger, args=[config], id="discovery_loop",
        max_instances=1, coalesce=True, replace_existing=True,
    )
    log.info("Scheduler: every %d min (±%ds jitter). Kill switch: %s",
             interval_min, jitter,
             config.safety.get("kill_switch_file", ".killswitch"))

    if run_on_start:
        # Fire one cycle shortly after boot without blocking startup.
        scheduler.add_job(_job, args=[config], id="startup_run",
                         max_instances=1, replace_existing=True)
    return scheduler


def _autopilot_job(config: Config) -> None:
    if KillSwitch(config).is_active():
        log.warning("Autopilot run skipped — kill switch active.")
        return
    try:
        from trendengine.autopilot import run_autopilot
        stats = run_autopilot(config)
        log.info("Autopilot: %s", stats.summary())
    except Exception as exc:  # noqa: BLE001
        log.exception("Autopilot run crashed: %s", exc)


def _ingest_job(config: Config) -> None:
    """Pull settled performance and feed the learners (safe no-op in shadow)."""
    try:
        from trendengine.learning import PerformanceIngestor
        res = PerformanceIngestor(config).run()
        log.info("Ingest: %s", res)
    except Exception as exc:  # noqa: BLE001
        log.exception("Ingest run crashed: %s", exc)


def _clip_job(config: Config) -> None:
    """Run configured clipping campaigns on schedule (autopilot.clip_campaigns)."""
    if KillSwitch(config).is_active():
        return
    ap = config.raw.get("autopilot", {})
    ids = ap.get("clip_campaigns", []) or []
    if not ids:
        return
    live = ap.get("mode") == "live"
    from trendengine.clipping.runner import run_clip_campaign
    for cid in ids:
        try:
            stats = run_clip_campaign(config, cid, live=live)
            log.info("Clip campaign: %s", stats.summary())
        except Exception as exc:  # noqa: BLE001
            log.error("Clip campaign '%s' failed: %s", cid, exc)


def build_autopilot_scheduler(config: Config) -> BackgroundScheduler:
    """Scheduler for fully autonomous mode: autopilot loop + learning ingest."""
    ap = config.raw.get("autopilot", {})
    interval_min = int(ap.get("interval_minutes", 240))
    jitter = int(ap.get("jitter_seconds", 1200))

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        _autopilot_job, trigger=IntervalTrigger(minutes=interval_min, jitter=jitter),
        args=[config], id="autopilot_loop", max_instances=1, coalesce=True,
        replace_existing=True)
    # Pull performance hourly so the learners see engagement settle.
    scheduler.add_job(
        _ingest_job, trigger=IntervalTrigger(minutes=60), args=[config],
        id="ingest_loop", max_instances=1, coalesce=True, replace_existing=True)

    # If clipping campaigns are configured, clip them on the autopilot cadence.
    if ap.get("clip_campaigns"):
        scheduler.add_job(
            _clip_job, trigger=IntervalTrigger(minutes=interval_min, jitter=jitter),
            args=[config], id="clip_loop", max_instances=1, coalesce=True,
            replace_existing=True)
        log.info("Clip campaigns scheduled: %s", ap.get("clip_campaigns"))

    log.info("Autopilot scheduler: cycle every %d min (±%ds), mode=%s. Ingest hourly.",
             interval_min, jitter, ap.get("mode", "shadow"))
    if config.schedule.get("run_on_start", True):
        scheduler.add_job(_autopilot_job, args=[config], id="autopilot_startup",
                         max_instances=1, replace_existing=True)
    return scheduler
