"""
veo.py — free image-to-video via Google Flow (labs.google/fx, Veo free tier).

Flow: open Flow -> new project -> "Frames to video" (image-to-video) ->
upload input image -> enter prompt -> generate -> wait (minutes) ->
download the mp4 with an authenticated request.

Veo's free tier is only a few videos/day and generation takes minutes per
clip — the agent waits patiently and the job stays 'running' meanwhile.

NOTE: Flow's DOM changes often; selectors marked # VERIFY. Failures raise
ProviderError naming the broken selector.
"""
from __future__ import annotations

import os
import re
import time
import uuid

from .base import FreeWebProvider, ProviderError, LoginRequired

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

        new_proj = _first(page, SELECTORS["new_project"])
        if new_proj:
            new_proj.click()
            _pause()

        if input_path and os.path.exists(input_path):
            # Image-to-video path.
            mode = _first(page, SELECTORS["frames_to_video"])
            if mode is None:
                raise ProviderError("Flow 'Frames to video' mode not found; tried: "
                                    + ", ".join(SELECTORS["frames_to_video"]))
            mode.click()
            _pause()
            upload = _first(page, SELECTORS["upload_input"])
            if upload is None:
                raise ProviderError("Flow file-upload input not found")
            upload.set_input_files(os.path.abspath(input_path))
            _pause()
        else:
            mode = _first(page, SELECTORS["text_to_video"])
            if mode:
                mode.click()
                _pause()

        box = _first(page, SELECTORS["prompt_box"])
        if box is None:
            raise ProviderError("Flow prompt box not found; tried: "
                                + ", ".join(SELECTORS["prompt_box"]))
        box.click()
        _pause()
        page.keyboard.type(prompt or "cinematic slow push-in, photorealistic", delay=15)
        _pause()

        gen = _first(page, SELECTORS["generate_button"])
        if gen is None:
            raise ProviderError("Flow Generate button not found")
        gen.click()

        # Generation takes minutes. Poll for a playable <video>.
        deadline = time.time() + 1500  # 25 min max
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
