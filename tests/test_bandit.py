from trendengine.learning.bandit import ThompsonBandit


def test_bandit_selects_one_arm_per_dimension(config):
    b = ThompsonBandit(config)
    arms = b.select()
    for dim in b.arms_spec:
        assert dim in arms
        assert str(arms[dim]) in [str(v) for v in b.arms_spec[dim]]


def test_bandit_learns_toward_winner(config):
    """After rewarding one caption_style repeatedly, it should dominate selection."""
    b = ThompsonBandit(config)
    winner = str(config.raw["learning"]["bandit_arms"]["caption_style"][0])
    loser = str(config.raw["learning"]["bandit_arms"]["caption_style"][1])

    for _ in range(40):
        b.update({"caption_style": winner}, reward=0.9, threshold=0.1)
        b.update({"caption_style": loser}, reward=0.0, threshold=0.1)

    picks = [b.select()["caption_style"] for _ in range(60)]
    assert picks.count(winner) > picks.count(loser)

    snap = {(a["dimension"], a["value"]): a for a in b.snapshot()}
    assert snap[("caption_style", winner)]["win_rate"] > \
           snap[("caption_style", loser)]["win_rate"]
