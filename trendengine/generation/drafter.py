"""Turn ranked topics into on-brand drafts.

`compose()` is the low-level unit (one topic + optional bandit arms -> parsed
draft dict, not persisted) used by both the dashboard path (`generate`) and the
autonomous path (autopilot gates the composed draft before persisting it).
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass

from trendengine.analysis.aggregator import TopicScore
from trendengine.config import Config
from trendengine.db.database import session_scope
from trendengine.db.models import STATUS_PENDING, Draft
from trendengine.generation.prompts import build_draft_prompt, build_system_prompt
from trendengine.llm.base import LLMClient, LLMError
from trendengine.logging_setup import get_logger

log = get_logger(__name__)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_llm_json(raw: str) -> dict:
    """Extract the JSON object from an LLM response, tolerating stray prose or
    ```json fences that small local models sometimes add."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = re.sub(r"^json", "", text, flags=re.IGNORECASE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_RE.search(text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    raise ValueError("Could not parse JSON from LLM response")


@dataclass
class ComposedDraft:
    caption: str
    hashtags: list[str]
    rationale: str
    features: dict
    source_summary: str


def _drafts_today(session) -> int:
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    return session.query(Draft).filter(Draft.created_at >= since).count()


class Drafter:
    def __init__(self, config: Config, llm: LLMClient) -> None:
        self.config = config
        self.llm = llm
        self._hints: list[str] | None = None  # lazily loaded title-model hints

    def _virality_hints(self) -> list[str]:
        if self._hints is None:
            try:
                from trendengine.learning.title_model import TitleModel
                self._hints = TitleModel(self.config).hints()
            except Exception:  # noqa: BLE001 - hints are best-effort
                self._hints = []
        return self._hints

    # -- low-level: one topic -> composed draft (no persistence) -----------
    def compose(self, topic: TopicScore, arms: dict | None = None) -> ComposedDraft:
        arms = arms or {}
        style = arms.get("caption_style")
        hashtag_count = _as_int(arms.get("hashtag_count"))
        base_tags = self.config.brand.get("hashtags_base", [])
        system = build_system_prompt(self.config)
        prompt = build_draft_prompt(topic, self.config, style=style,
                                    hashtag_count=hashtag_count,
                                    virality_hints=self._virality_hints())

        raw = self.llm.generate(prompt, system=system)  # may raise LLMError
        try:
            data = _parse_llm_json(raw)
            caption = str(data.get("caption", "")).strip()
            proposed = data.get("hashtags", [])
            rationale = str(data.get("rationale", "")).strip()
        except ValueError:
            log.warning("Non-JSON response for '%s'; using raw text.", topic.topic)
            caption, proposed, rationale = raw.strip(), [], ""

        tags = _merge_hashtags(base_tags, proposed, cap=hashtag_count)
        features = {"frequency": float(topic.frequency),
                    "growth": float(topic.growth),
                    "engagement": float(topic.engagement)}
        source_summary = "; ".join(f"[{i.source}] {i.title}"
                                   for i in topic.top_items(3))[:2000]
        return ComposedDraft(caption, tags, rationale, features, source_summary)

    # -- dashboard path: compose + persist as pending ----------------------
    def generate(self, topics: list[TopicScore]) -> list[int]:
        gen = self.config.generation
        max_topics = int(gen.get("max_topics", 5))
        drafts_per_run = int(gen.get("drafts_per_run", 3))
        max_per_day = int(self.config.safety.get("max_drafts_per_day", 12))
        platform = gen.get("platform", "instagram")

        created_ids: list[int] = []
        with session_scope() as session:
            budget = min(drafts_per_run, max(0, max_per_day - _drafts_today(session)))
            if budget <= 0:
                log.warning("Daily draft cap reached — skipping generation.")
                return []

            for topic in topics[:max_topics]:
                if len(created_ids) >= budget:
                    break
                try:
                    c = self.compose(topic)
                except LLMError as exc:
                    log.error("LLM generation failed for '%s': %s", topic.topic, exc)
                    continue
                if not c.caption:
                    continue
                draft = Draft(
                    topic=topic.topic, platform=platform, caption=c.caption,
                    hashtags=" ".join(c.hashtags), rationale=c.rationale,
                    source_summary=c.source_summary, status=STATUS_PENDING,
                    score=topic.score, features=c.features,
                    llm_provider=self.llm.provider, llm_model=self.llm.model)
                session.add(draft)
                session.flush()
                created_ids.append(draft.id)
                log.info("Drafted #%d for topic '%s'", draft.id, topic.topic)
        return created_ids


def _as_int(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def _merge_hashtags(base: list[str], proposed, cap: int | None = None) -> list[str]:
    """Base tags always kept; topical tags fill up to `cap` total if given."""
    out: list[str] = []
    seen: set[str] = set()
    for tag in list(base):
        tag = _norm_tag(tag)
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            out.append(tag)
    for tag in list(proposed or []):
        if cap is not None and len(out) >= cap:
            break
        tag = _norm_tag(tag)
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            out.append(tag)
    return out


def _norm_tag(tag) -> str:
    if not tag:
        return ""
    tag = str(tag).strip()
    return tag if tag.startswith("#") else f"#{tag}"
