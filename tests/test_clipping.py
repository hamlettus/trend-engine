import pytest

from trendengine.clipping.campaign import (Campaign, UnauthorizedSource,
                                           ensure_authorized, load_campaigns)
from trendengine.clipping.clipper import build_clip_cmd, parse_moments
from trendengine.clipping.transcript import parse_vtt, to_srt, window

SAMPLE_VTT = """WEBVTT

00:00:01.000 --> 00:00:04.000
Here is the hook line

00:00:04.000 --> 00:00:04.500
Here is the hook line

00:00:05.000 --> 00:00:09.000
and now the payoff <c>with tags</c>
"""


# -- authorization gate ----------------------------------------------------

def test_ensure_authorized_blocks_without_note():
    c = Campaign(id="x", authorized=True, authorization_note="")
    with pytest.raises(UnauthorizedSource):
        ensure_authorized(c)


def test_ensure_authorized_blocks_when_false():
    c = Campaign(id="x", authorized=False, authorization_note="licensed")
    with pytest.raises(UnauthorizedSource):
        ensure_authorized(c)


def test_ensure_authorized_passes_when_asserted():
    c = Campaign(id="x", authorized=True, authorization_note="Whop #123 per-view")
    ensure_authorized(c)  # no raise


def test_sample_campaigns_yaml_is_unauthorized_by_default():
    """The shipped example must not be clippable until the user asserts rights."""
    camps = load_campaigns()
    if camps:  # campaigns.yaml ships with an example
        for c in camps.values():
            if c.id == "example-campaign":
                with pytest.raises(UnauthorizedSource):
                    ensure_authorized(c)


# -- transcript ------------------------------------------------------------

def test_parse_vtt_dedups_and_strips_tags():
    segs = parse_vtt(SAMPLE_VTT)
    assert len(segs) == 2                      # the repeated rolling line collapses
    assert segs[0].text == "Here is the hook line"
    assert "with tags" in segs[1].text and "<c>" not in segs[1].text


def test_window_clips_to_range():
    segs = parse_vtt(SAMPLE_VTT)
    w = window(segs, 4.5, 9.0)
    assert len(w) == 1 and w[0].start >= 4.5


def test_to_srt_offsets_to_zero():
    segs = parse_vtt(SAMPLE_VTT)
    srt = to_srt(segs, offset=1.0)
    assert "00:00:00,000 -->" in srt          # first seg started at 1s, now 0


# -- moment parsing --------------------------------------------------------

def test_parse_moments_clamps_and_limits():
    raw = ('{"clips": [{"start": 0, "end": 200, "hook": "long"},'
           '{"start": 300, "end": 305, "hook": "too short"},'
           '{"start": 400, "end": 430, "hook": "ok"}]}')
    moments = parse_moments(raw, min_s=15, max_s=60, limit=5, source_duration=1000)
    # first clamped to 60s, second dropped (<15s), third kept
    assert len(moments) == 2
    assert moments[0].length == 60
    assert moments[1].hook == "ok"


def test_parse_moments_drops_out_of_range():
    raw = '{"clips": [{"start": 5000, "end": 5030}]}'
    assert parse_moments(raw, 15, 60, 5, source_duration=1000) == []


def test_parse_moments_handles_garbage():
    assert parse_moments("not json at all", 15, 60, 5) == []


# -- ffmpeg command --------------------------------------------------------

def test_build_clip_cmd_crops_vertical_and_muxes():
    cmd = build_clip_cmd("in.mp4", "out.mp4", 10.0, 40.0, "1080x1920")
    assert cmd[0] == "ffmpeg"
    vf = cmd[cmd.index("-vf") + 1]
    assert "crop='min(iw,ih*9/16)':ih" in vf and "scale=1080:1920" in vf
    assert "-ss" in cmd and "30.00" in cmd          # duration = end - start
    assert cmd[-1] == "out.mp4"


def test_build_clip_cmd_burns_subtitles_when_given():
    cmd = build_clip_cmd("in.mp4", "out.mp4", 0, 20, srt="subs.srt")
    vf = cmd[cmd.index("-vf") + 1]
    assert "subtitles='subs.srt'" in vf
