"""
scout.py — discovers new free AI generation sites and proposes them as
provider candidates.

Fetching goes through Scrapling (D4Vinci/Scrapling) when installed, in a
fast -> stealth fallback chain that mirrors the agent's own A->B->C
philosophy:

  tier "fast"    Fetcher — TLS-impersonated HTTP, quick and light.
  tier "stealth" StealthyFetcher — a real (camoufox) browser that bypasses
                 Cloudflare Turnstile out of the box.
  tier "legacy"  plain urllib — used when Scrapling isn't installed, or
                 when both Scrapling tiers fail. The scout never hard-
                 depends on Scrapling.

Parsing uses Scrapling's adaptive selectors: the first successful parse
banks each element's signature (auto_save=True); later runs relocate the
elements by similarity even if the site's markup drifted (adaptive=True),
so a DuckDuckGo/Reddit redesign doesn't silently kill the scout.

Every fresh candidate also gets a light homepage pre-check (quota hints,
signup requirement) so approvals in the Free AI tab are higher quality.

Findings go to the free_candidates table as 'pending'. Nothing becomes a
live provider until the user approves it in the Free AI admin tab — the
scout proposes, the human disposes.

Usage:
  python -m src.agent.scout            # one discovery sweep

One-time setup (Windows):
  pip install "scrapling[fetchers]"
  scrapling install                    # downloads the stealth browser
"""
from __future__ import annotations

import html as htmlmod
import json
import logging
import os
import re
import sys
import time
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

from src.backend import free_providers as ledger

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scout")

# ── Scrapling (optional) ──────────────────────────────────────────────────
try:
    from scrapling.parser import Selector as _ScraplingSelector
except Exception:
    _ScraplingSelector = None  # type: ignore

try:
    from scrapling.fetchers import Fetcher, StealthyFetcher
    Fetcher.adaptive = True
    StealthyFetcher.adaptive = True
    SCRAPLING_AVAILABLE = True
except Exception:  # not installed / no [fetchers] extras
    Fetcher = StealthyFetcher = None  # type: ignore
    SCRAPLING_AVAILABLE = False

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AgamScout/1.0"}

SUBREDDITS = ["LocalLLaMA", "artificial", "aivideo", "StableDiffusion", "ChatGPT"]
REDDIT_QUERIES = [
    "free image generator",
    "free video generator",
    "free credits AI",
    "free tier text to image",
]
DDG_QUERIES = [
    "free AI image generator no sign up",
    "free AI video generator free credits",
    "free text to image website 2026",
]

SKIP_DOMAINS = {
    "reddit.com", "old.reddit.com", "google.com", "youtube.com", "youtu.be",
    "twitter.com", "x.com", "facebook.com", "instagram.com", "github.com",
    "discord.com", "discord.gg", "t.me", "wikipedia.org", "medium.com",
}

BLOCK_MARKERS = (
    "just a moment", "checking your browser", "verify you are human",
    "access denied", "attention required", "cf-chl", "captcha",
)

SIGNUP_RES = (
    r"sign\s*up (to|for|and) (generate|create|start|use)",
    r"create (a |your )?free account",
    r"register to (generate|use|access)",
    r"log\s*in to (generate|continue|use)",
)


def _domain(url: str) -> str:
    try:
        d = urllib.parse.urlparse(url).netloc.lower()
        return d[4:] if d.startswith("www.") else d
    except Exception:
        return ""


def _quota_hint(text: str) -> str:
    text = text or ""
    m = re.search(r"(\d[\d,]*)\s*free\s*(credits?|images?|videos?|generations?)",
                  text, re.I)
    if m:
        return f"{m.group(1)} free {m.group(2)}"
    if re.search(r"free\s*(tier|plan|credits?|trial)", text, re.I):
        return "free tier mentioned"
    return ""


def _kinds_for(query: str) -> list:
    q = query.lower()
    kinds = []
    if "video" in q:
        kinds.append("video")
    if "image" in q or "picture" in q or "text to image" in q:
        kinds.append("image")
    return kinds or ["image"]


# ── fetch tiers ───────────────────────────────────────────────────────────
def _fetch_fast(url: str, timeout: int = 20):
    """Tier 1: Scrapling Fetcher — TLS-impersonated HTTP."""
    try:
        return Fetcher.get(url, timeout=timeout)
    except TypeError:
        return Fetcher.get(url)


def _fetch_stealth(url: str, timeout: int = 40):
    """Tier 2: Scrapling StealthyFetcher — real browser, Cloudflare bypass."""
    try:
        return StealthyFetcher.fetch(url, headless=True, network_idle=True,
                                     timeout=timeout)
    except TypeError:
        return StealthyFetcher.fetch(url, headless=True)


def _fetch_legacy(url: str, timeout: int = 20):
    """Tier 3: plain urllib, wrapped in a Scrapling Selector so downstream
    parsing uses one uniform interface."""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", errors="replace")
    if _ScraplingSelector is not None:
        return _ScraplingSelector(content=raw, url=url, adaptive=True)
    return _RawPage(raw, url)


class _RawPage:
    """Minimal page stand-in when even the Scrapling parser is missing."""
    def __init__(self, text: str, url: str):
        self.text = text
        self.url = url
        self.status = 200

    def css(self, selector: str, **kwargs):
        return []


def _page_text(page) -> str:
    t = (getattr(page, "text", "") or "").strip()
    if t:
        return t
    try:
        return " ".join(page.css("::text").getall())
    except Exception:
        return ""


def _is_blocked(page) -> bool:
    if page is None:
        return True
    try:
        if getattr(page, "status", 200) in (403, 429, 503):
            return True
    except Exception:
        pass
    blob = _page_text(page)[:4000].lower()
    if len(blob) < 200:
        return True
    return any(m in blob for m in BLOCK_MARKERS)


def _fetch_page(url: str, timeout: int = 20):
    """Fast -> stealth -> legacy. Returns (page, tier)."""
    if SCRAPLING_AVAILABLE:
        for tier, fn in (("fast", _fetch_fast), ("stealth", _fetch_stealth)):
            try:
                page = fn(url, timeout)
            except Exception as e:
                log.debug("scout tier %s failed for %s: %s", tier, url[:60], e)
                continue
            if not _is_blocked(page):
                return page, tier
            log.info("scout tier %s blocked on %s, escalating",
                     tier, _domain(url))
    try:
        return _fetch_legacy(url, timeout), "legacy"
    except Exception as e:
        log.debug("scout legacy fetch failed %s: %s", url[:60], e)
        return None, "none"


def _adaptive_css(page, selector: str):
    """Parse with banking: first hit saves the element signature, later
    runs relocate by similarity if markup drifted."""
    try:
        els = page.css(selector, auto_save=True)
        if not els:
            els = page.css(selector, adaptive=True)
        return els
    except TypeError:
        return page.css(selector)
    except Exception:
        return []


def _unwrap_ddg(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    try:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        if "uddg" in qs and qs["uddg"]:
            return qs["uddg"][0]
    except Exception:
        pass
    return href


# ── sweeps ────────────────────────────────────────────────────────────────
def reddit_sweep() -> list:
    found = []
    for sub in SUBREDDITS:
        for q in REDDIT_QUERIES:
            url = ("https://www.reddit.com/r/" + sub + "/search.json?"
                   + urllib.parse.urlencode(
                       {"q": q, "restrict_sr": "1", "sort": "new", "limit": 25}))
            page, tier = _fetch_page(url)
            if page is None:
                _note_source_result("reddit", tier, False)
                continue
            try:
                data = json.loads(_page_text(page))
            except Exception:
                _note_source_result("reddit", tier, False)
                continue
            n = 0
            for child in data.get("data", {}).get("children", []):
                d = child.get("data", {})
                title = d.get("title", "")
                link = d.get("url", "")
                dom = _domain(link)
                if not dom or dom in SKIP_DOMAINS:
                    continue
                found.append({
                    "name": (title[:80] or dom),
                    "url": f"https://{dom}/",
                    "kinds": _kinds_for(q),
                    "quota_hint": _quota_hint(title + " " + d.get("selftext", "")),
                    "source": f"reddit r/{sub}",
                    "source_url": "https://www.reddit.com" + d.get("permalink", ""),
                })
                n += 1
            _note_source_result("reddit", tier, n > 0)
            time.sleep(1)
    return found


def ddg_sweep() -> list:
    found = []
    for q in DDG_QUERIES:
        url = ("https://html.duckduckgo.com/html/?"
               + urllib.parse.urlencode({"q": q}))
        page, tier = _fetch_page(url)
        if page is None:
            _note_source_result("duckduckgo", tier, False)
            continue
        n = 0
        for el in _adaptive_css(page, "a.result__a"):
            try:
                href = _unwrap_ddg(el.attrib.get("href", ""))
                label = htmlmod.unescape(
                    " ".join(el.css("::text").getall())).strip()
            except Exception:
                continue
            dom = _domain(href)
            if not dom or dom in SKIP_DOMAINS or "duckduckgo" in dom:
                continue
            found.append({
                "name": (label[:80] or dom),
                "url": f"https://{dom}/",
                "kinds": _kinds_for(q),
                "quota_hint": _quota_hint(label),
                "source": "duckduckgo",
                "source_url": "",
            })
            n += 1
        _note_source_result("duckduckgo", tier, n > 0)
        time.sleep(1)
    return found


# ── candidate pre-check ───────────────────────────────────────────────────
def precheck(url: str) -> dict:
    """Light homepage fetch: enrich quota hints, detect signup walls.
    Never raises; failures just mean 'no extra info'."""
    info = {"quota_hint": "", "needs_signup": False, "reachable": False}
    try:
        page, _tier = _fetch_page(url if url.endswith("/") else url + "/",
                                  timeout=15)
        if page is None:
            return info
        info["reachable"] = True
        text = _page_text(page)
        hint = _quota_hint(text)
        needs_signup = any(re.search(rx, text, re.I) for rx in SIGNUP_RES)
        info["needs_signup"] = needs_signup
        parts = []
        if hint:
            parts.append(hint)
        if needs_signup:
            parts.append("signup required")
        elif hint:
            parts.append("no signup wall detected")
        info["quota_hint"] = " · ".join(parts)
    except Exception as e:
        log.debug("precheck failed for %s: %s", url[:60], e)
    return info


# ── memory: the scout learns which tiers/sources work ─────────────────────
_source_stats: dict = {}


def _note_source_result(source: str, tier: str, ok: bool) -> None:
    st = _source_stats.setdefault(source, {"tiers": {}, "fails": 0})
    st["tiers"][tier] = st["tiers"].get(tier, 0) + (1 if ok else 0)
    if not ok:
        st["fails"] += 1


def _learn_from_run() -> None:
    try:
        from src.agent import memory as agent_memory
        for source, st in _source_stats.items():
            wins = [(t, c) for t, c in st["tiers"].items() if c > 0]
            if wins:
                best = max(wins, key=lambda x: x[1])[0]
                agent_memory.remember(
                    "scout", "preference",
                    f"fetcher tier '{best}' works for {source}", confidence=0.6)
            elif st["fails"] >= 3:
                agent_memory.remember(
                    "scout", "lesson",
                    f"{source} unreachable via all fetch tiers "
                    f"({st['fails']} failures) — source may be dead or "
                    f"blocking datacenter IPs", confidence=0.7)
    except Exception as e:
        log.debug("scout memory update failed: %s", e)


def run_scout() -> dict:
    _source_stats.clear()
    seen_urls: set[str] = set()
    added = 0
    prechecked = 0
    candidates = reddit_sweep() + ddg_sweep()
    for c in candidates:
        if c["url"] in seen_urls:
            continue
        seen_urls.add(c["url"])
        # Enrich brand-new candidates with a homepage pre-check.
        info = precheck(c["url"])
        if info["quota_hint"]:
            prechecked += 1
            base = c.get("quota_hint") or ""
            c["quota_hint"] = (base + " · " + info["quota_hint"]
                               if base else info["quota_hint"])
        rid = ledger.add_candidate(**c)
        if rid:
            added += 1
            log.info("[scout] candidate: %s (%s) [%s]", c["name"], c["url"],
                     c.get("quota_hint") or "no quota info")
        time.sleep(0.5)
    _learn_from_run()
    log.info("[scout] scrapling %s",
             "available" if SCRAPLING_AVAILABLE else "missing — legacy mode")
    return {"scanned": len(candidates), "added": added,
            "prechecked": prechecked}


if __name__ == "__main__":
    result = run_scout()
    print(f"Scout done: {result['scanned']} hits, {result['added']} new "
          f"candidates ({result['prechecked']} pre-checked).")
