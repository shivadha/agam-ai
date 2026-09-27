"""Tests for the Fish Audio TTS provider (src/backend/voice_gen.py).

User requirement (2026-09-27): use Fish Audio's free s2.1-pro-free tier as a
TTS option. The free tier is promotional — ANY failure (no key, 402, network)
must fall back to Edge-TTS so a render never dies on it.
"""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from src.backend import voice_gen as vg


class _Resp:
    def __init__(self, status_code=200, content=b"", headers=None, text=""):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.text = text


def _fake_post_factory(captured, resp):
    def _fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return resp
    return _fake_post


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("FISH_AUDIO_KEY", raising=False)
    monkeypatch.delenv("FISH_API_KEY", raising=False)
    monkeypatch.delenv("FISH_AUDIO_MODEL", raising=False)
    yield


# ── provider resolution ─────────────────────────────────────────────────

def test_resolver_fish_voice_label():
    assert vg._resolve_tts_provider("Fish Audio S2.1 (Free API)", "auto") == "fish"


def test_resolver_fish_provider_flag():
    assert vg._resolve_tts_provider("af_heart", "fish") == "fish"


def test_resolver_fish_reference_id_syntax():
    assert vg._resolve_tts_provider("fish:abc123XYZ-_", "auto") == "fish"


def test_resolver_existing_voices_unchanged():
    assert vg._resolve_tts_provider("en-IN-PrabhatNeural", "auto") == "edge-tts"
    assert vg._resolve_tts_provider("af_heart", "auto") == "kokoro"
    assert vg._resolve_tts_provider("elevenlabs-xyz", "auto") == "elevenlabs"


# ── key lookup ──────────────────────────────────────────────────────────

def test_fish_api_key_canonical_and_alias(monkeypatch):
    monkeypatch.setenv("FISH_API_KEY", "alias-key")
    assert vg._fish_api_key() == "alias-key"
    monkeypatch.setenv("FISH_AUDIO_KEY", "canon-key")
    assert vg._fish_api_key() == "canon-key"  # canonical wins


# ── _generate_audio_fish ────────────────────────────────────────────────

def test_fish_success_writes_mp3(monkeypatch, tmp_path):
    captured = {}
    fake_audio = b"ID3" + b"\x00" * 5000
    monkeypatch.setattr("requests.post",
                        _fake_post_factory(captured, _Resp(200, fake_audio,
                                                          {"Content-Type": "audio/mpeg"})))
    out = str(tmp_path / "narr.mp3")
    audio_path, sub_path = vg._generate_audio_fish("Hello world", out, voice="fish",
                                                   api_key="test-key")
    assert audio_path == out
    assert os.path.getsize(out) == len(fake_audio)
    # Model rides in the HTTP header, not the body
    assert captured["headers"]["model"] == "s2.1-pro-free"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert "reference_id" not in captured["json"]
    assert captured["json"]["format"] == "mp3"
    assert sub_path is None  # raw bytes — no word timings; whisper handles it


def test_fish_reference_id_passed_through(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr("requests.post",
                        _fake_post_factory(captured, _Resp(200, b"ID3" + b"\x00" * 5000,
                                                          {"Content-Type": "audio/mpeg"})))
    out = str(tmp_path / "narr.mp3")
    vg._generate_audio_fish("Hi", out, voice="fish:myVoice-01_abc", api_key="k")
    assert captured["json"]["reference_id"] == "myVoice-01_abc"


def test_fish_model_env_override(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setenv("FISH_AUDIO_MODEL", "s2.1-pro")
    monkeypatch.setattr("requests.post",
                        _fake_post_factory(captured, _Resp(200, b"ID3" + b"\x00" * 5000,
                                                          {"Content-Type": "audio/mpeg"})))
    vg._generate_audio_fish("Hi", str(tmp_path / "n.mp3"), api_key="k")
    assert captured["headers"]["model"] == "s2.1-pro"


def test_fish_402_raises_with_credit_guidance(monkeypatch, tmp_path):
    monkeypatch.setattr("requests.post",
                        _fake_post_factory({}, _Resp(402, b'{"message":"no credit"}',
                                                    {"Content-Type": "application/json"},
                                                    '{"message":"no credit"}')))
    with pytest.raises(RuntimeError, match="402"):
        vg._generate_audio_fish("Hi", str(tmp_path / "n.mp3"), api_key="k")


def test_fish_json_error_payload_raises(monkeypatch, tmp_path):
    monkeypatch.setattr("requests.post",
                        _fake_post_factory({}, _Resp(200, b'{"error":"bad"}',
                                                    {"Content-Type": "application/json"},
                                                    '{"error":"bad"}')))
    with pytest.raises(RuntimeError, match="error payload"):
        vg._generate_audio_fish("Hi", str(tmp_path / "n.mp3"), api_key="k")


def test_fish_unauthorized_raises(monkeypatch, tmp_path):
    monkeypatch.setattr("requests.post",
                        _fake_post_factory({}, _Resp(401, b"nope", {}, "nope")))
    with pytest.raises(RuntimeError, match="rejected"):
        vg._generate_audio_fish("Hi", str(tmp_path / "n.mp3"), api_key="bad")


def test_fish_no_key_raises(monkeypatch, tmp_path):
    with pytest.raises(RuntimeError, match="FISH_AUDIO_KEY"):
        vg._generate_audio_fish("Hi", str(tmp_path / "n.mp3"), api_key="")


# ── generate_audio fallback contract ────────────────────────────────────

def test_generate_audio_fish_no_key_falls_back_to_edge(monkeypatch, tmp_path):
    """Fish selected but no key -> Edge-TTS path, never a crash."""
    calls = {}

    async def _fake_edge(text, output_path, voice):
        calls["voice"] = voice
        open(output_path, "wb").write(b"edge-audio")
        return output_path, None

    monkeypatch.setattr(vg, "_generate_audio_async", _fake_edge)
    out = str(tmp_path / "a.mp3")
    audio_path, _ = vg.generate_audio("Hello", out, voice="fish", provider="fish")
    assert audio_path == out
    assert os.path.exists(out)


def test_generate_audio_fish_failure_falls_back_to_edge(monkeypatch, tmp_path):
    """Fish 402 mid-render -> Edge-TTS takes over, render survives."""
    def _boom(*a, **k):
        raise RuntimeError("Fish Audio: insufficient API credit (HTTP 402).")

    calls = {}

    async def _fake_edge(text, output_path, voice):
        calls["used"] = True
        open(output_path, "wb").write(b"edge-audio")
        return output_path, None

    monkeypatch.setattr(vg, "_generate_audio_fish", _boom)
    monkeypatch.setattr(vg, "_generate_audio_async", _fake_edge)
    monkeypatch.setenv("FISH_AUDIO_KEY", "k")
    out = str(tmp_path / "a.mp3")
    audio_path, _ = vg.generate_audio("Hello", out, voice="fish", provider="fish")
    assert audio_path == out
    assert calls.get("used") is True


def test_generate_audio_fish_success_uses_fish(monkeypatch, tmp_path):
    def _ok(text, output_path, voice="fish", api_key=None):
        open(output_path, "wb").write(b"ID3" + b"\x00" * 5000)
        return output_path, None

    monkeypatch.setattr(vg, "_generate_audio_fish", _ok)
    monkeypatch.setenv("FISH_AUDIO_KEY", "k")
    out = str(tmp_path / "a.mp3")
    audio_path, _ = vg.generate_audio("Hello", out, voice="fish", provider="fish")
    assert audio_path == out
    assert os.path.getsize(out) > 1024
