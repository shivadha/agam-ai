"""Tests for the OmniVoice local TTS provider (k2-fsa/OmniVoice).

The real model is never loaded here: the worker subprocess and the package
probe are both faked.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.backend import voice_gen as vg
from src.backend.omnivoice_synthesize import split_text_chunks


# ── provider resolution ──────────────────────────────────────────────────

def test_resolver_omnivoice_label():
    assert vg._resolve_tts_provider("OmniVoice (Local Free)", "auto") == "omnivoice"


def test_resolver_omni_prefix_forms():
    assert vg._resolve_tts_provider("omni", "auto") == "omnivoice"
    assert vg._resolve_tts_provider("omni:design:female, low pitch", "auto") == "omnivoice"
    assert vg._resolve_tts_provider("omni:clone:C:/v/ref.wav", "auto") == "omnivoice"


def test_resolver_explicit_provider():
    assert vg._resolve_tts_provider("af_heart", "omnivoice") == "omnivoice"


def test_resolver_does_not_shadow_others():
    assert vg._resolve_tts_provider("fish", "auto") == "fish"
    assert vg._resolve_tts_provider("elevenlabs-xyz", "auto") == "elevenlabs"
    assert vg._resolve_tts_provider("af_heart", "auto") == "kokoro"
    assert vg._resolve_tts_provider("en-IN-PrabhatNeural", "auto") == "edge-tts"


# ── voice spec parsing ───────────────────────────────────────────────────

def test_parse_auto():
    assert vg._parse_omnivoice_voice("OmniVoice (Local Free)")["mode"] == "auto"
    assert vg._parse_omnivoice_voice("omni")["mode"] == "auto"


def test_parse_design():
    spec = vg._parse_omnivoice_voice("omni:design:female, low pitch, indian accent")
    assert spec["mode"] == "design"
    assert spec["instruct"] == "female, low pitch, indian accent"


def test_parse_design_empty_falls_back_to_auto():
    assert vg._parse_omnivoice_voice("omni:design:")["mode"] == "auto"


def test_parse_clone():
    spec = vg._parse_omnivoice_voice("omni:clone:C:/voices/me.wav")
    assert spec["mode"] == "clone"
    assert spec["ref_audio"] == "C:/voices/me.wav"
    assert spec["ref_text"] is None


def test_parse_clone_with_ref_text():
    spec = vg._parse_omnivoice_voice("omni:clone:C:/v/me.wav|hello this is me")
    assert spec["mode"] == "clone"
    assert spec["ref_audio"] == "C:/v/me.wav"
    assert spec["ref_text"] == "hello this is me"


def test_parse_env_ref_audio(monkeypatch):
    monkeypatch.setenv("OMNIVOICE_REF_AUDIO", "/tmp/voice.wav")
    spec = vg._parse_omnivoice_voice("omni")
    assert spec["mode"] == "clone"
    assert spec["ref_audio"] == "/tmp/voice.wav"


def test_parse_bare_existing_wav_is_clone(tmp_path):
    wav = tmp_path / "ref.wav"
    wav.write_bytes(b"RIFF....")
    spec = vg._parse_omnivoice_voice(str(wav))
    assert spec["mode"] == "clone"
    assert spec["ref_audio"] == str(wav)


# ── availability probe ───────────────────────────────────────────────────

def test_generate_raises_helpful_error_when_not_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(vg, "_omnivoice_available", lambda: False)
    with pytest.raises(RuntimeError, match="install_local"):
        vg._generate_audio_omnivoice("hi", str(tmp_path / "o.mp3"))


def test_generate_raises_when_clone_ref_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(vg, "_omnivoice_available", lambda: True)
    with pytest.raises(RuntimeError, match="not found"):
        vg._generate_audio_omnivoice("hi", str(tmp_path / "o.mp3"),
                                     voice="omni:clone:/nope/missing.wav")


# ── worker subprocess contract (faked) ───────────────────────────────────

class _Proc:
    def __init__(self, returncode=0, stderr="", stdout=""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout


def _fake_run_factory(captured, fail=False):
    import wave

    def _fake_run(cmd, **kwargs):
        captured.append(list(cmd))
        if fail:
            return _Proc(returncode=1, stderr="boom")
        if cmd[0] == "ffmpeg":
            # ffmpeg conversion call: last arg is the output mp3.
            with open(cmd[-1], "wb") as fh:
                fh.write(b"ID3" + b"\x00" * 2000)
            return _Proc()
        # worker call: find --output and write a tiny wav.
        out = cmd[cmd.index("--output") + 1]
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(b"\x00\x00" * 24000)  # 1s of silence
        return _Proc()
    return _fake_run


def _patch_subprocess(monkeypatch, captured, fail=False):
    import subprocess
    monkeypatch.setattr(vg, "_omnivoice_available", lambda: True)
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(captured, fail=fail))


def test_worker_cmd_auto_voice(monkeypatch, tmp_path):
    import subprocess  # noqa: F401  (patched below via vg's import)
    captured = []
    _patch_subprocess(monkeypatch, captured)
    out = str(tmp_path / "n.mp3")
    audio, _ = vg._generate_audio_omnivoice("Hello world", out, voice="omni")
    assert audio == out and os.path.getsize(out) > 1024
    worker_cmd = captured[0]
    assert "--text-file" in worker_cmd and "--output" in worker_cmd
    assert worker_cmd[worker_cmd.index("--model") + 1] == "k2-fsa/OmniVoice"
    assert "--ref_audio" not in worker_cmd and "--instruct" not in worker_cmd
    # mp3 requested -> ffmpeg conversion ran as the second call.
    assert captured[1][0] == "ffmpeg" and captured[1][-1] == out


def test_worker_cmd_design_and_clone(monkeypatch, tmp_path):
    captured = []
    _patch_subprocess(monkeypatch, captured)
    ref = tmp_path / "me.wav"
    ref.write_bytes(b"RIFF....")
    out = str(tmp_path / "n.wav")
    vg._generate_audio_omnivoice("Hi", out, voice=f"omni:clone:{ref}|hello",
                                 speed=1.2, language="Hindi")
    cmd = captured[0]
    assert cmd[cmd.index("--ref_audio") + 1] == str(ref)
    assert cmd[cmd.index("--ref_text") + 1] == "hello"
    assert cmd[cmd.index("--speed") + 1] == "1.2"
    assert cmd[cmd.index("--language") + 1] == "Hindi"
    # wav output -> plain copy, no ffmpeg call.
    assert len(captured) == 1
    assert os.path.getsize(out) > 1024

    captured.clear()
    vg._generate_audio_omnivoice("Hi", out, voice="omni:design:male, british accent")
    cmd = captured[0]
    assert cmd[cmd.index("--instruct") + 1] == "male, british accent"


def test_worker_failure_raises(monkeypatch, tmp_path):
    captured = []
    _patch_subprocess(monkeypatch, captured, fail=True)
    with pytest.raises(RuntimeError, match="worker failed"):
        vg._generate_audio_omnivoice("Hi", str(tmp_path / "n.mp3"), voice="omni")


# ── generate_audio fallback contract ─────────────────────────────────────

def test_generate_audio_omni_failure_falls_back_to_edge(monkeypatch, tmp_path):
    async def _fake_edge(text, output_path, voice):
        open(output_path, "wb").write(b"edge-audio")
        return output_path, None

    monkeypatch.setattr(vg, "_generate_audio_async", _fake_edge)
    monkeypatch.setattr(vg, "_generate_audio_omnivoice",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("nope")))
    out = str(tmp_path / "a.mp3")
    audio_path, _ = vg.generate_audio("Hello", out, voice="omni", provider="omnivoice")
    assert audio_path == out
    assert os.path.exists(out)


# ── chunking ─────────────────────────────────────────────────────────────

def test_split_chunks_basic():
    chunks = split_text_chunks("Hello world. This is a test.", max_chars=600)
    assert chunks == ["Hello world. This is a test."]


def test_split_chunks_respects_limit():
    text = " ".join(f"Sentence number {i} here." for i in range(50))
    chunks = split_text_chunks(text, max_chars=120)
    assert all(len(c) <= 120 for c in chunks)
    assert " ".join(chunks).replace("  ", " ") == " ".join(text.split())


def test_split_chunks_hard_splits_long_sentence():
    chunks = split_text_chunks("a" * 1500, max_chars=600)
    assert all(len(c) <= 600 for c in chunks)
    assert sum(len(c) for c in chunks) == 1500


def test_split_chunks_empty():
    assert split_text_chunks("   ") == []


# ── connection test ──────────────────────────────────────────────────────

def test_tts_omni_installed(monkeypatch):
    import importlib.util
    from src.backend import connection_tests as ct
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    res = ct.test_tts("", "", voice="OmniVoice (Local Free)")
    assert res["ok"] is True and res["provider"] == "OmniVoice"


def test_tts_omni_missing(monkeypatch):
    import importlib.util
    import shutil
    from src.backend import connection_tests as ct
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    res = ct.test_tts("omnivoice", "")
    assert res["ok"] is False
    assert "install_local" in res["message"]
