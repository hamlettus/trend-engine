#!/usr/bin/env python3
"""trend-engine command-line entry point.

Commands:
  init-db     Create the SQLite schema.
  once        Run one discovery -> draft cycle and exit (great for testing).
  dashboard   Start only the approval dashboard.
  run         Start the scheduler AND the dashboard together (normal use).
  doctor      Check config, Ollama, and which source credentials are present.

Examples:
  python run.py init-db
  python run.py once
  python run.py run
"""
from __future__ import annotations

import argparse
import sys
import threading

import uvicorn

from trendengine.config import Config
from trendengine.db.database import init_db
from trendengine.logging_setup import get_logger, setup_logging

log = get_logger("trendengine.cli")


def _start_dashboard(config: Config, block: bool = True) -> threading.Thread | None:
    from trendengine.dashboard.app import create_app

    host = config.dashboard.get("host", "127.0.0.1")
    port = int(config.dashboard.get("port", 8765))
    app = create_app(config)

    def _serve():
        uvicorn.run(app, host=host, port=port, log_level="warning")

    log.info("Dashboard → http://%s:%d", host, port)
    if block:
        _serve()
        return None
    thread = threading.Thread(target=_serve, daemon=True, name="dashboard")
    thread.start()
    return thread


def cmd_init_db(config: Config) -> None:
    init_db(config)
    print("✓ Database initialised.")


def cmd_once(config: Config) -> None:
    from trendengine.pipeline import run_once
    init_db(config)
    stats = run_once(config)
    print(f"✓ Run finished: {stats.summary()}")
    if stats.drafts:
        print(f"  New draft IDs: {stats.drafts}")
        print(f"  Review them at http://{config.dashboard.get('host','127.0.0.1')}:"
              f"{config.dashboard.get('port',8765)}")
    elif stats.note:
        print(f"  Note: {stats.note}")


def cmd_dashboard(config: Config) -> None:
    init_db(config)
    _start_dashboard(config, block=True)


def cmd_autopilot(config: Config) -> None:
    """One fully-autonomous cycle (discover -> gate -> render/post). For testing."""
    from trendengine.autopilot import run_autopilot
    init_db(config)
    mode = config.raw.get("autopilot", {}).get("mode", "shadow")
    print(f"Autopilot mode: {mode.upper()}"
          f"{'  (nothing will be uploaded)' if mode != 'live' else ''}")
    stats = run_autopilot(config)
    print(f"✓ {stats.summary()}")
    if stats.note:
        print(f"  Note: {stats.note}")


def cmd_autopilot_run(config: Config) -> None:
    """Autonomous scheduler (autopilot loop + performance ingest) + dashboard."""
    from trendengine.scheduler import build_autopilot_scheduler
    init_db(config)
    scheduler = build_autopilot_scheduler(config)
    scheduler.start()
    log.info("Autopilot running. Ctrl+C to stop. Kill switch: touch .killswitch")
    try:
        _start_dashboard(config, block=True)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        scheduler.shutdown(wait=False)


def cmd_youtube_auth(config: Config) -> None:
    from trendengine.publishers import get_publisher
    pub = get_publisher(config, "youtube")
    pub.authorize()  # type: ignore[attr-defined]
    print("✓ YouTube authorised. Token cached.")


def cmd_bootstrap(config: Config) -> None:
    """Warm-start the learners from public winners already out there.

    Run this ONCE before going live so the bandit starts biased toward what
    performs in your niche instead of a blank slate."""
    from trendengine.learning import CorpusLearner
    init_db(config)
    cl = CorpusLearner(config)
    n = cl.collect_reference()
    print(f"Collected {n} new reference items "
          f"(needs a YouTube key and/or Reddit creds for real data).")
    res = cl.bootstrap_bandit(force=getattr(config, "cli_force", False))
    print(f"✓ {res}")
    rep = cl.report()
    if rep.get("reference_items"):
        print(f"  Winner styles (mean performance percentile): "
              f"{rep.get('style_strength')}")
    # Fit the title virality model from the corpus (+ any own posts).
    from trendengine.learning import TitleModel
    tm = TitleModel(config)
    fitted = tm.fit()
    if fitted:
        print(f"  Title model coefficients: {fitted}")
        hints = tm.hints()
        if hints:
            print("  Title hints now steering generation:")
            for h in hints:
                print(f"    • {h}")
    else:
        print("  Title model: not enough corpus rows yet to fit "
              "(see learning.min_samples_to_learn).")


def cmd_ingest(config: Config) -> None:
    from trendengine.learning import PerformanceIngestor
    init_db(config)
    print(f"✓ Ingest: {PerformanceIngestor(config).run()}")


def cmd_learn(config: Config) -> None:
    from trendengine.learning import WeightLearner
    init_db(config)
    result = WeightLearner(config).learn()
    print(f"✓ Learned weights: {result}" if result
          else "Not enough settled posts yet to learn (see learning.min_samples_to_learn).")


def cmd_insights(config: Config) -> None:
    """Show what the engine has learned so far."""
    from trendengine.learning import ThompsonBandit, WeightLearner
    from trendengine.db.database import session_scope
    from trendengine.db.models import CanaryState
    from trendengine.db.models import ReferenceContent, SystemState
    from trendengine.learning import CorpusLearner
    init_db(config)
    with session_scope() as s:
        weights, samples = WeightLearner.load(s)
        canary = s.get(CanaryState, 1)
        cur = canary.current_per_day if canary else "?"
        n_ref = s.query(ReferenceContent).count()
        booted = s.get(SystemState, "bandit_bootstrapped") is not None
    print(f"Canary: {cur} posts/day")
    print(f"Bootstrap: {'done' if booted else 'NOT run'} "
          f"({n_ref} public reference items)")
    if n_ref:
        print(f"  Winner styles: {CorpusLearner(config).report().get('style_strength')}")
    print(f"Learned weights (from {samples} own posts): {weights or '(none yet)'}")

    from trendengine.learning import TitleModel
    tm = TitleModel(config)
    report = tm.report()
    if report:
        print(f"Title model coefficients: {report}")
        for h in tm.hints():
            print(f"  • {h}")
    print("\nBandit arms (win_rate = Beta mean; pulls = times used):")
    for a in ThompsonBandit(config).snapshot():
        print(f"  {a['dimension']:14} {a['value']:12} "
              f"win_rate={a['win_rate']:.2f} pulls={a['pulls']} "
              f"mean_reward={a['mean_reward']:.4f}")


def cmd_run(config: Config) -> None:
    from trendengine.scheduler import build_scheduler
    init_db(config)
    scheduler = build_scheduler(config)
    scheduler.start()
    log.info("Scheduler started. Ctrl+C to stop.")
    try:
        _start_dashboard(config, block=True)  # blocks; scheduler runs in background
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        scheduler.shutdown(wait=False)
        log.info("Stopped.")


def cmd_doctor(config: Config) -> None:
    print(f"niche: {config.niche.get('name','(unset)')}")
    print(f"keywords: {', '.join(config.keywords) or '(none)'}")
    print("\nsources:")
    for name, s in config.sources.items():
        state = "enabled" if s.get("enabled") else "disabled"
        print(f"  - {name}: {state} (min_interval={s.get('min_interval_seconds','?')}s)")

    print("\ncredentials in .env:")
    for key in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "YOUTUBE_API_KEY",
                "ANTHROPIC_API_KEY", "META_ACCESS_TOKEN", "TIKTOK_ACCESS_TOKEN"):
        print(f"  - {key}: {'set' if Config.env(key) else 'MISSING (TODO)'}")

    print(f"\nLLM provider: {config.llm.get('provider')}")
    try:
        from trendengine.llm import get_llm
        ok, detail = get_llm(config).health_check()
        print(f"  {'✓' if ok else '✗'} {detail}")
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ {exc}")

    ap = config.raw.get("autopilot", {})
    print(f"\nautopilot: enabled={ap.get('enabled')} mode={ap.get('mode')} "
          f"publisher={ap.get('publisher')}")
    import shutil as _sh
    print(f"  ffmpeg: {'found' if _sh.which('ffmpeg') else 'MISSING (needed to render Shorts)'}")
    print(f"  TTS '{config.raw.get('media', {}).get('tts')}': "
          f"{'found' if _sh.which(config.raw.get('media', {}).get('tts', 'say')) else 'not on PATH (silent video)'}")
    try:
        from trendengine.publishers import get_publisher
        ok, detail = get_publisher(config, "youtube").health_check()  # type: ignore
        print(f"  youtube: {'✓' if ok else '✗'} {detail}")
    except Exception as exc:  # noqa: BLE001
        print(f"  youtube: ✗ {exc}")

    from trendengine.utils.killswitch import KillSwitch
    print(f"\nkill switch: {'ACTIVE' if KillSwitch(config).is_active() else 'clear'}")


COMMANDS = {
    "init-db": cmd_init_db,
    "once": cmd_once,
    "dashboard": cmd_dashboard,
    "run": cmd_run,
    "autopilot": cmd_autopilot,
    "autopilot-run": cmd_autopilot_run,
    "youtube-auth": cmd_youtube_auth,
    "bootstrap": cmd_bootstrap,
    "ingest": cmd_ingest,
    "learn": cmd_learn,
    "insights": cmd_insights,
    "doctor": cmd_doctor,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="trend-engine")
    parser.add_argument("command", choices=COMMANDS.keys())
    parser.add_argument("--config", default=None, help="path to config.yaml")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--force", action="store_true",
                        help="re-run a one-off action (e.g. bootstrap) even if already done")
    args = parser.parse_args(argv)

    setup_logging(args.log_level)
    config = Config.load(config_path=args.config)
    config.cli_force = args.force  # read by cmd_bootstrap
    COMMANDS[args.command](config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
