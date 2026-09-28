"""Tests for the Chatterbox local TTS provider (resemble-ai/chatterbox).

The real model is never loaded here: the worker subprocess and the package
probe are both faked.
"""
import importlib.util
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.backend import voice_gen as vg
from src.backend.chatterbox_synthesize import (
    split_text_chunks,
    _stitch_with_room_tone,
)


# ── provider resolution ──────────────────────────────────────────────────

def test_resolver_chatterbox_label():
    assert vg._resolve_tts_provider("Chatterbox (Local Free)", "auto") == "chatterbox"


def test_resolver_chatterbox_prefix_forms():
    assert vg._resolve_tts_provider("chatterbox", "auto") == "chatterbox"
    assert vg._resolve_tts_provider("chatterbox:turbo", "auto") == "chatterbox"
    assert vg._resolve_tts_provider("chatterbox:multilingual", "auto") == "chatterbox"
    assert vg._resolve_tts_provider("chatterbox:clone:C:/v/ref.wav", "auto") == "chatterbox"


def test_resolver_explicit_provider():
    assert vg._resolve_tts_provider("af_heart", "chatterbox") == "chatterbox"


def test_resolver_does_not_shadow_others():
    assert vg._resolve_tts_provider("fish", "auto") == "fish"
    assert vg._resolve_tts_provider("elevenlabs-xyz", "auto") == "elevenlabs"
    assert vg._resolve_tts_provider("af_heart", "auto") == "kokoro"
    assert vg._resolve_tts_provider("en-IN-PrabhatNeural", "auto") == "edge-tts"
    assert vg._resolve_tts_provider("omni", "auto") == "omnivoice"


# ── voice spec parsing ───────────────────────────────────────────────────

def test_parse_default_turbo():
    spec = vg._parse_chatterbox_voice("Chatterbox (Local Free)")
    assert spec["backend"] == "turbo"


def test_parse_multilingual():
    spec = vg._parse_chatterbox_voice("chatterbox:multilingual")
    assert spec["backend"] == "multilingual"


def test_parse_clone():
    spec = vg._parse_chatterbox_voice("chatterbox:clone:C:/voices/me.wav")
    assert spec["backend"] == "turbo"
    assert spec["ref_audio"] == "C:/voices/me.wav"


def test_parse_default_ref_from_env(monkeypatch, tmp_path):
    ref = tmp_path / "narrator.wav"
    ref.write_bytes(b"RIFF....")
    monkeypatch.setenv("CHATTERBOX_REF_AUDIO", str(ref))
    spec = vg._parse_chatterbox_voice("chatterbox")
    assert spec["ref_audio"] == str(ref)


def test_parse_missing_ref_raises_on_generate(monkeypatch):
    # A clone spec pointing at a nonexistent file must fail LOUD, not silently
    # read with the default voice (a silent voice swap is an anti-slop violation).
    monkeypatch.setenv("CHATTERBOX_REF_AUDIO", "")
    monkeypatch.delenv("CHATTERBOX_REF_AUDIO", raising=False)
    monkeypatch.setattr(vg, "_chatterbox_available", lambda: True)
    with pytest.raises(RuntimeError, match="clone reference not found"):
        vg._generate_audio_chatterbox(
            "hello", "/tmp/x.wav", voice="chatterbox:clone:/nonexistent/ref.wav")


# ── chunk splitting (short chunks kill monotone drift) ───────────────────

def test_chunks_are_sentence_bounded_and_short():
    text = "Hello world. " * 60  # ~720 chars
    chunks = split_text_chunks(text, 300)
    assert all(len(c) <= 300 for c in chunks)
    assert all(c.rstrip().endswith((".", "!", "?", "…")) for c in chunks)
    assert len(chunks) > 1


def test_empty_text_has_no_chunks():
    assert split_text_chunks("   ") == []


# ── stitching: room tone, no digital-silence gaps, normalized ────────────

def test_stitch_inserts_room_tone_between_chunks():
    import numpy as np
    sr = 24000
    rng = np.random.default_rng(7)
    a1 = (rng.standard_normal(sr) * 0.5).astype("float32")   # 1s of tone
    a2 = (rng.standard_normal(sr) * 0.05).astype("float32")  # 1s quiet tone
    stitched = _stitch_with_room_tone([a1, a2], sr, room_tone_ms=220)
    expected = 2 * sr + int(sr * 0.22)
    assert len(stitched) == expected
    # The gap region is room tone (low but non-zero), not digital silence.
    gap = stitched[sr:sr + int(sr * 0.22)]
    assert float(abs(gap).max()) > 1e-5
    assert float(abs(gap).max()) < 0.05
    # Both chunks were normalized to the same peak (~0.89) — no volume jumps.
    peak1 = float(abs(stitched[:sr]).max())
    peak2 = float(abs(stitched[-sr:]).max())
    assert peak1 == pytest.approx(peak2, rel=0.05)


def test_stitch_empty_chunks_raises():
    with pytest.raises(RuntimeError):
        _stitch_with_room_tone([], 24000, 220)


# ── worker wiring (subprocess faked) ─────────────────────────────────────

def test_generate_audio_chatterbox_routes_through_worker(monkeypatch, tmp_path):
    monkeypatch.setattr(vg, "_chatterbox_available", lambda: True)
    monkeypatch.setenv("CHATTERBOX_REF_AUDIO", "")

    seen_cmd = {}

    def fake_run(cmd, **kwargs):
        seen_cmd["cmd"] = cmd
        # The worker would have written this; we fake it.
        out_idx = cmd.index("--output") + 1
        out_path = cmd[out_idx]
        import numpy as np
        import soundfile as sf
        sf.write(out_path, np.zeros(2400, dtype="float32"), 24000)

        class R:
            returncode = 0
            stderr = ""
            stdout = ""
        return R()

    monkeypatch.setattr("subprocess.run", fake_run)
    out = str(tmp_path / "voice.wav")
    got, srt = vg._generate_audio_chatterbox("Hello world", out, voice="chatterbox:turbo")
    assert got == out and os.path.exists(out)
    assert srt is None  # no word timings from worker (faster-whisper handles it)
    cmd = seen_cmd["cmd"]
    assert "chatterbox_synthesize.py" in cmd[1]
    assert "--backend" in cmd and "turbo" in cmd
    assert "--exaggeration" in cmd and "--cfg-weight" in cmd


def test_generate_audio_chatterbox_missing_package_falls_back():
    # When the package is missing, the provider raises (caller falls back to Edge).
    with pytest.raises(RuntimeError, match="not installed"):
        vg._generate_audio_chatterbox("hello", "/tmp/x.wav", voice="chatterbox")
