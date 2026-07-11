from pathlib import Path

from trendengine.media.short import (build_ffmpeg_cmd, script_from_caption,
                                     wrap_caption)


def test_script_strips_tags_emoji_and_caps_length():
    caption = "Check this out 🚀 https://x.com/a #ai #agents " + "word " * 300
    script = script_from_caption(caption, max_seconds=10)
    assert "#ai" not in script and "🚀" not in script and "http" not in script
    # ~2.5 words/sec * 10s = 25 words ceiling
    assert len(script.split()) <= 25


def test_wrap_caption_limits_line_width():
    wrapped = wrap_caption("word " * 40, width=20, max_lines=5)
    lines = wrapped.split("\n")
    assert len(lines) <= 5
    assert all(len(ln) <= 20 for ln in lines)


def test_build_ffmpeg_cmd_shape_with_audio(tmp_path):
    media = {"resolution": "1080x1920", "fps": 30, "background": "solid",
             "background_color": "#0f1216"}
    cmd = build_ffmpeg_cmd(tmp_path / "out.mp4", 12.0, media,
                           tmp_path / "t.txt", tmp_path / "a.aiff",
                           tmp_path / "title.txt")
    assert cmd[0] == "ffmpeg"
    assert "libx264" in cmd and "yuv420p" in cmd
    assert "-shortest" in cmd                      # audio muxing present
    assert str(tmp_path / "out.mp4") == cmd[-1]
    assert any("drawtext" in a for a in cmd)


def test_build_ffmpeg_cmd_silent_has_no_audio_flags(tmp_path):
    media = {"resolution": "1080x1920", "fps": 30}
    cmd = build_ffmpeg_cmd(tmp_path / "o.mp4", 8.0, media, tmp_path / "t.txt", None)
    assert "-shortest" not in cmd
    assert "aac" not in cmd
