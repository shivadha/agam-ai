"""Tests for the ComfyUI local-model auto-scanner (src/backend/comfyui_scan.py).

User requirement (2026-09-27): whenever the pipeline runs on the local
machine it must scan ComfyUI for installed video models and auto-pick the
one that gives the best result — visible in the UI with a manual override.
"""
import io
import json
import os
import sys
import urllib.request

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from src.backend import comfyui_scan as cs
from src.backend import video_gen_ai as vg


@pytest.fixture(autouse=True)
def _clear_cache():
    cs.clear_scan_cache()
    yield
    cs.clear_scan_cache()


# ── classification ──────────────────────────────────────────────────────

def test_classify_i2v():
    assert cs.classify_i2v("ltxv-13b-0.9.7-distilled.safetensors") == "ltx"
    assert cs.classify_i2v("LTX-Video-13b.safetensors") == "ltx"
    assert cs.classify_i2v("wan2.1-i2v-14b-480p.safetensors") == "wan"
    assert cs.classify_i2v("Wan2.1_I2V_1.3B_480p.safetensors") == "wan"
    assert cs.classify_i2v("svd_xt_1_1.safetensors") == "svd"
    assert cs.classify_i2v("v1-5-pruned-emaonly.safetensors") is None
    assert cs.classify_i2v("") is None


def test_rank_prefers_ltx_then_wan_then_svd():
    names = ["svd_xt.safetensors", "wan2.1-i2v-14b.safetensors",
             "ltxv-13b.safetensors"]
    assert cs.rank_i2v_models(names) == ("ltx", "ltxv-13b.safetensors")
    assert cs.rank_i2v_models(["svd_xt.safetensors",
                               "wan2.1-i2v-14b.safetensors"])[0] == "wan"
    assert cs.rank_i2v_models(["svd_xt.safetensors"])[0] == "svd"
    assert cs.rank_i2v_models(["v1-5.safetensors"]) == (None, None)
    assert cs.rank_i2v_models([]) == (None, None)


def test_video_gen_ai_alias_still_works():
    # backwards-compat alias used by the pipeline + older tests
    assert vg._pick_comfyui_model(["svd.safetensors",
                                   "ltxv-13b.safetensors"])[0] == "ltx"


# ── VRAM estimates ──────────────────────────────────────────────────────

def test_estimate_vram_gb():
    assert cs.estimate_vram_gb("wan2.1-i2v-1.3b-480p.safetensors", "wan") == pytest.approx(4.6)
    assert cs.estimate_vram_gb("svd_xt.safetensors", "svd") == 5.0
    assert cs.estimate_vram_gb("ltx-video-2b-v0.9.5.safetensors", "ltx") == pytest.approx(6.0)
    assert cs.estimate_vram_gb("ltxv-13b-Q4_K_M.gguf", "ltx") == 5.0
    assert cs.estimate_vram_gb("mystery.safetensors", None) is None


# ── full scan with mocked ComfyUI ───────────────────────────────────────

class _FakeResp:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()
    def read(self):
        return self._payload
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def _mock_comfyui(monkeypatch, vram_total=6 * 10**9,
                  checkpoints=("svd_xt_1_1.safetensors",),
                  diffusion=("ltxv-13b-0.9.7-distilled.safetensors",
                             "wan2.1-i2v-14b-480p.safetensors")):
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        url = req.full_url if hasattr(req, "full_url") else req
        if url.endswith("/system_stats"):
            return _FakeResp({"system": {"vram_total": vram_total,
                                         "vram_free": vram_total // 2}})
        if url.endswith("/models/checkpoints"):
            return _FakeResp(list(checkpoints))
        if url.endswith("/models/diffusion_models"):
            return _FakeResp(list(diffusion))
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return calls


def test_scan_finds_ltx_in_diffusion_models(monkeypatch):
    """The user's exact scenario: SVD in checkpoints, LTX in diffusion_models
    (newer ComfyUI layout). The old checkpoints-only scan never saw LTX."""
    _mock_comfyui(monkeypatch)
    scan = cs.scan_comfyui("http://127.0.0.1:8188", refresh=True)
    assert scan["reachable"] is True
    assert scan["vram_total_gb"] == 6.0
    kinds = {c["kind"] for c in scan["candidates"]}
    assert kinds == {"ltx", "wan", "svd"}
    # LTX is recommended despite the 6GB card: most capable installed model,
    # with an honest VRAM warning in the reason.
    rec = scan["recommended"]
    assert rec["kind"] == "ltx"
    assert rec["name"] == "ltxv-13b-0.9.7-distilled.safetensors"
    assert rec["fits_vram"] is False
    assert "VRAM" in scan["reason"] or "vram" in scan["reason"].lower()
    # SVD (the only one that fits 6GB) is still listed as fallback
    svd = next(c for c in scan["candidates"] if c["kind"] == "svd")
    assert svd["fits_vram"] is True
    assert svd["source"] == "checkpoints"
    assert rec["source"] == "diffusion_models"


def test_scan_prefers_vram_fit_among_equals(monkeypatch):
    # Two SVDs — nothing smarter available; the fitting one ranks first
    _mock_comfyui(monkeypatch, checkpoints=("svd.safetensors",), diffusion=())
    scan = cs.scan_comfyui(refresh=True)
    assert scan["recommended"]["kind"] == "svd"


def test_scan_offline(monkeypatch):
    def boom(req, timeout=None):
        raise ConnectionError("refused")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    scan = cs.scan_comfyui(refresh=True)
    assert scan["reachable"] is False
    assert scan["recommended"] is None


def test_scan_no_video_models(monkeypatch):
    _mock_comfyui(monkeypatch, checkpoints=("v1-5.safetensors",), diffusion=())
    scan = cs.scan_comfyui(refresh=True)
    assert scan["reachable"] is True
    assert scan["candidates"] == []
    assert scan["recommended"] is None
    assert "no image-to-video model" in scan["reason"]


def test_scan_cache(monkeypatch):
    calls = _mock_comfyui(monkeypatch)
    cs.scan_comfyui(refresh=True)
    first = calls["n"]
    assert first == 3  # system_stats + checkpoints + diffusion_models
    cs.scan_comfyui()  # cached — no new HTTP
    assert calls["n"] == first
    cs.scan_comfyui(refresh=True)
    assert calls["n"] == first + 3


# ── provider-string override parsing ────────────────────────────────────

def test_parse_comfyui_force():
    p = vg._parse_comfyui_force
    assert p("ComfyUI (Auto-Scan Best Model) [Free GPU]") is None
    assert p("ComfyUI (Local Wan 2.1 / LTX) [Free GPU]") is None  # legacy -> auto
    assert p("ComfyUI (LTX-Video) [Free GPU]") == "ltx"
    assert p("ComfyUI (Wan 2.1) [Free GPU]") == "wan"
    assert p("ComfyUI (SVD) [Free GPU]") == "svd"
    assert p("MiniMax-H3 (HF Space) [Free, No Key]") is None
    assert p("") is None
