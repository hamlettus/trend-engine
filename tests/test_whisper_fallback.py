import pytest

from trendengine.clipping.transcript import Segment
from trendengine.clipping.whisper import WhisperError, transcribe


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def _audio(tmp_path, mb=0.1):
    p = tmp_path / "a.m4a"
    p.write_bytes(b"\x00" * int(mb * 1_000_000))
    return p


def test_transcribe_requires_key(config, tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(WhisperError) as e:
        transcribe(_audio(tmp_path), config)
    assert "GROQ_API_KEY" in str(e.value)


def test_transcribe_parses_verbose_json(config, tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    captured = {}

    def fake_post(url, headers=None, files=None, data=None, timeout=None):
        captured["url"] = url
        captured["model"] = data["model"]
        return _Resp(200, {"segments": [
            {"start": 0.0, "end": 2.5, "text": "hello"},
            {"start": 2.5, "end": 5.0, "text": "world"},
        ]})

    monkeypatch.setattr("trendengine.clipping.whisper.requests.post", fake_post)
    segs = transcribe(_audio(tmp_path), config)
    assert [s.text for s in segs] == ["hello", "world"]
    assert isinstance(segs[0], Segment) and segs[1].end == 5.0
    assert "groq" in captured["url"] and captured["model"] == "whisper-large-v3"


def test_transcribe_openai_backend(config, tmp_path, monkeypatch):
    config.raw["media"]["whisper_backend"] = "openai"
    monkeypatch.setenv("OPENAI_API_KEY", "sk_test")
    monkeypatch.setattr("trendengine.clipping.whisper.requests.post",
                        lambda *a, **k: _Resp(200, {"segments": []}))
    assert transcribe(_audio(tmp_path), config) == []


def test_transcribe_chunks_oversized_audio_and_offsets_time(config, tmp_path, monkeypatch):
    """Audio over the cap is split into chunks and stitched into absolute time."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    config.raw["media"]["whisper_chunk_seconds"] = 600
    # 20-minute source -> 2 chunks of 600s.
    monkeypatch.setattr("trendengine.clipping.whisper._probe_duration",
                        lambda p: 1200.0)
    monkeypatch.setattr("trendengine.clipping.whisper._extract_chunk",
                        lambda audio, start, dur, out: (out.write_bytes(b"\x00"), out)[1])

    calls = {"n": 0}
    def fake_post(url, headers=None, files=None, data=None, timeout=None):
        calls["n"] += 1
        return _Resp(200, {"segments": [{"start": 1.0, "end": 3.0, "text": "seg"}]})
    monkeypatch.setattr("trendengine.clipping.whisper.requests.post", fake_post)

    segs = transcribe(_audio(tmp_path, mb=30), config)
    assert calls["n"] == 2                       # two chunks transcribed
    assert len(segs) == 2
    assert segs[0].start == 1.0                  # chunk 1: no offset
    assert segs[1].start == 601.0                # chunk 2: offset by 600s


def test_transcribe_chunking_tolerates_partial_failure(config, tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    config.raw["media"]["whisper_chunk_seconds"] = 600
    monkeypatch.setattr("trendengine.clipping.whisper._probe_duration",
                        lambda p: 1200.0)
    monkeypatch.setattr("trendengine.clipping.whisper._extract_chunk",
                        lambda audio, start, dur, out: (out.write_bytes(b"\x00"), out)[1])

    state = {"n": 0}
    def flaky_post(url, headers=None, files=None, data=None, timeout=None):
        state["n"] += 1
        if state["n"] == 1:
            return _Resp(500, text="boom")       # first chunk fails
        return _Resp(200, {"segments": [{"start": 0.5, "end": 2.0, "text": "ok"}]})
    monkeypatch.setattr("trendengine.clipping.whisper.requests.post", flaky_post)

    segs = transcribe(_audio(tmp_path, mb=30), config)
    assert len(segs) == 1                          # partial transcript survives
    assert segs[0].start == 600.5                  # from the second (surviving) chunk


def test_transcribe_maps_http_error(config, tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr("trendengine.clipping.whisper.requests.post",
                        lambda *a, **k: _Resp(401, text="bad"))
    with pytest.raises(WhisperError) as e:
        transcribe(_audio(tmp_path), config)
    assert "401" in str(e.value)


def test_download_falls_back_when_no_captions(config, monkeypatch):
    """ClipGenerator uses Whisper when yt-dlp returns no captions."""
    from trendengine.clipping.clipper import ClipGenerator
    gen = ClipGenerator(config)
    fake_segs = [Segment(0.0, 3.0, "from whisper")]
    monkeypatch.setattr(
        "trendengine.clipping.whisper.extract_audio",
        lambda video, out: out)
    monkeypatch.setattr(
        "trendengine.clipping.whisper.transcribe",
        lambda audio, cfg: fake_segs)
    # _transcribe_fallback is what download() calls when captions are absent.
    from pathlib import Path
    segs = gen._transcribe_fallback(Path("/tmp/video.mp4"))
    assert segs == fake_segs


def test_fallback_returns_empty_on_whisper_error(config, monkeypatch):
    """A failed transcription degrades gracefully (no captions, no crash)."""
    from pathlib import Path
    from trendengine.clipping.clipper import ClipGenerator
    from trendengine.clipping.whisper import WhisperError

    def boom(video, out):
        raise WhisperError("ffmpeg missing")
    monkeypatch.setattr("trendengine.clipping.whisper.extract_audio", boom)
    assert ClipGenerator(config)._transcribe_fallback(Path("/tmp/v.mp4")) == []
