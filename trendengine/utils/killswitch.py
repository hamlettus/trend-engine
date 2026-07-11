"""Global kill switch — a hard stop for the discovery/generation loop.

Two independent brakes, either one halts the loop:
  * ``safety.global_enabled: false`` in config.yaml
  * the presence of the kill-switch file (default ``.killswitch``)

The file-based switch is deliberately dead simple so you can trip it from
anywhere — the dashboard button, `touch .killswitch`, or a cron job.
"""
from __future__ import annotations

from pathlib import Path

from trendengine.config import PROJECT_ROOT, Config
from trendengine.logging_setup import get_logger

log = get_logger(__name__)


class KillSwitch:
    def __init__(self, config: Config) -> None:
        self.config = config
        fname = config.safety.get("kill_switch_file", ".killswitch")
        self.path = PROJECT_ROOT / fname

    def is_active(self) -> bool:
        if not self.config.safety.get("global_enabled", True):
            log.warning("Kill switch: safety.global_enabled is false in config.")
            return True
        if self.path.exists():
            log.warning("Kill switch ACTIVE: %s present.", self.path.name)
            return True
        return False

    def engage(self) -> None:
        self.path.write_text("engaged\n", encoding="utf-8")
        log.warning("Kill switch ENGAGED (%s created).", self.path.name)

    def release(self) -> None:
        if self.path.exists():
            self.path.unlink()
        log.info("Kill switch released.")
