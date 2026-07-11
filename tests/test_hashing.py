from trendengine.utils.hashing import content_hash, normalize_text


def test_normalize_text_strips_punct_and_case():
    assert normalize_text("Hello,  WORLD!!") == "hello world"


def test_hash_is_stable_and_ignores_tracking_params():
    a = content_hash("reddit", "AI Agents Boom", "https://x.com/p?utm=1")
    b = content_hash("reddit", "AI Agents Boom", "https://x.com/p?utm=2")
    assert a == b


def test_hash_differs_by_source():
    a = content_hash("reddit", "same title", "https://x.com/p")
    b = content_hash("youtube", "same title", "https://x.com/p")
    assert a != b
