"""The core loop: discover -> dedup -> analyse -> draft -> queue."""
from __future__ import annotations

from dataclasses import dataclass, field

from trendengine.analysis.aggregator import TrendAnalyzer
from trendengine.config import Config
from trendengine.db.database import session_scope
from trendengine.db.models import SeenContent
from trendengine.generation.drafter import Drafter
from trendengine.llm import get_llm
from trendengine.logging_setup import get_logger
from trendengine.sources import build_sources
from trendengine.sources.base import TrendItem
from trendengine.utils.killswitch import KillSwitch

log = get_logger(__name__)


@dataclass
class RunStats:
    fetched: int = 0
    new: int = 0
    duplicates: int = 0
    topics: int = 0
    drafts: list[int] = field(default_factory=list)
    halted: bool = False
    note: str = ""

    def summary(self) -> str:
        if self.halted:
            return f"HALTED: {self.note}"
        return (f"fetched={self.fetched} new={self.new} dup={self.duplicates} "
                f"topics={self.topics} drafts={len(self.drafts)}")


def _dedup(items: list[TrendItem]) -> tuple[list[TrendItem], int]:
    """Filter out content we've already seen; persist the new hashes."""
    fresh: list[TrendItem] = []
    duplicates = 0
    with session_scope() as session:
        for it in items:
            h = it.content_hash
            exists = session.query(SeenContent.id).filter_by(content_hash=h).first()
            if exists:
                duplicates += 1
                continue
            session.add(SeenContent(
                content_hash=h, source=it.source, external_id=str(it.external_id),
                title=it.title[:1000], url=it.url, keyword=it.keyword, score=it.score,
            ))
            fresh.append(it)
    return fresh, duplicates


def run_once(config: Config) -> RunStats:
    """Execute a single discovery->draft cycle. Safe to call standalone."""
    stats = RunStats()

    kill = KillSwitch(config)
    if kill.is_active():
        stats.halted = True
        stats.note = "kill switch active"
        log.warning("Run aborted — %s", stats.note)
        return stats

    keywords = config.keywords
    if not keywords:
        stats.note = "no niche keywords configured"
        log.warning(stats.note)
        return stats

    # 1) Discover across all enabled, rate-ready sources.
    all_items: list[TrendItem] = []
    for source in build_sources(config):
        all_items.extend(source.collect(keywords))
    stats.fetched = len(all_items)
    if not all_items:
        stats.note = "no items fetched (sources disabled, rate-limited, or no creds)"
        log.info(stats.note)
        return stats

    # 2) Dedup against history.
    fresh, dupes = _dedup(all_items)
    stats.new, stats.duplicates = len(fresh), dupes
    if not fresh:
        stats.note = "all fetched items already seen"
        log.info(stats.note)
        return stats

    # 3) Analyse -> ranked topics.
    topics = TrendAnalyzer(config).analyze(fresh)
    stats.topics = len(topics)
    if not topics:
        stats.note = "analysis produced no topics"
        return stats

    # 4) Draft via the configured LLM.
    try:
        llm = get_llm(config)
    except Exception as exc:  # noqa: BLE001
        stats.note = f"LLM unavailable: {exc}"
        log.error(stats.note)
        return stats

    drafter = Drafter(config, llm)
    stats.drafts = drafter.generate(topics)

    log.info("Run complete: %s", stats.summary())
    return stats
