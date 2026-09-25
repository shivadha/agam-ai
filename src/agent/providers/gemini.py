"""
gemini.py — free image generation via gemini.google.com (user's Google AI plan).

Flow: open Gemini -> type prompt -> send -> wait for the generated image ->
download it with an authenticated request.

NOTE: selectors below are best-effort from the public web UI and are marked
# VERIFY. Google changes this DOM regularly. If generate() fails it raises
ProviderError naming the selector that broke — update SELECTORS and retry.
"""
from __future__ import annotations

import os
import time
import uuid

from .base import FreeWebProvider, ProviderError, LoginRequired

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
    kinds = ("image",)
    balance_recipe = {"api_patterns": ["batchexecute"],
                      "regex": r"(\d+)\s*(?:images?|generations?)\s*(?:left|remaining|per day)"}

    # ── login ──────────────────────────────────────────────────────────
    def needs_login(self, page) -> bool:
        try:
            page.goto(self.login_url, wait_until="domcontentloaded", timeout=45000)
            _pause()
            body = page.locator("body").inner_text(timeout=10000).lower()
            return ("sign in" in body and "ask gemini" not in body)
        except Exception:
            return True

    # ── image generation ───────────────────────────────────────────────
    def generate(self, page, job: dict, out_dir: str) -> dict:
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
