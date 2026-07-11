"""The autonomous quality/safety gate.

In autopilot there is no human approver, so a draft must pass ALL of these
before it can be rendered and posted:

  1. length bounds
  2. banned-term blocklist
  3. topic-recency dedup (don't re-post a topic within N days)
  4. an LLM self-critique pass that scores the draft 1-10 against brand + safety

Any failure rejects the draft with a reason (stored on the draft for audit).
This is deliberately conservative: the cost of a bad autonomous post is high.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from trendengine.config import Config
from trendengine.db.database import session_scope
from trendengine.db.models import STATUS_POSTED, STATUS_SHADOW, Draft
from trendengine.generation.drafter import _parse_llm_json
from trendengine.llm.base import LLMClient, LLMError
from trendengine.logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class GateResult:
    passed: bool
    score: float | None = None          # LLM self-critique score (1-10)
    reasons: list[str] = field(default_factory=list)

    @property
    def notes(self) -> str:
        return "; ".join(self.reasons)


CRITIQUE_SYSTEM = (
    "You are a strict brand-safety and quality reviewer for social posts. You "
    "reject anything off-brand, misleading, unsafe, spammy, or low quality. You "
    "reply with ONLY JSON."
)


class QualityGate:
    def __init__(self, config: Config, llm: LLMClient | None = None) -> None:
        self.config = config
        self.g = config.raw.get("guardrails", {})
        self.llm = llm

    def check(self, topic_score: float, caption: str, hashtags: str,
              topic: str) -> GateResult:
        reasons: list[str] = []

        # 1) topic strength
        min_score = float(self.g.get("min_topic_score", 0.35))
        if topic_score < min_score:
            reasons.append(f"topic score {topic_score:.2f} < min {min_score}")

        # 2) length
        n = len(caption or "")
        lo = int(self.g.get("min_caption_chars", 60))
        hi = int(self.g.get("max_caption_chars", 2200))
        if n < lo:
            reasons.append(f"caption too short ({n} < {lo})")
        if n > hi:
            reasons.append(f"caption too long ({n} > {hi})")

        # 3) banned terms
        haystack = f"{caption} {hashtags}".lower()
        for term in self.g.get("banned_terms", []):
            if re.search(rf"\b{re.escape(str(term).lower())}\b", haystack):
                reasons.append(f"banned term: '{term}'")

        # 4) topic-recency dedup
        if self._recently_posted(topic):
            reasons.append(f"topic '{topic}' posted within "
                          f"{self.g.get('dedup_days', 30)}d")

        # Cheap checks failed already — don't spend an LLM call.
        if reasons:
            return GateResult(passed=False, reasons=reasons)

        # 5) LLM self-critique (the expensive, judgment check)
        score = None
        if self.g.get("require_llm_self_critique", True) and self.llm is not None:
            score, critique_reasons = self._self_critique(caption, hashtags, topic)
            min_crit = float(self.g.get("self_critique_min_score", 7))
            if score is not None and score < min_crit:
                reasons.append(f"self-critique {score} < {min_crit}: "
                              f"{'; '.join(critique_reasons)}")

        return GateResult(passed=not reasons, score=score, reasons=reasons)

    # -- internals ---------------------------------------------------------
    def _recently_posted(self, topic: str) -> bool:
        days = int(self.g.get("dedup_days", 30))
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
        with session_scope() as s:
            hit = (s.query(Draft.id)
                   .filter(Draft.topic == topic,
                           Draft.status.in_([STATUS_POSTED, STATUS_SHADOW]),
                           Draft.created_at >= cutoff)
                   .first())
        return hit is not None

    def _self_critique(self, caption: str, hashtags: str,
                       topic: str) -> tuple[float | None, list[str]]:
        brand = self.config.brand
        prompt = f"""\
Review this social post draft for the niche "{self.config.niche.get('name','')}".
Brand voice: {brand.get('voice','')}

DRAFT:
{caption}
{hashtags}

Score it 1-10 on: on-brand voice, clarity, honesty (no unsupported claims),
safety, and non-spamminess. Respond with ONLY:
{{"score": <1-10 integer>, "issues": ["..."], "verdict": "pass" | "reject"}}
"""
        try:
            raw = self.llm.generate(prompt, system=CRITIQUE_SYSTEM, temperature=0.0)
        except LLMError as exc:
            # Fail CLOSED: if we can't critique, don't auto-post.
            log.warning("Self-critique unavailable (%s) — failing gate closed.", exc)
            return 0.0, ["self-critique LLM unavailable"]
        try:
            data = _parse_llm_json(raw)
            score = float(data.get("score", 0))
            issues = [str(i) for i in data.get("issues", [])]
            if str(data.get("verdict", "")).lower() == "reject":
                issues.append("reviewer verdict: reject")
                score = min(score, 0.0) if score else 0.0
            return score, issues
        except (ValueError, TypeError):
            log.warning("Could not parse self-critique JSON — failing gate closed.")
            return 0.0, ["unparseable self-critique"]
