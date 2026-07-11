from trendengine.utils.killswitch import KillSwitch


def test_killswitch_engage_release(config, tmp_path, monkeypatch):
    ks = KillSwitch(config)
    ks.path = tmp_path / ".killswitch"
    assert ks.is_active() is False
    ks.engage()
    assert ks.is_active() is True
    ks.release()
    assert ks.is_active() is False


def test_global_disabled_flag_halts(config):
    config.raw.setdefault("safety", {})["global_enabled"] = False
    assert KillSwitch(config).is_active() is True
    config.raw["safety"]["global_enabled"] = True
