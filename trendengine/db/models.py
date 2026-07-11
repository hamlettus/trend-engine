"""SQLAlchemy models: dedup, drafts, post history, performance feedback."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Integer,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


# Draft lifecycle states.
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_POSTED = "posted"
STATUS_SHADOW = "shadow"      # autopilot would-have-posted (shadow mode, not live)
STATUS_FAILED = "failed"      # render/upload failed
VALID_STATUSES = {STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED, STATUS_POSTED,
                  STATUS_SHADOW, STATUS_FAILED}


class SeenContent(Base):
    """Every discovered item, hashed, so we never re-process the same thing."""
    __tablename__ = "seen_content"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(255), default="")
    title: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text, default="")
    keyword: Mapped[str] = mapped_column(String(128), default="")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    first_seen: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class TrendObservation(Base):
    """Point-in-time score per topic, used to compute growth rate over time."""
    __tablename__ = "trend_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic: Mapped[str] = mapped_column(String(128), index=True)
    source: Mapped[str] = mapped_column(String(32), default="")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    frequency: Mapped[int] = mapped_column(Integer, default=0)
    observed_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class Draft(Base):
    """A generated post draft awaiting human approval."""
    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic: Mapped[str] = mapped_column(String(255), default="")
    platform: Mapped[str] = mapped_column(String(32), default="instagram")
    caption: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[str] = mapped_column(Text, default="")   # space-separated
    media_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str] = mapped_column(Text, default="")   # why this trend / why now
    source_summary: Mapped[str] = mapped_column(Text, default="")  # supporting evidence
    status: Mapped[str] = mapped_column(String(16), default=STATUS_PENDING, index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)   # topic score at draft time
    llm_provider: Mapped[str] = mapped_column(String(32), default="")
    llm_model: Mapped[str] = mapped_column(String(64), default="")
    export_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    posted_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    # -- autopilot / autonomous fields --
    auto: Mapped[bool] = mapped_column(Boolean, default=False)   # created by autopilot
    gate_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # LLM self-critique 1-10
    gate_notes: Mapped[str] = mapped_column(Text, default="")    # why gated / passed
    arms: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # bandit arms chosen
    features: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # topic features at draft time
    learned_applied: Mapped[bool] = mapped_column(Boolean, default=False)  # bandit reward folded in
    video_path: Mapped[str | None] = mapped_column(Text, nullable=True)  # rendered Short
    external_post_id: Mapped[str | None] = mapped_column(String(255), nullable=True)  # youtube id

    feedback: Mapped[list["PerformanceFeedback"]] = relationship(
        back_populates="draft", cascade="all, delete-orphan")
    metrics: Mapped[list["PostMetric"]] = relationship(
        back_populates="draft", cascade="all, delete-orphan")

    def hashtag_list(self) -> list[str]:
        return [h for h in (self.hashtags or "").split() if h]


class PostHistory(Base):
    """Record of a draft the user actually marked as posted."""
    __tablename__ = "post_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id"), index=True)
    platform: Mapped[str] = mapped_column(String(32), default="")
    caption: Mapped[str] = mapped_column(Text, default="")
    external_post_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    posted_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class PerformanceFeedback(Base):
    """Engagement you log on YOUR published posts — feeds the learning loop."""
    __tablename__ = "performance_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int | None] = mapped_column(ForeignKey("drafts.id"), nullable=True, index=True)
    topic: Mapped[str] = mapped_column(String(255), default="", index=True)
    platform: Mapped[str] = mapped_column(String(32), default="")
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    reach: Mapped[int] = mapped_column(Integer, default=0)
    engagement_rate: Mapped[float] = mapped_column(Float, default=0.0)
    logged_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, index=True)

    draft: Mapped["Draft"] = relationship(back_populates="feedback")

    def compute_engagement_rate(self) -> float:
        interactions = self.likes + self.comments + self.shares + self.saves
        if self.reach > 0:
            return round(interactions / self.reach, 4)
        return float(interactions)


class PostMetric(Base):
    """Auto-ingested performance snapshot for a posted video (time-series).

    The learning loop pulls these from the platform API at intervals after
    posting, so it sees how engagement settles over time — no manual logging.
    """
    __tablename__ = "post_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id"), index=True)
    external_post_id: Mapped[str] = mapped_column(String(255), default="", index=True)
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    engagement_rate: Mapped[float] = mapped_column(Float, default=0.0)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, index=True)

    draft: Mapped["Draft"] = relationship(back_populates="metrics")

    def compute_engagement_rate(self) -> float:
        if self.views > 0:
            return round((self.likes + self.comments) / self.views, 4)
        return 0.0


class BanditArm(Base):
    """One arm of a multi-armed bandit (Beta-Bernoulli / Thompson sampling).

    Dimensions are controllable choices (post_hour, caption_style, …). The
    engine samples an arm per post; when performance lands, the arm's reward is
    folded into alpha/beta. Success = engagement above the running threshold.
    """
    __tablename__ = "bandit_arms"
    __table_args__ = (UniqueConstraint("dimension", "value", name="uq_arm"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dimension: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[str] = mapped_column(String(64))
    alpha: Mapped[float] = mapped_column(Float, default=1.0)   # Beta prior successes+1
    beta: Mapped[float] = mapped_column(Float, default=1.0)    # Beta prior failures+1
    pulls: Mapped[int] = mapped_column(Integer, default=0)
    reward_sum: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    @property
    def mean_reward(self) -> float:
        return self.reward_sum / self.pulls if self.pulls else 0.0


class LearnedWeight(Base):
    """A scoring weight the system learned from its own results (vs. config).

    The weight learner fits engagement ~ features and stores the resulting,
    bounded coefficients here. Analysis blends these over the config defaults.
    """
    __tablename__ = "learned_weights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feature: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    weight: Mapped[float] = mapped_column(Float, default=0.0)
    samples: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class CanaryState(Base):
    """Tracks the autopilot daily-volume ramp so it can grow safely over days."""
    __tablename__ = "canary_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    current_per_day: Mapped[int] = mapped_column(Integer, default=1)
    last_ramped_on: Mapped[dt.date | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class ReferenceContent(Base):
    """Already-out-there public winners used to warm-start the learners.

    Discovered high-performing content (top YouTube videos, high-upvote Reddit
    posts) with its engagement and derived features, so the bandit can be seeded
    from what works in the niche BEFORE the engine posts anything of its own.
    """
    __tablename__ = "reference_content"
    __table_args__ = (UniqueConstraint("platform", "external_id", name="uq_ref"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text, default="")
    engagement: Mapped[float] = mapped_column(Float, default=0.0)  # views / upvotes
    publish_hour: Mapped[int] = mapped_column(Integer, default=0)
    hashtag_count: Mapped[int] = mapped_column(Integer, default=0)
    style: Mapped[str] = mapped_column(String(32), default="")
    keyword: Mapped[str] = mapped_column(String(128), default="")
    collected_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class SystemState(Base):
    """Tiny key/value store for one-off flags (e.g., bandit bootstrap done)."""
    __tablename__ = "system_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class TitleSignal(Base):
    """A learned coefficient for how a title feature relates to engagement.

    Fit from the public reference corpus (and your own posts, once they exist).
    Positive coef = the feature is associated with better performance in-niche;
    the strongest signals become plain-English hints in the draft prompt.
    """
    __tablename__ = "title_signals"

    feature: Mapped[str] = mapped_column(String(64), primary_key=True)
    coef: Mapped[float] = mapped_column(Float, default=0.0)
    samples: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
