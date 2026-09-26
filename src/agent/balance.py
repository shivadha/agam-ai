"""
balance.py — live credit-balance reading for free-web providers.

Strategy (in order), driven by the provider's balance_recipe from the DB:
  1. API-response sniffing: while the provider generates, the agent records
     network responses whose URL matches recipe["api_patterns"]; we then
     search those JSON bodies for credit-like fields. Most reliable.
  2. DOM selector: recipe["dom_selector"] text -> first integer.
  3. Regex: recipe["regex"] (or a default) over the page's visible text.

Returns an int or None. Never raises — a failed read just means the ledger
falls back to usage counting.
"""
from __future__ import annotations

import json
import logging
import re

log = logging.getLogger("free-agent")

CREDIT_KEYS = (
    "credits", "remaining", "remaining_credits", "balance",
    "image_credits", "video_credits", "generation_credits",
    "quota_remaining", "allowance", "allowance_remaining",
    "daily_remaining", "credits_remaining",
)

DEFAULT_REGEXES = [
    r"(\d+)\s*credits?\s*(?:left|remaining)?",
    r"(\d+)\s*(?:images?|videos?|generations?)\s*(?:left|remaining|per day)",
]


class ResponseSniffer:
    """Records response bodies whose URL matches any pattern."""

    def __init__(self, patterns: list[str] | None):
        self.patterns = [p.lower() for p in (patterns or [])]
        self.captured: list[tuple[str, str]] = []

    def _on_response(self, resp):
        try:
            url = resp.url.lower()
            if not any(p in url for p in self.patterns):
                return
            ctype = (resp.headers.get("content-type") or "").lower()
            if "json" not in ctype and "text" not in ctype:
                return
            body = resp.text()
            if body:
                self.captured.append((resp.url, body[:20000]))
        except Exception:
            pass

    def attach(self, page):
        if self.patterns:
            page.on("response", self._on_response)

    def detach(self, page):
        try:
            page.remove_listener("response", self._on_response)
        except Exception:
            pass

    def find_balance(self) -> int | None:
        for url, body in self.captured:
            try:
                data = json.loads(body)
            except Exception:
                continue
            found = _search_credit_keys(data)
            if found is not None:
                log.info("[balance] api-sniff %s -> %s", url[:80], found)
                return found
        return None


def _search_credit_keys(obj, depth: int = 0) -> int | None:
    """Two-pass search: first prefer keys with remaining/left semantics
    (a plan-limit key like 'max_credits' must never be read as the balance),
    then fall back to any credit-ish key."""
    if depth > 4:
        return None
    if isinstance(obj, dict):
        weak = None
        for k, v in obj.items():
            kl = str(k).lower()
            if any(ck in kl for ck in CREDIT_KEYS) and isinstance(v, (int, float)):
                iv = int(v)
                if 0 <= iv < 1000000:
                    # Skip obvious plan-limit keys — they are not the balance.
                    if any(bad in kl for bad in ("max_", "total", "limit", "plan_")):
                        continue
                    if any(good in kl for good in ("remaining", "left", "available")):
                        return iv
                    if weak is None:
                        weak = iv
            r = _search_credit_keys(v, depth + 1)
            if r is not None:
                return r
        return weak
    elif isinstance(obj, list):
        for v in obj[:20]:
            r = _search_credit_keys(v, depth + 1)
            if r is not None:
                return r
    return None


def _first_int(text: str, patterns: list[str]) -> int | None:
    for pat in patterns:
        try:
            m = re.search(pat, text or "", re.IGNORECASE)
        except re.error:
            continue
        if m:
            try:
                return int(m.group(1))
            except (ValueError, IndexError):
                continue
    return None


def read_balance(page, recipe: dict, sniffer: ResponseSniffer | None = None) -> int | None:
    recipe = recipe or {}
    try:
        # 1. API sniffing
        if sniffer is not None:
            bal = sniffer.find_balance()
            if bal is not None:
                return bal
        # 2. DOM selector
        sel = (recipe.get("dom_selector") or "").strip()
        if sel:
            try:
                text = page.locator(sel).first.inner_text(timeout=8000)
                bal = _first_int(text, [r"(\d[\d,]*)"])
                if bal is not None:
                    log.info("[balance] dom %s -> %s", sel, bal)
                    return bal
            except Exception as e:
                log.debug("[balance] dom selector failed: %s", e)
        # 3. regex over visible text
        try:
            body = page.locator("body").inner_text(timeout=8000)
        except Exception:
            body = ""
        patterns = [recipe["regex"]] if recipe.get("regex") else DEFAULT_REGEXES
        bal = _first_int(body, patterns)
        if bal is not None:
            log.info("[balance] regex -> %s", bal)
        return bal
    except Exception as e:
        log.debug("[balance] read failed: %s", e)
        return None
