"""
free_prompting.py — ChatGPT writes the per-scene prompts for the free-web
background agent pipeline.

Two guarantees the orchestrator enforces before any free generation:

1. IMAGE PROMPTS — every scene gets an `image_prompt` written by ChatGPT,
   grounded in the main script (subject, mood, lighting, 9:16 composition).
2. VIDEO/MOTION SCRIPTS — every scene gets an `image_to_video_prompt`
   written by ChatGPT: a dedicated motion script (camera move + dynamic
   motion, 4-6 seconds) based on the main script AND the scene's image
   prompt, so the video actually continues the story instead of a generic
   "slow push-in".

Both run as ONE batched chat call per missing-prompt type (not one call
per scene). ChatGPT is reached through the free-web background agent
(ChatGPT Go, $0); if the agent is down it falls back to the normal model
chain so the pipeline never dies.
"""
from __future__ import annotations

import re

PREFER_CHAT_PROVIDER = "chatgpt_go"  # ChatGPT Go via the background agent


def _ask_chatgpt(system_prompt: str, user_prompt: str,
                 max_new_tokens: int = 2500) -> str | None:
    """ChatGPT via free-web agent first, normal chain as fallback."""
    try:
        from src.backend.free_agent_client import generate_text, FreeAgentError
        print("[free-prompting] asking ChatGPT via free-web agent...")
        return generate_text(f"{system_prompt}\n\n{user_prompt}\n\n"
                             f"(Reply with only the requested content.)",
                             provider_id=PREFER_CHAT_PROVIDER,
                             timeout=max(600, max_new_tokens))
    except Exception as e:
        print(f"[free-prompting] free-web agent unavailable ({e}); "
              f"falling back to model chain.")
    try:
        from src.backend.script_gen import _chat_via_chain
        return _chat_via_chain(system_prompt, user_prompt,
                               model_name="GPT-4o", tag="prompt-ensure",
                               max_new_tokens=max_new_tokens)
    except Exception as e:
        print(f"[free-prompting] model chain also failed: {e}")
        return None


def _parse_numbered(text: str | None, count: int) -> list[str]:
    """Parse `1. ...` numbered lines back into a list (best effort)."""
    if not text:
        return []
    items: list[str] = []
    for line in text.splitlines():
        m = re.match(r"\s*(\d+)[.)\-:]\s*(.+)", line.strip())
        if m:
            items.append(m.group(2).strip())
        elif items and line.strip():
            # continuation of the previous item
            items[-1] += " " + line.strip()
    # pad / trim to the expected count
    while len(items) < count:
        items.append("")
    return items[:count]


def ensure_image_prompts(scenes: list, main_script: str = "",
                         visual_style: str = "cinema_8k") -> list:
    """Fill missing scene['image_prompt'] with ChatGPT-written prompts."""
    missing = [i for i, s in enumerate(scenes)
               if not (s.get("image_prompt") or "").strip()]
    if not missing:
        return scenes

    script_ctx = (main_script or "")[:2500]
    numbered = []
    for n, i in enumerate(missing, 1):
        s = scenes[i]
        narration = (s.get("narration") or "")[:300]
        numbered.append(f"{n}. Scene {s.get('scene_number', i + 1)} narration: "
                        f"\"{narration}\"")
    system = (
        "You are a cinematic art director. Write image-generation prompts. "
        "Reply with ONLY numbered lines, one per scene, no extra text.")
    user = (
        f"Main video script (ground every prompt in THIS story):\n{script_ctx}\n\n"
        f"For each scene below write ONE image prompt: hyper-realistic 8k "
        f"cinematic still, {visual_style} style, 9:16 vertical. Describe "
        f"subject, dramatic lighting, atmosphere, environment. "
        f"Each prompt must be unique to its scene's narration.\n\n"
        + "\n".join(numbered))
    text = _ask_chatgpt(system, user, max_new_tokens=2000)
    prompts = _parse_numbered(text, len(missing))
    for idx, prompt in zip(missing, prompts):
        if prompt:
            scenes[idx]["image_prompt"] = prompt
            scenes[idx]["image_prompt_source"] = "chatgpt-free-web"
            print(f"[free-prompting] scene {idx + 1}: image prompt written "
                  f"by ChatGPT ({len(prompt)} chars)")
    return scenes


def ensure_video_prompts(scenes: list, main_script: str = "") -> list:
    """Fill missing scene['image_to_video_prompt'] with ChatGPT motion scripts.

    Each motion script is written from the main script AND the scene's own
    image prompt, so the animation continues that scene's story.
    """
    # Image prompts must exist first — the motion script builds on them.
    scenes = ensure_image_prompts(scenes, main_script)

    missing = [i for i, s in enumerate(scenes)
               if not (s.get("image_to_video_prompt") or "").strip()]
    if not missing:
        return scenes

    script_ctx = (main_script or "")[:2500]
    numbered = []
    for n, i in enumerate(missing, 1):
        s = scenes[i]
        img_prompt = (s.get("image_prompt") or "")[:400]
        narration = (s.get("narration") or "")[:200]
        numbered.append(
            f"{n}. Scene {s.get('scene_number', i + 1)} — image shows: "
            f"\"{img_prompt}\" | voiceover: \"{narration}\"")
    system = (
        "You are a motion director for AI image-to-video. Write motion "
        "scripts. Reply with ONLY numbered lines, one per scene, no extra text.")
    user = (
        f"Main video script:\n{script_ctx}\n\n"
        f"For each scene below write ONE image-to-video motion script: the "
        f"exact camera movement (push-in, pan, tilt, orbit, dolly...) plus "
        f"dynamic motion inside the frame (fog drift, particles, light "
        f"flicker, subject movement), 4-6 seconds, cinematic. It must "
        f"continue the story of THAT scene's image and voiceover — never a "
        f"generic push-in.\n\n" + "\n".join(numbered))
    text = _ask_chatgpt(system, user, max_new_tokens=2000)
    prompts = _parse_numbered(text, len(missing))
    for idx, prompt in zip(missing, prompts):
        if prompt:
            scenes[idx]["image_to_video_prompt"] = prompt
            scenes[idx]["image_to_video_prompt_source"] = "chatgpt-free-web"
            print(f"[free-prompting] scene {idx + 1}: motion script written "
                  f"by ChatGPT ({len(prompt)} chars)")
    return scenes
