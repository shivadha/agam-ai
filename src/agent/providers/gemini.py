"""
gemini.py — free image generation AND image-to-video via gemini.google.com
(user's Google AI plan; video uses the Veo model inside Gemini web).

Image flow: open Gemini -> type prompt -> send -> wait for the generated
image -> download it with an authenticated request.

Video flow: every run takes a DIFFERENT path to the video feature — the
VIDEO_STRATEGIES ledger below records each distinct route (tool chip,
tools menu, model picker, chat intent). StrategyRotator picks one per run,
never repeating the previous run's, and logs the choice so the job record
shows which path was taken. All strategies converge on: attach image ->
prompt -> submit -> wait for <video> -> download mp4.

NOTE: selectors below are best-effort from the public web UI and are marked
# VERIFY. Google changes this DOM regularly. If generate() fails it raises
ProviderError naming the selector that broke — update SELECTORS and retry.
"""
from __future__ import annotations

import logging
import os
import time
import uuid

from .base import FreeWebProvider, ProviderError, LoginRequired, StrategyRotator

log = logging.getLogger("free-agent.gemini")

# Prompt-box / response selectors. Tried in order; first match wins.
SELECTORS = {
    # The message input (contenteditable). Candidates tried in order.
    "prompt_box": [
        'div[aria-label="Ask Gemini"]',          # VERIFY
        'div[role="textbox"]',                   # VERIFY
        'rich-textarea div[contenteditable="true"]',  # VERIFY
    ],
    "send_button": [
        'button[aria-label="Send message"]',     # VERIFY
        'button:has-text("Send")',               # VERIFY
    ],
    # Any rendered image inside a model response turn.
    "response_image": [
        'message-content img',                  # VERIFY
        'div.model-response img',               # VERIFY
        'img[src*="googleusercontent"]',        # fallback: any GU image
    ],
    "stop_button": ['button[aria-label="Stop responding"]'],  # VERIFY

    # ── video-mode entry points (each strategy uses different ones) ──
    "video_chip": [
        'button:has-text("Video")',             # VERIFY — tool chip on home
        'button[aria-label*="ideo"]',           # VERIFY
    ],
    "tools_menu_button": [
        'button[aria-label="Open tools menu"]', # VERIFY
        'button:has-text("Tools")',             # VERIFY
    ],
    "tools_menu_video_item": [
        'button:has-text("Create videos")',     # VERIFY
        '[role="menuitem"]:has-text("ideo")',   # VERIFY
    ],
    "model_picker": [
        'button[aria-label*="model"]',          # VERIFY — model dropdown
        'button:has-text("Veo")',               # VERIFY — video model entry
    ],
    "attach_button": [
        'button[aria-label*="Attach"]',         # VERIFY
        'button[aria-label*="Upload"]',         # VERIFY
        'input[type="file"]',                  # direct file input fallback
    ],
    "result_video": [
        'video[src]',                           # VERIFY
        'video source[src]',                    # VERIFY
    ],
}

HUMAN_PAUSE = (0.6, 1.4)  # gentle pacing between actions


def _pause():
    import random
    time.sleep(random.uniform(*HUMAN_PAUSE))


def _first_locator(page, candidates):
    for sel in candidates:
        loc = page.locator(sel).first
        try:
            if loc.count() > 0:
                return loc, sel
        except Exception:
            continue
    return None, None


class GeminiProvider(FreeWebProvider):
    id = "gemini_web"
    display_name = "Gemini Web (AI Pro)"
    login_url = "https://gemini.google.com/"
    kinds = ("image", "video")
    balance_recipe = {"api_patterns": ["batchexecute"],
                      "regex": r"(\d+)\s*(?:images?|generations?|videos?)\s*(?:left|remaining|per day)"}

    # ── login ──────────────────────────────────────────────────────────
    def needs_login(self, page) -> bool:
        try:
            page.goto(self.login_url, wait_until="domcontentloaded", timeout=45000)
            _pause()
            body = page.locator("body").inner_text(timeout=10000).lower()
            return ("sign in" in body and "ask gemini" not in body)
        except Exception:
            return True

    # ── generation (dispatch by kind) ──────────────────────────────────
    def generate(self, page, job: dict, out_dir: str) -> dict:
        kind = job.get("kind") or "image"
        if kind == "video":
            return self._generate_video(page, job, out_dir)
        return self._generate_image(page, job, out_dir)

    # ── video (image-to-video via Veo inside Gemini) ────────────────────
    def _generate_video(self, page, job: dict, out_dir: str) -> dict:
        prompt = (job.get("prompt") or "").strip()
        input_path = job.get("input_path")
        if not input_path or not os.path.exists(input_path):
            raise ProviderError("gemini video job needs input_path pointing at an image")

        page.goto(self.login_url, wait_until="domcontentloaded", timeout=60000)
        if self.needs_login(page):
            raise LoginRequired("Gemini shows logged-out state")

        # A different recorded path every run — never repeats the last one.
        rotator = StrategyRotator(self.id, VIDEO_STRATEGIES)
        strategy = rotator.pick()  # logged + persisted in agent_strategy_state.json
        log.info("job %s: gemini_web video via strategy '%s'",
                 job.get("id"), strategy["name"])
        strategy["run"](page, {"prompt": prompt, "input_path": input_path})
        result = _wait_and_download_video(page, out_dir)
        result["strategy"] = strategy["name"]  # recorded on the job result
        return result

    # ── image generation ───────────────────────────────────────────────
    def _generate_image(self, page, job: dict, out_dir: str) -> dict:
        prompt = (job.get("prompt") or "").strip()
        if not prompt:
            raise ProviderError("empty prompt for gemini image job")

        page.goto(self.login_url, wait_until="domcontentloaded", timeout=60000)
        if self.needs_login(page):
            raise LoginRequired("Gemini shows logged-out state")

        box, used = _first_locator(page, SELECTORS["prompt_box"])
        if box is None:
            raise ProviderError(
                "gemini prompt box not found; tried: "
                + ", ".join(SELECTORS["prompt_box"]))
        box.click()
        _pause()
        # Ask explicitly for an image so a text answer isn't enough.
        full_prompt = prompt if "image" in prompt.lower() else f"Generate an image: {prompt}"
        page.keyboard.type(full_prompt, delay=18)
        _pause()

        send, _ = _first_locator(page, SELECTORS["send_button"])
        if send is not None:
            send.click()
        else:
            page.keyboard.press("Enter")
        _pause()

        # Wait for generation to finish: stop-button appears while working,
        # then an image shows up in the response.
        deadline = time.time() + 300
        img_url = None
        while time.time() < deadline:
            img, _ = _first_locator(page, SELECTORS["response_image"])
            if img is not None:
                try:
                    src = img.get_attribute("src")
                    # Skip tiny UI icons/avatars; want a real render.
                    if src and src.startswith("http") and "avatar" not in src.lower():
                        img_url = src
                        break
                except Exception:
                    pass
            time.sleep(3)

        if not img_url:
            raise ProviderError(
                "timed out waiting for gemini image; tried: "
                + ", ".join(SELECTORS["response_image"]))

        # Download with the page's authenticated session.
        resp = page.request.get(img_url, timeout=60000)
        if resp.status != 200:
            raise ProviderError(f"image download failed: HTTP {resp.status}")
        ctype = (resp.headers.get("content-type") or "").lower()
        ext = ".png" if "png" in ctype else ".jpg"
        out_path = os.path.join(out_dir, f"gemini_{uuid.uuid4().hex[:10]}{ext}")
        with open(out_path, "wb") as f:
            f.write(resp.body())
        return {"result_path": os.path.abspath(out_path)}


# ═══════════════════════════════════════════════════════════════════════
# VIDEO STRATEGY LEDGER — distinct recorded paths to image-to-video.
# Each entry is one human-plausible way to reach the Veo video feature
# inside Gemini web. StrategyRotator picks a different one every run and
# logs the choice, so the job record shows which path was taken.
# To add a new way: write a _strategy_* function, append one dict here.
# ═══════════════════════════════════════════════════════════════════════

def _strategy_video_chip(page, ctx):
    """Home screen -> click the Video/Veo tool chip -> attach -> prompt."""
    chip, used = _first_locator(page, SELECTORS["video_chip"])
    if chip is None:
        raise ProviderError("video tool chip not found; tried: "
                            + ", ".join(SELECTORS["video_chip"]))
    log.info("strategy video_chip: clicked %s", used)
    chip.click()
    _pause()
    _attach_image(page, ctx["input_path"])
    _type_prompt(page, ctx["prompt"])


def _strategy_tools_menu(page, ctx):
    """Open the + tools menu -> 'Create videos' -> attach -> prompt."""
    menu, _ = _first_locator(page, SELECTORS["tools_menu_button"])
    if menu is None:
        raise ProviderError("tools menu button not found; tried: "
                            + ", ".join(SELECTORS["tools_menu_button"]))
    menu.click()
    _pause()
    item, used = _first_locator(page, SELECTORS["tools_menu_video_item"])
    if item is None:
        raise ProviderError("'Create videos' menu item not found; tried: "
                            + ", ".join(SELECTORS["tools_menu_video_item"]))
    log.info("strategy tools_menu: picked %s", used)
    item.click()
    _pause()
    _attach_image(page, ctx["input_path"])
    _type_prompt(page, ctx["prompt"])


def _strategy_model_picker(page, ctx):
    """Switch the model dropdown to the video model first, then attach+prompt."""
    picker, _ = _first_locator(page, SELECTORS["model_picker"])
    if picker is None:
        raise ProviderError("model picker not found; tried: "
                            + ", ".join(SELECTORS["model_picker"]))
    picker.click()
    _pause()
    veo_opt = page.locator('button:has-text("Veo"), [role="option"]:has-text("Veo")').first
    try:
        if veo_opt.count() > 0:
            veo_opt.click()
            _pause()
    except Exception:
        pass
    _attach_image(page, ctx["input_path"])
    _type_prompt(page, ctx["prompt"])


def _strategy_chat_intent(page, ctx):
    """Type a video request in chat so intent routing engages video mode,
    then attach the image (prompt-first order, unlike the others)."""
    box, used = _first_locator(page, SELECTORS["prompt_box"])
    if box is None:
        raise ProviderError("gemini prompt box not found; tried: "
                            + ", ".join(SELECTORS["prompt_box"]))
    box.click()
    _pause()
    page.keyboard.type(f"Create a video from the image I am about to upload: "
                       f"{ctx['prompt']}", delay=18)
    _pause()
    _attach_image(page, ctx["input_path"])
    log.info("strategy chat_intent: typed video request via %s", used)


VIDEO_STRATEGIES = [
    {"name": "video_chip",
     "desc": "Click the Video/Veo tool chip on the home screen, then attach image + prompt.",
     "run": _strategy_video_chip},
    {"name": "tools_menu",
     "desc": "Open the + tools menu, pick 'Create videos', then attach image + prompt.",
     "run": _strategy_tools_menu},
    {"name": "model_picker",
     "desc": "Switch the model dropdown to the Veo video model first, then attach image + prompt.",
     "run": _strategy_model_picker},
    {"name": "chat_intent",
     "desc": "Type a video request in chat (intent routing), then attach the image — prompt-first order.",
     "run": _strategy_chat_intent},
]


# ── shared video helpers ──────────────────────────────────────────────

def _attach_image(page, input_path):
    if not input_path or not os.path.exists(input_path):
        raise ProviderError("gemini video needs input_path: an existing image file")
    btn, _ = _first_locator(page, SELECTORS["attach_button"])
    if btn is not None:
        try:
            tag = btn.evaluate("el => el.tagName.toLowerCase()")
            if tag == "input":
                btn.set_input_files(os.path.abspath(input_path))
            else:
                # Click attach, then use the file chooser.
                with page.expect_file_chooser(timeout=8000) as fc:
                    btn.click()
                fc.value.set_files(os.path.abspath(input_path))
            _pause()
            return
        except Exception as e:
            log.warning("attach via button failed (%s); trying direct input", e)
    direct = page.locator('input[type="file"]').first
    try:
        if direct.count() > 0:
            direct.set_input_files(os.path.abspath(input_path))
            _pause()
            return
    except Exception:
        pass
    raise ProviderError("could not attach image; tried: "
                        + ", ".join(SELECTORS["attach_button"]))


def _type_prompt(page, prompt):
    box, used = _first_locator(page, SELECTORS["prompt_box"])
    if box is None:
        raise ProviderError("gemini prompt box not found (video); tried: "
                            + ", ".join(SELECTORS["prompt_box"]))
    box.click()
    _pause()
    page.keyboard.type(prompt or "cinematic slow push-in, photorealistic", delay=16)
    _pause()
    send, _ = _first_locator(page, SELECTORS["send_button"])
    if send is not None:
        send.click()
    else:
        page.keyboard.press("Enter")
    _pause()


def _wait_and_download_video(page, out_dir, timeout_s=1200):
    deadline = time.time() + timeout_s
    video_url = None
    while time.time() < deadline:
        vid, _ = _first_locator(page, SELECTORS["result_video"])
        if vid is not None:
            try:
                src = vid.get_attribute("src")
                if src and src.startswith("http"):
                    video_url = src
                    break
            except Exception:
                pass
        time.sleep(5)
    if not video_url:
        raise ProviderError("timed out waiting for gemini video; tried: "
                            + ", ".join(SELECTORS["result_video"]))
    resp = page.request.get(video_url, timeout=120000)
    if resp.status != 200:
        raise ProviderError(f"video download failed: HTTP {resp.status}")
    out_path = os.path.join(out_dir, f"gemini_video_{uuid.uuid4().hex[:10]}.mp4")
    with open(out_path, "wb") as f:
        f.write(resp.body())
    return {"result_path": os.path.abspath(out_path)}


# ── video entry point (method lives on GeminiProvider above) ──────────
# (VIDEO_STRATEGIES + helpers; _generate_video is defined in the class.)
