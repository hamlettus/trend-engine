from trendengine.pipeline import _dedup
from tests.conftest import make_item


def test_dedup_filters_repeats(config):
    items = [make_item(title="Trend one"), make_item(title="Trend two")]
    fresh, dupes = _dedup(items)
    assert len(fresh) == 2 and dupes == 0

    # Re-running with an overlapping item marks it as duplicate.
    again = [make_item(title="Trend one"), make_item(title="Trend three")]
    fresh2, dupes2 = _dedup(again)
    assert dupes2 == 1
    assert {i.title for i in fresh2} == {"Trend three"}
