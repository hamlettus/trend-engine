import datetime as dt

from trendengine.learning.corpus import CorpusLearner
from trendengine.learning.features import (classify_style, count_hashtags,
                                           derive_arms, nearest)
from trendengine.sources.base import TrendItem


def _item(title, views, hour=12):
    return TrendItem(source="youtube", external_id=f"{title[:10]}-{views}",
                     title=title, url="https://y/x", score=views,
                     created_at=dt.datetime(2026, 1, 1, hour, tzinfo=dt.timezone.utc),
                     keyword="AI agents", engagement={"views": views})


def test_classify_style():
    assert classify_style("Why AI agents win") == "hook_first"
    assert classify_style("Is this the future?") == "question"
    assert classify_style("5 ways to use AI agents") == "listicle"
    assert classify_style("AI agents are powerful tools") == "bold_claim"


def test_nearest_and_hashtags():
    assert nearest(4, [3, 5, 8]) == "3"
    assert count_hashtags("hello #ai world #agents #ml") == 3


def test_derive_arms_maps_to_arm_space(config):
    spec = config.raw["learning"]["bandit_arms"]
    arms = derive_arms("5 ways to grow #a #b #c", "", 20, spec)
    assert arms["caption_style"] == "listicle"
    assert arms["hashtag_count"] in [str(v) for v in spec["hashtag_count"]]
    assert arms["post_hour"] in [str(v) for v in spec["post_hour"]]


def test_collect_reference_stores_items(config):
    items = [_item("Why AI agents win", 9000), _item("AI agents overview", 120)]
    n = CorpusLearner(config).collect_reference(items=items)
    assert n == 2
    # dedup on re-collect
    assert CorpusLearner(config).collect_reference(items=items) == 0


def test_bootstrap_seeds_bandit_toward_public_winners(config):
    winners = [_item(f"Why AI agents matter {i}", 20000 + i) for i in range(3)]
    losers = [_item(f"AI agents are fine tools {i}", 50 + i) for i in range(3)]
    cl = CorpusLearner(config)
    cl.collect_reference(items=winners + losers)
    res = cl.bootstrap_bandit()
    assert res["bootstrapped"] and res["reference_items"] == 6

    # A FRESH bandit (no real pulls yet) should already prefer the winners' style.
    from trendengine.learning.bandit import ThompsonBandit
    snap = {(a["dimension"], a["value"]): a for a in ThompsonBandit(config).snapshot()}
    assert snap[("caption_style", "hook_first")]["win_rate"] > \
           snap[("caption_style", "bold_claim")]["win_rate"]

    picks = [ThompsonBandit(config).select()["caption_style"] for _ in range(60)]
    assert picks.count("hook_first") > picks.count("bold_claim")


def test_bootstrap_is_idempotent_without_force(config):
    cl = CorpusLearner(config)
    cl.collect_reference(items=[_item("Why AI agents win", 9000)])
    assert cl.bootstrap_bandit()["bootstrapped"] is True

    from trendengine.db.database import session_scope
    from trendengine.db.models import BanditArm
    with session_scope() as s:
        before = {(a.dimension, a.value): a.alpha for a in s.query(BanditArm).all()}

    second = cl.bootstrap_bandit()
    assert second["bootstrapped"] is False and "already" in second["note"]
    with session_scope() as s:
        after = {(a.dimension, a.value): a.alpha for a in s.query(BanditArm).all()}
    assert before == after  # not double-seeded

    # force re-seeds.
    assert cl.bootstrap_bandit(force=True)["bootstrapped"] is True
