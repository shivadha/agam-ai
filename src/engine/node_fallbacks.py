"""
node_fallbacks.py — what happens when a workflow node fails.

Two policies, chosen per node via the node's ``on_failure`` setting
(``"fallback"`` | ``"fail"``); the workflow JSON can set a default for
all nodes via ``failure_policy``:

  * ``"fallback"`` (default): the engine AUTOMATICALLY tries other ways
    to fulfill the node. Registered fallback strategies for that node
    type are attempted in order until one succeeds. The winning result is
    marked with ``recovered_via`` so the UI can show the node recovered.
    Only when every strategy fails does the node report an error — and
    then the cycle halts (there is nothing left to try).

  * ``"fail"``: the node failure FAILS THE WHOLE CYCLE immediately —
    the engine's CRITICAL HALT, no fallbacks attempted. Use it for nodes
    whose output everything downstream depends on being genuine
    (e.g. you never want a template standing in for a real script).

Register a strategy with::

    @fallback("gen-script", "free-web-agent")
    def _fb(engine, node, node_data, inputs, primary_error): ...

A strategy receives the engine (for ``engine._find_in_state``), the node
dicts, and the primary exception. Return a result dict with
``"status": "success"`` (extra keys should mirror the node's normal
result shape so downstream nodes keep working), or raise / return None
to let the next strategy try.
"""
from __future__ import annotations

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

FAIL = "fail"
FALLBACK = "fallback"

_FALLBACKS: dict[str, list[tuple[str, callable]]] = {}


def fallback(*node_types: str, name: str):
    """Decorator registering a fallback strategy for node type(s)."""
    def deco(fn):
        for nt in node_types:
            _FALLBACKS.setdefault(nt, []).append((name, fn))
        fn.strategy_name = name
        return fn
    return deco


def resolve_policy(node_data: dict, workflow: dict) -> str:
    """'fallback' or 'fail'. Node-level `on_failure` wins; workflow-level
    `failure_policy` is the default; global default is 'fallback'."""
    node_data = node_data or {}
    workflow = workflow or {}
    p = str(node_data.get("on_failure") or "").strip().lower()
    if p.startswith("fail"):
        return FAIL
    if p == FALLBACK:
        return FALLBACK
    w = str(workflow.get("failure_policy") or "").strip().lower()
    if w.startswith("fail"):
        return FAIL
    return FALLBACK


def attempt_fallbacks(engine, node: dict, node_type: str, node_data: dict,
                      inputs: dict, primary_error: Exception) -> dict | None:
    """Try each registered strategy in order. Returns the first successful
    result dict (marked with `recovered_via`), or None when every
    strategy failed / none are registered."""
    strategies = _FALLBACKS.get(node_type, [])
    if not strategies:
        return None
    node_id = (node or {}).get("id", "?")
    print(f"[node_fallbacks] Node {node_id} ({node_type}) failed: {primary_error}. "
          f"Trying {len(strategies)} fallback strategie(s)...", flush=True)
    for name, fn in strategies:
        try:
            res = fn(engine, node, node_data, inputs, primary_error)
        except Exception as e:
            print(f"[node_fallbacks] strategy '{name}' failed: {e}", flush=True)
            continue
        if res and res.get("status") == "success":
            res.setdefault("recovered_via", name)
            res["recovery_note"] = (
                f"Primary failed ({primary_error}); recovered via '{name}'.")
            print(f"[node_fallbacks] Node {node_id} RECOVERED via '{name}'.", flush=True)
            return res
        print(f"[node_fallbacks] strategy '{name}' returned no success; trying next.",
              flush=True)
    return None


# ═══════════════════════════════════════════════════════════════════
# Fallback strategies
# ═══════════════════════════════════════════════════════════════════

# ── gen-script ─────────────────────────────────────────────────────

@fallback("gen-script", name="free-web-agent")
def _fb_script_freeweb(engine, node, node_data, inputs, primary_error):
    """Primary LLM failed (bad key / quota / outage) — retry the same
    script request through the free-web background agent ($0)."""
    from src.backend.script_gen import generate_video_content
    if str(node_data.get("model", "")).lower().startswith("free-web"):
        raise RuntimeError("primary was already the free-web agent")
    topic_title = (node_data.get("topic_title") or node_data.get("topic")
                   or engine._find_in_state("topic_title")
                   or engine._find_in_state("topic") or "AI Trends")
    script_data = generate_video_content(
        topic_title, node_data.get("custom_prompt", ""),
        model_name="free-web", custom_api_key="",
        shorts_length=int(node_data.get("shorts_length", 45) or 45),
        visual_style=node_data.get("visual_style") or "cinema_8k",
    )
    scenes = (script_data.get("scenes") if script_data else []) or []
    if not script_data or len(scenes) < 3:
        raise RuntimeError("free-web agent also produced no usable script")
    return {
        "status": "success", "node_type": "gen-script",
        "topic": topic_title, "topic_title": topic_title,
        "visual_style": node_data.get("visual_style") or "cinema_8k",
        "title": script_data.get("title", topic_title),
        "script": script_data.get("script", ""),
        "scenes": scenes,
        "description": script_data.get("description", ""),
        "tags": script_data.get("tags", []),
    }


@fallback("gen-script", name="template-script")
def _fb_script_template(engine, node, node_data, inputs, primary_error):
    """Every AI route failed — build a valid director script from a
    template so the cycle can still complete offline. Marked clearly."""
    topic_title = (node_data.get("topic_title") or node_data.get("topic")
                   or engine._find_in_state("topic_title")
                   or engine._find_in_state("topic") or "AI Trends")
    hook = engine._find_in_state("hook") or f"What if everything you knew about {topic_title} was wrong?"
    visual_style = node_data.get("visual_style") or "cinema_8k"
    beats = [
        ("HOOK", hook),
        ("CONTEXT", f"Here's the story behind {topic_title} that nobody talks about."),
        ("TWIST", f"The turning point came when the truth about {topic_title} finally surfaced."),
        ("PROOF", f"Look at what happened next — the evidence around {topic_title} is undeniable."),
        ("PAYOFF", f"If this opened your eyes about {topic_title}, share it and follow for part two."),
    ]
    scenes = []
    for i, (beat, narration) in enumerate(beats):
        scenes.append({
            "narration": narration,
            "image_prompt": (f"Cinematic 8k vertical {visual_style} shot embodying '{beat}' "
                             f"for a story about {topic_title}, dramatic lighting, ultra detailed"),
            "image_to_video_prompt": "cinematic slow push-in, subtle parallax, photorealistic",
        })
    script_text = " ".join(s["narration"] for s in scenes)
    return {
        "status": "success", "node_type": "gen-script",
        "topic": topic_title, "topic_title": topic_title,
        "visual_style": visual_style,
        "title": f"{topic_title} — Explained",
        "script": script_text, "scenes": scenes,
        "description": f"A breakdown of {topic_title}. #Shorts #Viral",
        "tags": ["#Shorts", "#Viral", "#AI", "#Trending"],
        "recovery_note": "Offline template script used — replace with AI script for best quality.",
    }


# ── tts ────────────────────────────────────────────────────────────

@fallback("tts", name="alt-edge-voices")
def _fb_tts_alt_voices(engine, node, node_data, inputs, primary_error):
    """Kokoro/Edge chain failed — retry Edge-TTS explicitly with a few
    alternate neural voices (different voice, different infra path)."""
    from src.backend.voice_gen import generate_audio
    script_text = (node_data.get("script") or ""
                   or engine._find_in_state("script") or "")
    if not script_text:
        raise RuntimeError("no script text available for TTS retry")
    node_id = (node or {}).get("id", "n")
    for voice in ("en-US-ChristopherNeural", "en-US-AriaNeural", "en-IN-PrabhatNeural"):
        out = os.path.join(OUTPUT_DIR, f"audio_{node_id}_fb_{voice[:5]}.mp3")
        audio_path, vtt_path = generate_audio(
            script_text, out, voice=voice, provider="edge-tts",
            api_key=node_data.get("api_key", ""))
        if audio_path and os.path.exists(audio_path):
            return {"status": "success", "node_type": "tts",
                    "audio_path": audio_path, "vtt_path": vtt_path,
                    "voice": voice}
    raise RuntimeError("all alternate Edge-TTS voices failed")


# ── image-gen ──────────────────────────────────────────────────────

@fallback("image-gen", "visuals", "gen-image", name="swap-source")
def _fb_imagegen_swap(engine, node, node_data, inputs, primary_error):
    """Primary image source failed — use the OTHER source: free-web agent
    <-> local/cloud queue."""
    scenes = node_data.get("scenes") or engine._find_in_state("scenes") or []
    if not scenes:
        raise RuntimeError("no scenes available for image-gen retry")
    visual_style = (node_data.get("visual_style")
                    or engine._find_in_state("visual_style") or "cinema_8k")
    primary_freeweb = str(node_data.get("model", "")).lower().startswith("free-web")

    if primary_freeweb:
        from src.backend.image_gen import generate_images_for_scenes
        updated = generate_images_for_scenes(
            scenes, OUTPUT_DIR, model_name="DALL-E 3",
            custom_api_key=node_data.get("api_key", ""),
            visual_style=visual_style)
    else:
        from src.backend.free_agent_client import generate_image_file
        from src.backend.free_prompting import ensure_image_prompts
        main_script = engine._find_in_state("script") or ""
        scenes = ensure_image_prompts(scenes, main_script, visual_style)
        for i, scene in enumerate(scenes):
            prompt = (scene.get("image_prompt")
                      or (scene.get("image_prompts") or [None])[0]
                      or scene.get("narration")
                      or f"Cinematic photorealistic 8k vertical shot, scene {i + 1}")
            img_path = generate_image_file(prompt, provider_id=None)
            scene.setdefault("image_paths", []).append(img_path)
        updated = scenes
    return {"status": "success", "node_type": "image-gen", "scenes": updated}


# ── img-to-video ───────────────────────────────────────────────────

@fallback("img-to-video", "image-to-video", name="swap-source")
def _fb_img2vid_swap(engine, node, node_data, inputs, primary_error):
    """Primary video source failed — use the OTHER source: free-web agent
    <-> local/cloud queue (ComfyUI first, keyless)."""
    from src.backend.free_prompting import ensure_video_prompts
    scenes = node_data.get("scenes") or engine._find_in_state("scenes") or []
    if not scenes:
        raise RuntimeError("no scenes available for img-to-video retry")
    main_script = engine._find_in_state("script") or ""
    scenes = ensure_video_prompts(scenes, main_script)
    primary_freeweb = str(node_data.get("provider", "")).lower().startswith("free-web")

    if primary_freeweb:
        from src.backend.video_gen_ai import generate_videos_for_scenes
        updated = generate_videos_for_scenes(
            scenes=scenes, output_dir=OUTPUT_DIR,
            provider="ComfyUI (Local Wan / SVD - Free)",
            api_key=node_data.get("api_key", ""))
    else:
        from src.backend.free_agent_client import generate_video_file
        for i, scene in enumerate(scenes):
            img = (scene.get("image_paths") or [None])[0] or scene.get("image_path")
            prompt = (scene.get("image_to_video_prompt") or scene.get("video_prompt")
                      or scene.get("narration") or "cinematic slow push-in, photorealistic")
            v_path = generate_video_file(prompt, input_path=img, provider_id=None)
            scene.setdefault("video_paths", []).append(v_path)
        updated = scenes
    return {"status": "success", "node_type": "img-to-video", "scenes": updated}


# ── meme-sound ─────────────────────────────────────────────────────

@fallback("meme-sound", name="graceful-skip")
def _fb_meme_skip(engine, node, node_data, inputs, primary_error):
    """No meme sounds available — degrade gracefully: the video works
    fine without a meme drop, so emit an empty timeline with a warning
    instead of failing the cycle."""
    print(f"[node_fallbacks] meme-sound skipped: {primary_error}", flush=True)
    return {"status": "success", "node_type": "meme-sound",
            "sfx_timeline": [], "skipped": True,
            "warning": str(primary_error)}


# ── fetch-broll ────────────────────────────────────────────────────

@fallback("fetch-broll", name="graceful-skip")
def _fallback_broll_skip(engine, node, node_data, inputs, primary_error):
    """Stock b-roll fetch failed — the assembler prefers real footage but
    works with AI stills, so continue without b-roll."""
    print(f"[node_fallbacks] fetch-broll skipped: {primary_error}", flush=True)
    scenes = node_data.get("scenes") or engine._find_in_state("scenes") or []
    return {"status": "success", "node_type": "fetch-broll",
            "broll_map": {}, "scenes": scenes, "skipped": True,
            "warning": str(primary_error)}
