"""
ComfyUI local-model scanner — auto-detect the best image-to-video model.

Every run scans the user's local ComfyUI server and picks whichever installed
model gives the best result, instead of assuming one is present:

* Queries BOTH /models/checkpoints AND /models/diffusion_models.
  (Newer ComfyUI keeps DiT video UNETs such as LTX-Video and Wan in
  diffusion_models/ — a checkpoints-only scan never sees them. This was the
  real reason LTX sat unused on machines that had it installed.)
* Ranks by native clip length (longest first): LTX-Video (~10s) > Wan (~5s)
  > SVD (~2-3.6s), because the pipeline needs ~9s shots.
* Soft-checks VRAM fit from /system_stats purely as an advisory label — it
  warns, never gates. A rough heuristic must not overrule a model the user
  deliberately installed (that is how LTX sat unused on machines that had it).
* Results are cached briefly (120s) so every node doesn't re-scan.

Free-only: no network calls leave the machine; everything is localhost.
"""

import json
import os
import time
import urllib.request

COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")

# Native capability per model family: (max_frames, fps, label)
MODEL_SPECS = {
    "ltx": {"max_frames": 257, "fps": 24, "label": "LTX-Video",
            "why": "up to ~10s native AI motion per shot"},
    "wan": {"max_frames": 81, "fps": 16, "label": "Wan I2V",
            "why": "up to ~5s native AI motion per shot"},
    "svd": {"max_frames": 25, "fps": 7, "label": "SVD",
            "why": "up to ~3.6s native AI motion per shot"},
    # LTX-2 (Lightricks, 19B): the first open-source video+AUDIO combo model.
    # Detected and shown, but never auto-picked — it needs 20GB+ VRAM and a
    # completely different ComfyUI node graph (audio VAE, LTX-2 sampler nodes)
    # than the LTX-Video 2B workflow this pipeline submits. Auto-submitting
    # our LTX workflow to an LTX-2 checkpoint would be a guaranteed failure,
    # which is workflow incompatibility — not the advisory VRAM heuristic.
    "ltx2": {"max_frames": 257, "fps": 24, "label": "LTX-2 (19B video+audio)",
             "why": "video + native audio in one pass — needs its own ComfyUI workflow (not supported yet)"},
}

_SCAN_CACHE = {"at": 0.0, "base_url": None, "result": None}
SCAN_TTL_S = 120


def classify_i2v(name):
    """Return 'ltx' | 'ltx2' | 'wan' | 'svd' | None for a ComfyUI model filename."""
    ml = (name or "").lower()
    # LTX-2 FIRST: "ltx-2"/"ltxv2"/"ltxav" all contain "ltx" — without this
    # check a 19B LTX-2 checkpoint would misclassify as LTX-Video 2B and get
    # auto-picked, then fail (wrong workflow + 20GB+ VRAM need).
    if "ltx-2" in ml or "ltxv2" in ml or "ltxav" in ml or "ltx2" in ml:
        return "ltx2"
    if "wan" in ml and ("i2v" in ml or "image" in ml or "img2vid" in ml):
        return "wan"
    if "ltx" in ml:
        return "ltx"
    if "svd" in ml:
        return "svd"
    return None


def rank_i2v_models(names):
    """Pick the best i2v model: LTX > Wan > SVD (longest native clip first).

    LTX-2 is deliberately excluded from the auto-pick even when installed:
    our ComfyUI workflow targets LTX-Video 2B nodes and cannot drive LTX-2's
    video+audio graph. (The advisory-VRAM rule is untouched — this is about
    submitting a compatible workflow, not a VRAM heuristic.)

    Returns (kind, checkpoint_name); (None, None) when nothing drivable matches.
    """
    best = {}
    for m in (names if isinstance(names, list) else []):
        kind = classify_i2v(m)
        if kind and kind != "ltx2" and kind not in best:
            best[kind] = m
    for kind in ("ltx", "wan", "svd"):
        if kind in best:
            return kind, best[kind]
    return None, None


def estimate_vram_gb(name, kind):
    """Rough VRAM estimate (GB, fp16-ish) parsed from the model filename.

    Heuristic only — used for a soft fit check, never a hard gate.
    Returns None when it can't be estimated.
    """
    ml = (name or "").lower()
    # Quantized GGUFs state it outright
    if "gguf" in ml:
        if "q4" in ml:
            return 5.0
        if "q6" in ml or "q5" in ml:
            return 8.0
        if "q8" in ml:
            return 10.0
    # Parameter count hints
    import re
    m = re.search(r"(\d+(?:\.\d+)?)\s*b", ml)
    if m:
        params = float(m.group(1))
        # ~2 bytes/param fp16 + VAE/text-encoder overhead; distilled a bit less
        est = params * 2.0 + 2.0
        if "distill" in ml:
            est *= 0.85
        return round(est, 1)
    # Family fallbacks
    if kind == "svd":
        return 5.0
    if kind == "ltx":
        return 12.0
    if kind == "ltx2":
        return 40.0  # 19B dev bf16; distilled/fp8 repacks run ~20-35GB
    if kind == "wan":
        return 5.0 if ("1.3b" in ml or "1_3b" in ml or "t2v" in ml) else 14.0
    return None


def _get_json(base_url, path, timeout=6):
    req = urllib.request.Request(f"{base_url}{path}",
                                 headers={"User-Agent": "PulseForge/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def scan_comfyui(base_url=None, refresh=False):
    """Scan the local ComfyUI server and recommend the best i2v model.

    Returns a JSON-serializable dict:
      {"reachable": bool, "vram_total_gb": float|None, "vram_free_gb": ...,
       "candidates": [{"kind","name","source","max_frames","fps",
                       "est_vram_gb","fits_vram","native_seconds"}, ...],
       "recommended": {"kind","name",...} | None,
       "reason": str, "scanned_at": epoch}
    """
    base_url = base_url or COMFYUI_URL
    now = time.time()
    cached = _SCAN_CACHE
    if (not refresh and cached["result"] is not None
            and cached["base_url"] == base_url
            and now - cached["at"] < SCAN_TTL_S):
        return cached["result"]

    result = {
        "reachable": False,
        "vram_total_gb": None,
        "vram_free_gb": None,
        "candidates": [],
        "recommended": None,
        "reason": "ComfyUI is not reachable.",
        "scanned_at": now,
    }
    try:
        stats = _get_json(base_url, "/system_stats", timeout=4)
    except Exception as e:
        result["reason"] = f"ComfyUI not reachable at {base_url}: {e}"
        cached.update(at=now, base_url=base_url, result=result)
        return result

    result["reachable"] = True
    devices = stats.get("devices") or []
    sys_info = stats.get("system") or {}
    if devices and isinstance(devices, list):
        dev = devices[0] or {}
        vram_total = dev.get("vram_total") or sys_info.get("vram_total")
        vram_free = dev.get("vram_free") or sys_info.get("vram_free")
    else:
        vram_total = sys_info.get("vram_total")
        vram_free = sys_info.get("vram_free")
    if vram_total:
        result["vram_total_gb"] = round(vram_total / 1e9, 1)
    if vram_free:
        result["vram_free_gb"] = round(vram_free / 1e9, 1)

    # Merge both model locations (newer ComfyUI: DiT UNETs live in diffusion_models/)
    seen = {}
    for endpoint in ("/models/checkpoints", "/models/diffusion_models"):
        try:
            names = _get_json(base_url, endpoint, timeout=6)
        except Exception:
            continue
        for n in (names if isinstance(names, list) else []):
            kind = classify_i2v(n)
            if kind and n not in seen:
                seen[n] = (kind, endpoint)

    vram_total_gb = result["vram_total_gb"]
    candidates = []
    for name, (kind, endpoint) in seen.items():
        spec = MODEL_SPECS[kind]
        est = estimate_vram_gb(name, kind)
        fits = None
        if est is not None and vram_total_gb:
            fits = est <= vram_total_gb * 1.15  # 15% headroom for offload wiggle
        candidates.append({
            "kind": kind,
            "name": name,
            "source": endpoint.rsplit("/", 1)[-1],
            "max_frames": spec["max_frames"],
            "fps": spec["fps"],
            "native_seconds": round(spec["max_frames"] / spec["fps"], 1),
            "est_vram_gb": est,
            "fits_vram": fits,
        })
    # Rank: longest native clip first; among those, prefer VRAM fit.
    # LTX-2 always sorts last: detected for visibility, never recommended
    # (incompatible workflow — see rank_i2v_models).
    order = {"ltx": 0, "wan": 1, "svd": 2, "ltx2": 3}
    candidates.sort(key=lambda c: (order[c["kind"]],
                                   0 if c["fits_vram"] is not False else 1))
    result["candidates"] = candidates

    if candidates:
        # The most capable installed model wins — it was installed deliberately.
        # VRAM fit is advisory only: warn, never gate. (ComfyUI can offload or
        # run quantized builds, and the pipeline falls back automatically if
        # a model OOMs.) Gating on a rough heuristic is exactly how LTX sat
        # unused on machines that had it.
        # LTX-2 is never the recommendation (incompatible workflow), but it is
        # still listed in candidates so the UI shows it was detected.
        drivable = [c for c in candidates if c["kind"] != "ltx2"]
        ltx2_names = [c["name"] for c in candidates if c["kind"] == "ltx2"]
        rec = drivable[0] if drivable else None
        ltx2_note = ""
        if ltx2_names:
            ltx2_note = (f" LTX-2 detected ({', '.join(ltx2_names)}) but not "
                         f"auto-selected: it needs 20GB+ VRAM and its own "
                         f"ComfyUI workflow (video+audio graph) — AGAM's LTX "
                         f"workflow targets LTX-Video 2B.")
        if rec is None:
            result["reason"] = ("No drivable image-to-video model found."
                                + ltx2_note)
        else:
            spec = MODEL_SPECS[rec["kind"]]
            if rec["fits_vram"] is False:
                result["reason"] = (
                    f"{spec['label']} ({rec['name']}) is the most capable model "
                    f"installed ({spec['why']}), but it may exceed your "
                    f"{vram_total_gb}GB VRAM — ComfyUI will try with offloading; "
                    f"if it OOMs, the pipeline falls back automatically. "
                    f"Override anytime in the node's AI Video Provider dropdown."
                    + ltx2_note)
            else:
                result["reason"] = (
                    f"{spec['label']} ({rec['name']}) — {spec['why']}, "
                    f"fits your {vram_total_gb or '?'}GB VRAM."
                    + ltx2_note)
            result["recommended"] = rec
    else:
        result["reason"] = ("ComfyUI is online but no image-to-video model "
                            "(LTX / Wan / SVD) was found in checkpoints or "
                            "diffusion_models.")

    cached.update(at=now, base_url=base_url, result=result)
    return result


def clear_scan_cache():
    _SCAN_CACHE.update(at=0.0, base_url=None, result=None)
