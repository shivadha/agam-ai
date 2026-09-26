"""
hailuo.py — free MiniMax H3 video via Hailuo AI web (hailuoai.video).

Hailuo AI is MiniMax's official web product for the Hailuo 3.0 (H3)
video model: normal web UI (prompt box + Create button + downloadable
results), free signup (Google/Apple/Facebook/email) with free credits for
new users — no API key needed. Generation is gated behind login, so the
user logs in once with --show-login and the persistent profile is reused.

Every run takes a DIFFERENT recorded path to the generation feature —
the VIDEO_STRATEGIES ledger below lists each distinct route. Driving a
site identically every time is the easiest bot pattern to fingerprint,
so StrategyRotator picks one per run, never repeating the previous run's,
and logs the choice so the job record shows which path was taken.

NOTE: Hailuo's DOM changes often; selectors marked # VERIFY. Failures
raise ProviderError naming the broken selector.
"""
from __future__ import annotations

import logging
import os
import re
import time
import uuid

from .base import FreeWebProvider, ProviderError, LoginRequired, StrategyRotator

log = logging.getLogger("free-agent.hailuo")

SELECTORS = {
    "create_video_tab": [
        'button:has-text("Create Video")',      # VERIFY
        'a:has-text("Create Video")',           # VERIFY
        '[role="tab"]:has-text("Create Video")',  # VERIFY
    ],
    "prompt_box": [
        'textarea[placeholder*="Describe the video"]',  # VERIFY
        'textarea[placeholder*="describe"]',            # VERIFY
        'div[role="textbox"]',                          # VERIFY
    ],
    "create_button": [
        'button:has-text("Create")',            # VERIFY
        'button[type="submit"]:has-text("Create")',  # VERIFY
    ],
    "omni_reference": [
        'button:has-text("Omni Reference")',    # VERIFY
        'div:has-text("Omni Reference")',       # VERIFY
    ],
    "upload_input": [
        'input[type="file"]',                   # VERIFY
    ],
    "result_video": [
        'video[src]',                           # VERIFY
        'video source[src]',                    # VERIFY
    ],
    "login_markers": [
        'text="Continue with Google"',          # VERIFY
        'button:has-text("Continue with Google")',  # VERIFY
    ],
    "aspect_option": [
        'button:has-text("9:16")',              # VERIFY (best-effort)
        '[aria-label*="9:16"]',                 # VERIFY (best-effort)
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


class HailuoProvider(FreeWebProvider):
    id = "hailuo_web"
    display_name = "Hailuo AI (MiniMax H3, free signup)"
    login_url = "https://hailuoai.video/"
    kinds = ("video",)
    balance_recipe = {"api_patterns": ["hailuoai", "credit"],
                      "regex": r"(\d+)\s*(?:credits?)\s*(?:left|remaining)"}

    def needs_login(self, page) -> bool:
        try:
            page.goto(self.login_url, wait_until="domcontentloaded", timeout=45000)
            _pause()
            return _first(page, SELECTORS["login_markers"]) is not None
        except Exception:
            return True

    def generate(self, page, job: dict, out_dir: str) -> dict:
        prompt = (job.get("prompt") or "").strip()
        input_path = job.get("input_path")

        page.goto(self.login_url, wait_until="domcontentloaded", timeout=60000)
        if self.needs_login(page):
            raise LoginRequired(
                "Hailuo AI shows the logged-out state (login modal). "
                "Log in once with --show-login, then retry.")

        if not input_path or not os.path.exists(input_path):
            # Text-to-video: single direct path.
            log.info("job %s: hailuo_web text-to-video (no input image)",
                     job.get("id"))
            _enter_create_mode(page)
            _type_prompt(page, prompt)
            result = _submit_and_download(page, out_dir)
            result["strategy"] = "text_to_video"
            return result

        # Image-to-video: a different recorded path every run.
        rotator = StrategyRotator(self.id, VIDEO_STRATEGIES)
        strategy = rotator.pick()  # logged + persisted in agent_strategy_state.json
        log.info("job %s: hailuo_web via strategy '%s'",
                 job.get("id"), strategy["name"])
        strategy["run"](page, {"prompt": prompt, "input_path": input_path})
        result = _submit_and_download(page, out_dir)
        result["strategy"] = strategy["name"]  # recorded on the job result
        return result


# ═══════════════════════════════════════════════════════════════════════
# VIDEO STRATEGY LEDGER — distinct recorded paths to H3 generation.
# Same destination, different human-plausible routes: entry point, step
# order, and input modality (mouse vs keyboard) all vary per run.
# To add a new way: write a _strategy_* function, append one dict here.
# ═══════════════════════════════════════════════════════════════════════

def _strategy_reference_first(page, ctx):
    """Attach the image via Omni Reference FIRST, then type the motion
    prompt, then Create — reference-first ordering."""
    _enter_create_mode(page)
    _attach_reference(page, ctx["input_path"])
    _type_prompt(page, ctx["prompt"])


def _strategy_prompt_first(page, ctx):
    """Type the motion prompt first, attach the reference image after —
    reversed order vs reference_first."""
    _enter_create_mode(page)
    _type_prompt(page, ctx["prompt"] or "cinematic slow push-in, photorealistic")
    _attach_reference(page, ctx["input_path"])


def _strategy_aspect_first(page, ctx):
    """Pick the 9:16 aspect first (best-effort), then reference, prompt,
    Create — settings-first ordering for vertical Shorts output."""
    _enter_create_mode(page)
    _pick_vertical_aspect(page)
    _attach_reference(page, ctx["input_path"])
    _type_prompt(page, ctx["prompt"])


def _strategy_keyboard_flow(page, ctx):
    """Keyboard-driven: Tab to the prompt box, type, attach via the
    focused file input, Tab to Create, Enter — no mouse clicks."""
    page.keyboard.press("Tab")
    _pause()
    for _ in range(15):  # walk focus toward the prompt box
        try:
            focused = page.evaluate(
                "() => document.activeElement?.getAttribute?.('placeholder') || ''")
        except Exception:
            focused = ""
        if "Describe the video" in focused or "describe" in focused.lower():
            break
        page.keyboard.press("Tab")
        time.sleep(0.25)
    page.keyboard.type(ctx["prompt"] or "cinematic slow push-in", delay=15)
    _pause()
    # If keyboard nav missed, fall back to the click path.
    if _first(page, SELECTORS["prompt_box"]) is None:
        log.info("keyboard nav missed the prompt box; falling back to click")
        _enter_create_mode(page)
        _type_prompt(page, ctx["prompt"])
    _attach_reference(page, ctx["input_path"])


VIDEO_STRATEGIES = [
    {"name": "reference_first",
     "desc": "Omni Reference image attached first, then motion prompt, then Create.",
     "run": _strategy_reference_first},
    {"name": "prompt_first",
     "desc": "Motion prompt typed first, reference image attached after.",
     "run": _strategy_prompt_first},
    {"name": "aspect_first",
     "desc": "9:16 aspect picked first (best-effort), then reference, prompt, Create.",
     "run": _strategy_aspect_first},
    {"name": "keyboard_flow",
     "desc": "Keyboard-driven: Tab to prompt box, type, attach, Tab to Create, Enter.",
     "run": _strategy_keyboard_flow},
]


# ── shared step helpers (strategies compose these differently) ─────────

def _enter_create_mode(page):
    tab = _first(page, SELECTORS["create_video_tab"])
    if tab is not None:
        tab.click()
        _pause()
    # If the tab click missed, we may already be on the create view —
    # only fail when the prompt box is truly absent.
    if _first(page, SELECTORS["prompt_box"]) is None:
        raise ProviderError("Hailuo 'Create Video' view not found; tried: "
                            + ", ".join(SELECTORS["create_video_tab"]))


def _type_prompt(page, prompt):
    box = _first(page, SELECTORS["prompt_box"])
    if box is None:
        raise ProviderError("Hailuo prompt box not found; tried: "
                            + ", ".join(SELECTORS["prompt_box"]))
    box.click()
    _pause()
    page.keyboard.type(prompt or "cinematic slow push-in, photorealistic", delay=15)
    _pause()


def _attach_reference(page, input_path):
    """Omni Reference image (H3's image-to-video input). Best-effort click
    on the reference control, then the file input."""
    ref = _first(page, SELECTORS["omni_reference"])
    if ref is not None:
        try:
            ref.click()
            _pause()
        except Exception:
            pass
    upload = _first(page, SELECTORS["upload_input"])
    if upload is None:
        raise ProviderError("Hailuo reference upload input not found")
    upload.set_input_files(os.path.abspath(input_path))
    _pause()


def _pick_vertical_aspect(page):
    """Best-effort 9:16 for vertical Shorts. Never fatal if absent."""
    opt = _first(page, SELECTORS["aspect_option"])
    if opt is not None:
        try:
            opt.click()
            _pause()
            log.info("picked 9:16 aspect (best-effort)")
        except Exception:
            pass


def _submit_and_download(page, out_dir, timeout_s=1500):
    gen = _first(page, SELECTORS["create_button"])
    if gen is None:
        raise ProviderError("Hailuo Create button not found; tried: "
                            + ", ".join(SELECTORS["create_button"]))
    gen.click()

    # If clicking Create while logged out opened the login modal, fail loud
    # with a clear message instead of timing out.
    _pause()
    if _first(page, SELECTORS["login_markers"]) is not None:
        raise LoginRequired("Hailuo AI asked to log in on Create. "
                            "Log in once with --show-login, then retry.")

    # Generation takes minutes on the free tier (queued). Poll for a
    # playable <video> and sniff .mp4 responses as backup.
    deadline = time.time() + timeout_s  # 25 min max
    video_url = None
    seen = []  # insertion-ordered; last resort only

    def on_response(resp):
        url = resp.url
        if re.search(r"\.mp4(\?|$)", url) and url not in seen:
            seen.append(url)

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
            # Only the real <video> element's src counts as success. A stray
            # .mp4 in network traffic (UI preview, tutorial clip) must NOT end
            # the wait early — 'seen' is a last-resort fallback after the deadline.
            if video_url:
                break
            time.sleep(10)
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass

    if not video_url and seen:
        # Last resort: most recently observed .mp4 URL (insertion-ordered).
        video_url = seen[-1]
        print(f"[agent] [Hailuo] warning: no <video> element found; "
              f"falling back to last sniffed .mp4 URL.")
    if not video_url:
        raise ProviderError("timed out waiting for Hailuo render (25 min)")

    resp = page.request.get(video_url, timeout=120000)
    if resp.status != 200:
        raise ProviderError(f"video download failed: HTTP {resp.status}")
    out_path = os.path.join(out_dir, f"hailuo_{uuid.uuid4().hex[:10]}.mp4")
    with open(out_path, "wb") as f:
        f.write(resp.body())
    return {"result_path": os.path.abspath(out_path)}
