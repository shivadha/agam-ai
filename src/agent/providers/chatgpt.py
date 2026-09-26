"""
chatgpt.py — ChatGPT Go plan via chatgpt.com (user's paid consumer plan).

Kinds:
  * text  — hooks, scripts, descriptions, tags: type prompt, wait for the
            streamed reply to finish, return the last assistant message text.
  * image — "generate an image of ...": wait for the image, download it
            with an authenticated request.

chatgpt.com has aggressive bot detection; run with a persistent profile
that the user logged into once. Gentle pacing is built in.
"""
from __future__ import annotations

import os
import time
import uuid

from .base import FreeWebProvider, ProviderError, LoginRequired

SELECTORS = {
    "prompt_box": [
        '#prompt-textarea',                     # VERIFY (long-standing)
        'div[role="textbox"]',                  # VERIFY
        'div[contenteditable="true"]',          # VERIFY
    ],
    "send_button": [
        'button[data-testid="send-button"]',    # VERIFY
        'button[aria-label="Send prompt"]',     # VERIFY
    ],
    "assistant_turn": [
        'div[data-message-author-role="assistant"]',  # VERIFY
    ],
    "stop_button": [
        'button[data-testid="stop-button"]',    # VERIFY
    ],
    "response_image": [
        'div[data-message-author-role="assistant"] img',  # VERIFY
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


_CHATGPT_ERROR_MARKERS = (
    "something went wrong", "try again", "error generating",
    "unable to load", "network error", "rate limit", "too many requests",
    "try again later",
)


class ChatGPTProvider(FreeWebProvider):
    id = "chatgpt_go"
    display_name = "ChatGPT Go (web)"
    login_url = "https://chatgpt.com/"
    kinds = ("text", "image")
    balance_recipe = {"api_patterns": ["backend-api"],
                      "note": "ChatGPT web rarely exposes a numeric balance; "
                              "usage counting applies."}

    def needs_login(self, page) -> bool:
        try:
            page.goto(self.login_url, wait_until="domcontentloaded", timeout=45000)
            _pause()
            body = page.locator("body").inner_text(timeout=10000).lower()
            return ("log in" in body or "sign up" in body) and "new chat" not in body
        except Exception:
            return True

    def _submit(self, page, prompt: str):
        box = _first(page, SELECTORS["prompt_box"])
        if box is None:
            raise ProviderError("chatgpt prompt box not found; tried: "
                                + ", ".join(SELECTORS["prompt_box"]))
        box.click()
        _pause()
        page.keyboard.type(prompt, delay=14)
        _pause()
        send = _first(page, SELECTORS["send_button"])
        if send is not None:
            send.click()
        else:
            page.keyboard.press("Enter")
        _pause()

    def _wait_until_done(self, page, timeout: int = 420):
        """Wait until the stop button disappears (streaming finished)."""
        deadline = time.time() + timeout
        stop_sel = ", ".join(SELECTORS["stop_button"])
        while time.time() < deadline:
            try:
                if page.locator(stop_sel).count() == 0:
                    time.sleep(2)  # settle
                    return
            except Exception:
                pass
            time.sleep(3)
        raise ProviderError("timed out waiting for chatgpt reply")

    def _last_assistant_text(self, page) -> str:
        turns = page.locator(", ".join(SELECTORS["assistant_turn"])).all()
        if not turns:
            raise ProviderError("no assistant reply found")
        try:
            text = turns[-1].inner_text(timeout=15000).strip()
        except Exception as e:
            raise ProviderError(f"could not read assistant reply: {e}")
        # An error banner ("Something went wrong") is not a result — the
        # orchestrator would otherwise happily use it as the video script.
        low = text.lower()
        if any(m in low for m in _CHATGPT_ERROR_MARKERS):
            raise ProviderError(
                f"chatgpt showed an error instead of a reply: {text[:120]}")
        if not text:
            raise ProviderError("chatgpt returned an empty reply")
        return text

    def generate(self, page, job: dict, out_dir: str) -> dict:
        kind = job.get("kind", "text")
        prompt = (job.get("prompt") or "").strip()
        if not prompt:
            raise ProviderError("empty prompt for chatgpt job")

        page.goto(self.login_url, wait_until="domcontentloaded", timeout=60000)
        if self.needs_login(page):
            raise LoginRequired("chatgpt shows logged-out state")
        # Fresh chat so replies don't mix with history.
        try:
            page.keyboard.press("Control+Shift+o")  # new chat shortcut
            _pause()
        except Exception:
            pass

        if kind == "image" and "image" not in prompt.lower():
            prompt = f"Generate an image: {prompt}"
        self._submit(page, prompt)

        if kind == "image":
            deadline = time.time() + 300
            img_url = None
            while time.time() < deadline:
                imgs = page.locator(
                    ", ".join(SELECTORS["response_image"])).all()
                for im in imgs:
                    try:
                        src = im.get_attribute("src")
                        if src and src.startswith("http") and "avatar" not in src.lower():
                            img_url = src
                            break
                    except Exception:
                        continue
                if img_url:
                    break
                time.sleep(3)
            if not img_url:
                # Maybe it answered in text instead — return that.
                try:
                    self._wait_until_done(page, timeout=60)
                    return {"result_text": self._last_assistant_text(page)}
                except Exception:
                    pass
                raise ProviderError("timed out waiting for chatgpt image")
            resp = page.request.get(img_url, timeout=60000)
            if resp.status != 200:
                raise ProviderError(f"image download failed: HTTP {resp.status}")
            out_path = os.path.join(out_dir, f"gpt_{uuid.uuid4().hex[:10]}.png")
            with open(out_path, "wb") as f:
                f.write(resp.body())
            return {"result_path": os.path.abspath(out_path)}

        # text kind
        self._wait_until_done(page)
        return {"result_text": self._last_assistant_text(page)}
