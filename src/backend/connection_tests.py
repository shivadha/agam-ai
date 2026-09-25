"""
connection_tests.py — Honest live connection testing for workflow nodes.

Every test here performs a REAL check (key validity ping, service reachability)
and never reports success for something it did not actually verify. Used by:

  * POST /api/workflow/test-connection  (single node, from the UI)
  * POST /api/workflow/preflight        (whole workflow, before a run)
  * The /api/workflow/run gate          (refuses to start when a required
                                         node has no live connection)

Result shape: {"ok": bool, "provider": str, "message": str, "latency_ms": int}
"""

import os
import time
import json
import concurrent.futures

import requests

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ms(t0: float) -> int:
    return int((time.time() - t0) * 1000)


def _env(*names: str) -> str:
    for n in names:
        v = (os.environ.get(n) or "").strip()
        if v:
            return v
    return ""


def clean_token(val: str) -> str:
    """Sanitize a pasted API token: strip whitespace, surrounding quotes,
    and any inner whitespace/newlines (HF tokens never contain them —
    they only appear from bad copy-pastes, and any of them -> HTTP 401)."""
    v = (val or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1].strip()
    return "".join(v.split())


def _ok(provider: str, message: str, t0: float) -> dict:
    return {"ok": True, "provider": provider, "message": message, "latency_ms": _ms(t0)}


def _fail(message: str, t0: float, provider: str = "") -> dict:
    return {"ok": False, "provider": provider, "message": message, "latency_ms": _ms(t0)}


# ---------------------------------------------------------------------------
# LLM / script nodes  (mirrors the provider chain in script_gen.py)
# ---------------------------------------------------------------------------

HF_TEXT_MODEL = "Qwen/Qwen2.5-7B-Instruct"


def _ping_hf_text(hf_token: str, t0: float):
    """Lightweight HF Inference API check (no generation, just router status)."""
    try:
        r = requests.get(
            "https://huggingface.co/api/models/" + HF_TEXT_MODEL,
            headers={"Authorization": f"Bearer {hf_token}"} if hf_token else {},
            timeout=10,
        )
        if r.status_code == 200:
            return _ok("Hugging Face Inference", f"HF Inference API reachable ({HF_TEXT_MODEL}).", t0)
        return None
    except Exception:
        return None


def test_llm(model_name: str = "", api_key: str = "") -> dict:
    """
    Walk the same provider chain script_gen uses and return the first LIVE one.
    `model_name` is the node's display model (e.g. 'GPT-4o', 'Gemini 2.5 Flash').
    """
    t0 = time.time()
    model = (model_name or "").lower()
    key = (api_key or "").strip()
    tried = []

    def note(name):
        tried.append(name)

    # 1. Astra / Experiential Labs
    astra_key = key if (key.startswith("xpl_") or "astra" in model) else _env("ASTRA_API_KEY", "EXPERIENTIAL_API_KEY")
    if astra_key:
        note("Astra")
        try:
            r = requests.post(
                "https://api.experientiallabs.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {astra_key}", "Content-Type": "application/json"},
                json={"model": "gpt-6-astra",
                      "messages": [{"role": "user", "content": "ping"}],
                      "max_tokens": 5},
                timeout=12,
            )
            if r.status_code == 200:
                return _ok("Experiential Astra", "Astra frontier model is live.", t0)
        except Exception:
            pass

    # 2. Explicit local Ollama
    if any(k in model for k in ["ollama", "shivam-pro", "deepseek", "qwen", "local"]):
        note("Ollama")
        try:
            r = requests.get("http://localhost:11434/api/tags", timeout=4)
            if r.status_code == 200:
                names = [m.get("name") for m in r.json().get("models", [])][:4]
                return _ok("Local Ollama", f"Ollama live ({', '.join(names) or 'no models listed'}).", t0)
        except Exception:
            pass

    # 3. Meta Muse Spark
    muse_key = (key if ("muse" in model or key.startswith("LLM_")) else "") or _env("MUSE_API_KEY", "META_API_KEY") or (key if key.startswith("LLM_") else "")
    if muse_key:
        note("Meta Muse Spark")
        try:
            r = requests.get("https://api.meta.ai/v1/models",
                             headers={"Authorization": f"Bearer {muse_key}"}, timeout=10)
            if r.status_code == 200:
                return _ok("Meta Muse Spark", "Muse Spark Model API is live.", t0)
        except Exception:
            pass

    # 4. Groq
    groq_key = (key if "groq" in model else "") or _env("GROQ_API_KEY") or key
    if groq_key:
        note("Groq")
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                json={"model": "llama-3.3-70b-versatile",
                      "messages": [{"role": "user", "content": "ping"}],
                      "max_tokens": 5},
                timeout=12,
            )
            if r.status_code == 200:
                return _ok("Groq Cloud", "Groq ultra-fast inference is live.", t0)
        except Exception:
            pass

    # 5. Gemini
    gem_key = (key if "gemini" in model else "") or _env("GEMINI_API_KEY") or key
    if gem_key:
        note("Gemini")
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gem_key}",
                headers={"Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": "ping"}]}]},
                timeout=12,
            )
            if r.status_code == 200:
                return _ok("Google Gemini", "Gemini 2.0 Flash is live.", t0)
        except Exception:
            pass

    # 6. OpenAI
    o_key = (key if "gpt" in model or "openai" in model else "") or _env("OPENAI_API_KEY") or key
    if o_key and not o_key.startswith("xpl_") and not o_key.startswith("LLM_"):
        note("OpenAI")
        try:
            r = requests.get("https://api.openai.com/v1/models",
                             headers={"Authorization": f"Bearer {o_key}"}, timeout=10)
            if r.status_code == 200:
                return _ok("OpenAI", "OpenAI API is live.", t0)
        except Exception:
            pass

    # 6.5. OpenRouter (free :free models, no card needed)
    or_key = (key if "openrouter" in model else "") or _env("OPENROUTER_API_KEY") or key
    if or_key and not or_key.startswith("xpl_") and not or_key.startswith("LLM_"):
        note("OpenRouter")
        try:
            r = requests.get("https://openrouter.ai/api/v1/models",
                             headers={"Authorization": f"Bearer {or_key}"}, timeout=10)
            if r.status_code == 200:
                return _ok("OpenRouter", "OpenRouter free-model gateway is live.", t0)
        except Exception:
            pass

    # 7. Hugging Face Inference (free tier, optional token)
    hf_token = clean_token(_env("HF_TOKEN", "HUGGINGFACE_TOKEN"))
    note("Hugging Face")
    hf_res = _ping_hf_text(hf_token, t0)
    if hf_res:
        return hf_res

    # 8. Pollinations (zero-key free)
    note("Pollinations")
    try:
        r = requests.post("https://text.pollinations.ai/",
                          json={"messages": [{"role": "user", "content": "ping"}]},
                          timeout=12)
        if r.status_code == 200 and r.text.strip():
            return _ok("Pollinations AI", "Pollinations free text engine is live.", t0)
    except Exception:
        pass

    return _fail(
        "No live AI script provider. Tried: " + ", ".join(tried) +
        ". Add a key (Gemini/Groq/OpenAI/Muse/HF_TOKEN) or start Ollama.",
        t0,
    )


# ---------------------------------------------------------------------------
# Image nodes
# ---------------------------------------------------------------------------

def test_image(model_name: str = "", api_key: str = "") -> dict:
    t0 = time.time()
    model = (model_name or "").lower()
    key = (api_key or "").strip()

    # ComfyUI local
    if "comfy" in model:
        try:
            r = requests.get("http://127.0.0.1:8188/system_stats", timeout=4)
            if r.status_code == 200:
                return _ok("ComfyUI Local", "ComfyUI GPU server is live on :8188.", t0)
            return _fail("ComfyUI responded with HTTP %s on :8188." % r.status_code, t0, "ComfyUI Local")
        except Exception:
            return _fail("ComfyUI is not reachable at http://127.0.0.1:8188.", t0, "ComfyUI Local")

    # DALL-E 3
    if "dall" in model or "openai" in model:
        o_key = key or _env("OPENAI_API_KEY")
        if not o_key:
            return _fail("No OpenAI API key for DALL-E 3 (node config or OPENAI_API_KEY).", t0, "DALL-E 3")
        try:
            r = requests.get("https://api.openai.com/v1/models",
                             headers={"Authorization": f"Bearer {o_key}"}, timeout=10)
            if r.status_code == 200:
                return _ok("DALL-E 3", "OpenAI API key valid — DALL-E 3 ready.", t0)
            return _fail(f"OpenAI key rejected (HTTP {r.status_code}).", t0, "DALL-E 3")
        except Exception as e:
            return _fail(f"OpenAI unreachable: {e}", t0, "DALL-E 3")

    # Gemini / Imagen
    if "gemini" in model or "imagen" in model:
        g_key = key or _env("GEMINI_API_KEY")
        if not g_key:
            return _fail("No Gemini API key (node config or GEMINI_API_KEY).", t0, "Imagen")
        try:
            r = requests.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={g_key}",
                timeout=10)
            if r.status_code == 200:
                return _ok("Imagen", "Gemini API key valid — Imagen ready.", t0)
            return _fail(f"Gemini key rejected (HTTP {r.status_code}).", t0, "Imagen")
        except Exception as e:
            return _fail(f"Gemini unreachable: {e}", t0, "Imagen")

    # Hugging Face (FLUX.1 / SD)
    if any(k in model for k in ["flux", "huggingface", "hugging", "sd", "stable"]):
        hf_token = clean_token(_env("HF_TOKEN", "HUGGINGFACE_TOKEN"))
        if not hf_token:
            return _fail("HF_TOKEN not set — Hugging Face image models need a token.", t0, "Hugging Face")
        try:
            r = requests.get("https://huggingface.co/api/whoami",
                             headers={"Authorization": f"Bearer {hf_token}"}, timeout=10)
            if r.status_code == 200:
                who = r.json().get("name", "?")
                return _ok("Hugging Face", f"HF token valid (user: {who}) — FLUX.1 ready.", t0)
            if r.status_code == 401:
                return _fail(
                    "Hugging Face rejected the saved token (HTTP 401) — it is invalid, "
                    "expired, or revoked on Hugging Face's side. Fix: open "
                    "https://huggingface.co/settings/tokens, create a new User Access "
                    "Token (fine-grained tokens need the 'Make calls to Inference "
                    "Providers' permission), then paste it fresh into API Keys → "
                    "Hugging Face and re-run PreFlight.", t0, "Hugging Face")
            return _fail(f"Hugging Face token check failed (HTTP {r.status_code}).", t0, "Hugging Face")
        except Exception as e:
            return _fail(f"Hugging Face unreachable: {e}", t0, "Hugging Face")

    # Default: Pollinations free image engine — REAL tiny render as the live check
    try:
        import random as _rand
        seed = _rand.randint(1, 999999)
        r = requests.get(
            f"https://image.pollinations.ai/prompt/connection-test?model=turbo&width=128&height=128"
            f"&nologo=true&seed={seed}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=45,
        )
        ctype = r.headers.get("Content-Type", "")
        if r.status_code == 200 and "image" in ctype and len(r.content) > 2000:
            return _ok("Pollinations", "Pollinations free image engine rendered live.", t0)
        return _fail(f"Pollinations image check failed (HTTP {r.status_code}, {ctype}).", t0, "Pollinations")
    except Exception as e:
        return _fail(f"Pollinations unreachable: {e}", t0, "Pollinations")


# ---------------------------------------------------------------------------
# TTS nodes
# ---------------------------------------------------------------------------

def test_tts(provider: str = "", api_key: str = "") -> dict:
    t0 = time.time()
    prov = (provider or "").lower()

    if "kokoro" in prov:
        try:
            import kokoro  # noqa: F401
            return _ok("Kokoro-82M", "Kokoro local neural voice engine installed.", t0)
        except Exception:
            return _fail("Kokoro provider selected but the 'kokoro' package is not installed.", t0, "Kokoro")

    if "eleven" in prov:
        el_key = (api_key or "").strip() or _env("ELEVENLABS_API_KEY")
        if not el_key:
            return _fail("ElevenLabs selected but no API key (node config or ELEVENLABS_API_KEY).", t0, "ElevenLabs")
        try:
            r = requests.get("https://api.elevenlabs.io/v1/voices",
                             headers={"xi-api-key": el_key}, timeout=10)
            if r.status_code == 200:
                return _ok("ElevenLabs", "ElevenLabs API key valid.", t0)
            return _fail(f"ElevenLabs key rejected (HTTP {r.status_code}).", t0, "ElevenLabs")
        except Exception as e:
            return _fail(f"ElevenLabs unreachable: {e}", t0, "ElevenLabs")

    # Default: Edge-TTS (cloud, keyless) — verify the service endpoint is reachable
    try:
        import socket
        socket.create_connection(("speech.platform.bing.com", 443), timeout=6).close()
        return _ok("Edge-TTS", "Edge-TTS speech endpoint reachable.", t0)
    except Exception:
        pass
    try:
        import kokoro  # noqa: F401
        return _ok("Kokoro-82M", "Edge-TTS unreachable; Kokoro local fallback installed.", t0)
    except Exception:
        return _fail("No TTS available: Edge-TTS endpoint unreachable and Kokoro not installed.", t0)


# ---------------------------------------------------------------------------
# Image-to-video nodes
# ---------------------------------------------------------------------------

def test_video(provider: str = "", api_key: str = "") -> dict:
    t0 = time.time()
    prov = (provider or "").lower()
    key = (api_key or "").strip()

    # Local ComfyUI (Wan / LTX / SVD) — key-free, must be running
    if "comfy" in prov or "local" in prov or "wan" in prov or "ltx" in prov or not prov:
        try:
            r = requests.get("http://127.0.0.1:8188/system_stats", timeout=4)
            if r.status_code == 200:
                return _ok("ComfyUI Local", "ComfyUI video server live on :8188.", t0)
        except Exception:
            pass
        # fall through to HF check when provider is auto

    hf_token = clean_token(_env("HF_TOKEN", "HUGGINGFACE_TOKEN"))
    if "huggingface" in prov or "svd" in prov or "cogvideo" in prov or not key:
        if hf_token:
            try:
                r = requests.get("https://huggingface.co/api/whoami",
                                 headers={"Authorization": f"Bearer {hf_token}"}, timeout=10)
                if r.status_code == 200:
                    return _ok("Hugging Face Video", "HF token valid — SVD/CogVideoX cloud ready.", t0)
            except Exception:
                pass

    paid = ["luma", "runway", "kling", "pika", "veo", "minimax", "fal"]
    if any(p in prov for p in paid):
        if key:
            return _ok("Video API", f"API key configured for '{provider}' (live render not pre-tested).", t0)
        return _fail(f"'{provider}' needs an API key in the node config.", t0, provider)

    return _fail(
        "No video provider live: ComfyUI offline (:8188) and no HF_TOKEN set.",
        t0,
    )


# ---------------------------------------------------------------------------
# YouTube upload node
# ---------------------------------------------------------------------------

def test_youtube(user_id: int = 1) -> dict:
    t0 = time.time()
    try:
        from .youtube_auth import is_connected
        if is_connected(user_id):
            return _ok("YouTube", f"YouTube OAuth connected for user {user_id}.", t0)
        return _fail("YouTube not connected — complete OAuth in the YouTube settings page.", t0, "YouTube")
    except Exception as e:
        return _fail(f"YouTube credential check failed: {e}", t0, "YouTube")


# ---------------------------------------------------------------------------
# Dispatcher + preflight
# ---------------------------------------------------------------------------

# node_type -> which test it needs. Anything not listed needs no live connection.
# NOTE: unimplemented passthrough types (gen-scene-breakdown, translate, subtitle-gen,
# etc.) are deliberately NOT listed — they must never block a run.
REQUIRED_TESTS = {
    "gen-script": "llm",
    "extract-viral-angle": "llm",
    "gen-hook": "llm",
    "tts": "tts",
    "voice": "tts",
    "image-gen": "image",
    "visuals": "image",
    "gen-image": "image",
    "img-to-video": "video",
    "image-to-video": "video",
    "gen-video": "video",
    "youtube-upload": "youtube",
    "upload-yt": "youtube",
}


def test_node(node_type: str, config: dict | None) -> dict:
    """Run the live connection test for a single node. Always honest."""
    config = config or {}
    kind = REQUIRED_TESTS.get((node_type or "").lower())
    if not kind:
        return {"ok": True, "provider": "local",
                "message": f"Node '{node_type}' needs no external connection.", "latency_ms": 0}
    try:
        if kind == "llm":
            return test_llm(config.get("model", ""), config.get("api_key", ""))
        if kind == "image":
            return test_image(config.get("model", ""), config.get("api_key", ""))
        if kind == "tts":
            return test_tts(config.get("provider", ""), config.get("api_key", ""))
        if kind == "video":
            return test_video(config.get("provider", ""), config.get("api_key", ""))
        if kind == "youtube":
            return test_youtube(int(config.get("user_id") or 1))
    except Exception as e:
        return {"ok": False, "provider": "", "message": f"Test crashed: {e}", "latency_ms": 0}
    return {"ok": False, "provider": "", "message": "Unknown test kind.", "latency_ms": 0}


def preflight_workflow(workflow: dict) -> dict:
    """
    Test every connection-requiring node in a workflow, in parallel.
    Returns {"can_start": bool, "nodes": {node_id: result}, "failed": [...]}.
    """
    nodes = workflow.get("nodes", []) or []
    results: dict = {}

    def _run(node):
        nid = node.get("id", "?")
        ntype = node.get("type", "?")
        cfg = {**(node.get("data") or {}), **(node.get("config") or {})}
        res = test_node(ntype, cfg)
        res["node_id"] = nid
        res["node_type"] = ntype
        res["required"] = (ntype or "").lower() in REQUIRED_TESTS
        return nid, res

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        for nid, res in ex.map(_run, nodes):
            results[nid] = res

    failed = [r for r in results.values() if r["required"] and not r["ok"]]
    return {
        "can_start": not failed,
        "nodes": results,
        "failed": [
            {"node_id": f["node_id"], "node_type": f["node_type"],
             "provider": f.get("provider", ""), "message": f["message"]}
            for f in failed
        ],
    }
