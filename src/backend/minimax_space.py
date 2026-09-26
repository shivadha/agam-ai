"""
minimax_space.py — MiniMax H3 video generation with NO API key.

Uses the free community/official HuggingFace Spaces that host MiniMax-H3
(the Hailuo 3.0 video model) with free GPU quota — no API key, no signup
key, just the public Gradio API:

  * multimodalart/minimax-h3            (community, most-liked)
  * MiniMaxAI/MiniMax-H3-Turbo-Lora     (official MiniMaxAI org space)

Space UIs drift, so instead of hardcoding parameter order this module
discovers the right endpoint at runtime: it reads the space's API info,
picks the endpoint that takes a text prompt (+ optional image) and
returns a video, then calls it. If the first space is paused/queued-out,
it tries the next one.

Requires: pip install gradio_client   (pure HTTP client, free)

Note: HF ZeroGPU spaces may ask for a free HF login when GPU quota is
exhausted for anonymous users — that is a site-side limit, not an API key.
"""
from __future__ import annotations

import os
import shutil
import urllib.request

# Verified live 2026-09-26. Order: community workhorse first, official second.
SPACES = [
    "multimodalart/minimax-h3",
    "MiniMaxAI/MiniMax-H3-Turbo-Lora",
]

_GENERATE_CANDIDATES = ("/generate", "/predict", "/run", "/infer")


def _client_for(space_id: str):
    try:
        from gradio_client import Client
    except ImportError as e:
        raise RuntimeError(
            "gradio_client is not installed. Install it once with:\n"
            "    pip install gradio_client\n"
            "then retry — no API key is needed for public Spaces."
        ) from e
    return Client(space_id)


def _find_video_endpoint(client) -> str:
    """Pick the named endpoint that takes text (+ optional image) and
    returns a video. Returns the api_name (e.g. '/generate')."""
    try:
        info = client.get_api_info() or {}
    except Exception:
        info = {}
    named = info.get("named_endpoints") or {}
    for api_name, ep in named.items():
        params = ep.get("parameters") or []
        returns = ep.get("returns") or []
        ptypes = " ".join(
            str(p.get("type", "")) + " " + str(p.get("python_type", {}).get("type", ""))
            for p in params).lower()
        rtypes = " ".join(
            str(r.get("type", "")) + " " + str(r.get("python_type", {}).get("type", ""))
            for r in returns).lower()
        has_text = "string" in ptypes or "str" in ptypes
        has_video = "video" in rtypes
        if has_text and has_video:
            return api_name
    # Fallback: blind candidates, most Gradio video demos use /generate.
    for cand in _GENERATE_CANDIDATES:
        if cand in named:
            return cand
    raise RuntimeError("no text-to-video endpoint found on this Space")


def _build_kwargs(client, api_name: str, prompt: str, image_path: str | None) -> dict:
    """Map prompt/image onto the endpoint's parameter names."""
    try:
        info = client.get_api_info() or {}
        params = (info.get("named_endpoints") or {}).get(api_name, {}).get("parameters") or []
    except Exception:
        params = []
    kwargs: dict = {}
    text_set = False
    for p in params:
        name = p.get("parameter_name") or p.get("name") or ""
        ptype = (str(p.get("type", "")) + " " +
                 str(p.get("python_type", {}).get("type", ""))).lower()
        lname = name.lower()
        if not text_set and ("string" in ptype or "str" in ptype) \
                and any(k in lname for k in ("prompt", "text", "input", "query")):
            kwargs[name] = prompt
            text_set = True
        elif image_path and "image" in ptype and "image" in lname:
            kwargs[name] = image_path
        elif "bool" in ptype and "upsample" in lname:
            kwargs[name] = True  # prompt upsampling improves H3 output
    if not text_set:
        # Last resort: first string parameter gets the prompt.
        for p in params:
            name = p.get("parameter_name") or p.get("name") or ""
            ptype = (str(p.get("type", "")) + " " +
                     str(p.get("python_type", {}).get("type", ""))).lower()
            if "string" in ptype or "str" in ptype:
                kwargs[name] = prompt
                break
    return kwargs


def _extract_video_path(result) -> str | None:
    """gradio_client returns file outputs as local paths or dicts."""
    cands = []
    if isinstance(result, (list, tuple)):
        cands = list(result)
    else:
        cands = [result]
    for c in cands:
        if isinstance(c, dict):
            p = c.get("path") or c.get("name")
            if p and os.path.exists(p):
                return p
            url = c.get("url")
            if url:
                return url  # handled as URL below
        elif isinstance(c, str):
            if os.path.exists(c):
                return c
            if c.startswith("http"):
                return c
    return None


def _save_result(src: str, output_path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    if os.path.exists(src):
        if os.path.abspath(src) != os.path.abspath(output_path):
            shutil.copyfile(src, output_path)
        return os.path.abspath(output_path)
    if src.startswith("http"):  # remote URL — download it
        urllib.request.urlretrieve(src, output_path)
        return os.path.abspath(output_path)
    raise RuntimeError(f"unusable video result: {src!r}")


def generate_minimax_h3_space(image_path: str | None, prompt: str,
                              output_path: str, duration: float = 4.0,
                              space_id: str | None = None,
                              timeout: int = 1800) -> str:
    """Generate a video with MiniMax-H3 via a free HF Space. No API key.

    Returns the absolute output_path of the downloaded mp4.
    Raises RuntimeError when every space failed (with the last error).
    """
    prompt = (prompt or "").strip() or "cinematic slow push-in, photorealistic"
    spaces = [space_id] if space_id else list(SPACES)
    last_err: Exception | None = None
    for sid in spaces:
        try:
            print(f"[minimax_space] Trying H3 Space '{sid}' (no API key)...")
            client = _client_for(sid)
            api_name = _find_video_endpoint(client)
            kwargs = _build_kwargs(client, api_name, prompt, image_path)
            print(f"[minimax_space] endpoint={api_name} params={sorted(kwargs)}")
            result = client.predict(api_name=api_name, **kwargs)
            src = _extract_video_path(result)
            if not src:
                raise RuntimeError(f"endpoint returned no video: {result!r:.200}")
            out = _save_result(src, output_path)
            if os.path.getsize(out) < 1000:
                raise RuntimeError("downloaded video is suspiciously small")
            print(f"[minimax_space] SUCCESS via '{sid}': {os.path.basename(out)}")
            return out
        except Exception as e:
            last_err = e
            print(f"[minimax_space] Space '{sid}' failed: {e}")
            continue
    raise RuntimeError(f"All MiniMax-H3 Spaces failed. Last error: {last_err}")
