"""
veo.py — free image-to-video via Google Flow (labs.google/fx, Veo free tier).

Every run takes a DIFFERENT recorded path to the image-to-video feature —
the VIDEO_STRATEGIES ledger below lists each distinct route (direct mode
pick, new-project-first, prompt-first ordering, keyboard-driven). Driving
the site identically every time is the easiest bot pattern to fingerprint,
so StrategyRotator picks one per run, never repeating the previous run's,
and logs the choice so the job record shows which path was taken.

Veo's free tier is only a few videos/day and generation takes minutes per
clip — the agent waits patiently and the job stays 'running' meanwhile.

NOTE: Flow's DOM changes often; selectors marked # VERIFY. Failures raise
ProviderError naming the broken selector.
"""
from __future__ import annotations

import logging
import os
import re
import time
import uuid

from .base import FreeWebProvider, ProviderError, LoginRequired, StrategyRotator

log = logging.getLogger("free-agent.veo")

SELECTORS = {
    "new_project": [
        'button:has-text("New project")',       # VERIFY
        'a:has-text("New project")',            # VERIFY
    ],
    "frames_to_video": [
        'button:has-text("Frames to video")',   # VERIFY
        'button:has-text("Image to video")',    # VERIFY
    ],
    "text_to_video": [
        'button:has-text("Text to video")',     # VERIFY
    ],
    "prompt_box": [
        'textarea[placeholder*="prompt"]',      # VERIFY
        'div[role="textbox"]',                  # VERIFY
    ],
    "generate_button": [
        'button:has-text("Generate")',          # VERIFY
        'button[aria-label*="Generate"]',       # VERIFY
    ],
    "result_video": [
        'video[src]',                           # VERIFY
        'video source[src]',                    # VERIFY
    ],
    "upload_input": [
        'input[type="file"]',                  # VERIFY
    ],
}

HUMAN_PAUSE = (0.8, 1.8)


def _pause():
    import random
    time.sleep(random.uniform(*HUMAN_PAUSE))


def _first(page, candidates):
    for sel in candidates:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                return loc
        except Exception:
            continue
    return None


class VeoProvider(FreeWebProvider):
    id = "veo_web"
    display_name = "Veo Web (free tier)"
    login_url = "https://labs.google/fx/"
    kinds = ("video",)
    balance_recipe = {"api_patterns": ["flow", "credit"],
                      "regex": r"(\d+)\s*(?:credits?|videos?)\s*(?:left|remaining)"}

    def needs_login(self, page) -> bool:
        try:
            page.goto(self.login_url, wait_until="domcontentloaded", timeout=45000)
            _pause()
            body = page.locator("body").inner_text(timeout=10000).lower()
            return "sign in" in body and "flow" not in body
        except Exception:
            return True

    def generate(self, page, job: dict, out_dir: str) -> dict:
        prompt = (job.get("prompt") or "").strip()
        input_path = job.get("input_path")

        page.goto(self.login_url, wait_until="domcontentloaded", timeout=60000)
        if self.needs_login(page):
            raise LoginRequired("Flow shows logged-out state")

        if not input_path or not os.path.exists(input_path):
            # Text-to-video fallback (no image given): single direct path.
            log.info("job %s: veo_web text-to-video (no input image)",
                     job.get("id"))
            mode = _first(page, SELECTORS["text_to_video"])
            if mode is not None:
                mode.click()
                _pause()
            _type_prompt(page, prompt)
            result = _submit_and_download(page, out_dir)
            result["strategy"] = "text_to_video_fallback"
            return result

        # Image-to-video: a different recorded path every run.
        rotator = StrategyRotator(self.id, VIDEO_STRATEGIES)
        strategy = rotator.pick()  # logged + persisted in agent_strategy_state.json
        log.info("job %s: veo_web via strategy '%s'",
                 job.get("id"), strategy["name"])
        strategy["run"](page, {"prompt": prompt, "input_path": input_path})
        result = _submit_and_download(page, out_dir)
        result["strategy"] = strategy["name"]  # recorded on the job result
        return result


# ═══════════════════════════════════════════════════════════════════════
# VIDEO STRATEGY LEDGER — distinct recorded paths to image-to-video.
# Same destination, different human-plausible routes: entry point, step
# order, and input modality (mouse vs keyboard) all vary per run.
# To add a new way: write a _strategy_* function, append one dict here.
# ═══════════════════════════════════════════════════════════════════════

def _strategy_frames_direct(page, ctx):
    """Home -> 'Frames to video' -> upload image -> prompt -> Generate."""
    _enter_frames_mode(page)
    _upload_image(page, ctx["input_path"])
    _type_prompt(page, ctx["prompt"])


def _strategy_new_project_first(page, ctx):
    """'New project' first -> 'Frames to video' -> prompt BEFORE upload
    (reversed order vs frames_direct) -> Generate."""
    new_proj = _first(page, SELECTORS["new_project"])
    if new_proj is not None:
        new_proj.click()
        _pause()
    _enter_frames_mode(page)
    _type_prompt(page, ctx["prompt"])
    _upload_image(page, ctx["input_path"])


def _strategy_prompt_first(page, ctx):
    """'Frames to video' -> type the motion prompt first, then attach the
    image, then Generate — prompt-first ordering."""
    _enter_frames_mode(page)
    _type_prompt(page, ctx["prompt"] or "cinematic slow push-in, photorealistic")
    _upload_image(page, ctx["input_path"])


def _strategy_keyboard_flow(page, ctx):
    """Keyboard-driven: Tab to the mode button, Enter to select, attach via
    the focused file input — no mouse clicks on the mode UI."""
    page.keyboard.press("Tab")
    _pause()
    for _ in range(12):  # walk focus toward the mode buttons
        focused = page.evaluate("() => document.activeElement?.textContent || ''")
        if "Frames to video" in focused or "Image to video" in focused:
            break
        page.keyboard.press("Tab")
        time.sleep(0.25)
    page.keyboard.press("Enter")
    _pause()
    # If keyboard nav missed, fall back to the direct click path.
    if _first(page, SELECTORS["prompt_box"]) is None:
        log.info("keyboard nav missed the mode; falling back to click")
        _enter_frames_mode(page)
    _upload_image(page, ctx["input_path"])
    _type_prompt(page, ctx["prompt"])


VIDEO_STRATEGIES = [
    {"name": "frames_direct",
     "desc": "Home -> 'Frames to video' -> upload image -> prompt -> Generate.",
     "run": _strategy_frames_direct},
    {"name": "new_project_first",
     "desc": "'New project' first, then frames mode with prompt typed before upload.",
     "run": _strategy_new_project_first},
    {"name": "prompt_first",
     "desc": "Frames mode, motion prompt typed first, image attached after.",
     "run": _strategy_prompt_first},
    {"name": "keyboard_flow",
     "desc": "Keyboard-driven: Tab/Enter to the mode, attach via focused input.",
     "run": _strategy_keyboard_flow},
]


# ── shared step helpers (strategies compose these differently) ─────────

def _enter_frames_mode(page):
    mode = _first(page, SELECTORS["frames_to_video"])
    if mode is None:
        raise ProviderError("Flow 'Frames to video' mode not found; tried: "
                            + ", ".join(SELECTORS["frames_to_video"]))
    mode.click()
    _pause()


def _upload_image(page, input_path):
    upload = _first(page, SELECTORS["upload_input"])
    if upload is None:
        raise ProviderError("Flow file-upload input not found")
    upload.set_input_files(os.path.abspath(input_path))
    _pause()


def _type_prompt(page, prompt):
    box = _first(page, SELECTORS["prompt_box"])
    if box is None:
        raise ProviderError("Flow prompt box not found; tried: "
                            + ", ".join(SELECTORS["prompt_box"]))
    box.click()
    _pause()
    page.keyboard.type(prompt or "cinematic slow push-in, photorealistic", delay=15)
    _pause()


def _submit_and_download(page, out_dir, timeout_s=1500):
    gen = _first(page, SELECTORS["generate_button"])
    if gen is None:
        raise ProviderError("Flow Generate button not found")
    gen.click()

    # Generation takes minutes. Poll for a playable <video>.
    deadline = time.time() + timeout_s  # 25 min max
    video_url = None
    seen = set()

    # Also sniff network responses for mp4s as a backup source.
    def on_response(resp):
        url = resp.url
        if re.search(r"\.mp4(\?|$)", url) and url not in seen:
            seen.add(url)

    page.on("response", on_response)
    try:
        while time.time() < deadline:
            vids = page.locator("video").all()
            for v in vids:
                try:
                    src = v.get_attribute("src")
                    if src and src.startswith("http"):
                        video_url = src
                        break
                except Exception:
                    continue
            if video_url or seen:
                break
            time.sleep(10)
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass

    video_url = video_url or (next(iter(seen)) if seen else None)
    if not video_url:
        raise ProviderError("timed out waiting for Veo render (25 min)")

    resp = page.request.get(video_url, timeout=120000)
    if resp.status != 200:
        raise ProviderError(f"video download failed: HTTP {resp.status}")
    out_path = os.path.join(out_dir, f"veo_{uuid.uuid4().hex[:10]}.mp4")
    with open(out_path, "wb") as f:
        f.write(resp.body())
    return {"result_path": os.path.abspath(out_path)}
