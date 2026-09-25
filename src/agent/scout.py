"""
scout.py — discovers new free AI generation sites and proposes them as
provider candidates.

Sources (all free, no API keys):
  * Reddit public JSON search across AI subreddits.
  * DuckDuckGo HTML results.

Findings go to the free_candidates table as 'pending'. Nothing becomes a
live provider until the user approves it in the Free AI admin tab — the
scout proposes, the human disposes.

Usage:
  python -m src.agent.scout            # one discovery sweep
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


def _fetch(url: str, timeout: int = 20) -> str | None:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        log.debug("fetch failed %s: %s", url[:80], e)
        return None


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


def reddit_sweep() -> list:
    found = []
    for sub in SUBREDDITS:
        for q in REDDIT_QUERIES:
            url = ("https://www.reddit.com/r/" + sub + "/search.json?"
                   + urllib.parse.urlencode(
                       {"q": q, "restrict_sr": "1", "sort": "new", "limit": 25}))
            raw = _fetch(url)
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
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
            time.sleep(1)
    return found


def ddg_sweep() -> list:
    found = []
    for q in DDG_QUERIES:
        url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": q})
        raw = _fetch(url)
        if not raw:
            continue
        for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                             raw, re.S):
            href, label = m.group(1), htmlmod.unescape(re.sub(r"<[^>]+>", "", m.group(2)))
            if href.startswith("//"):
                href = "https:" + href
            # DDG wraps links in a redirect; unwrap it.
            parsed = urllib.parse.urlparse(href)
            qs = urllib.parse.parse_qs(parsed.query)
            if "uddg" in qs:
                href = qs["uddg"][0]
            dom = _domain(href)
            if not dom or dom in SKIP_DOMAINS or "duckduckgo" in dom:
                continue
            found.append({
                "name": (label.strip()[:80] or dom),
                "url": f"https://{dom}/",
                "kinds": _kinds_for(q),
                "quota_hint": _quota_hint(label),
                "source": "duckduckgo",
                "source_url": "",
            })
        time.sleep(1)
    return found


def run_scout() -> dict:
    seen_urls: set[str] = set()
    added = 0
    candidates = reddit_sweep() + ddg_sweep()
    for c in candidates:
        if c["url"] in seen_urls:
            continue
        seen_urls.add(c["url"])
        rid = ledger.add_candidate(**c)
        if rid:
            added += 1
            log.info("[scout] candidate: %s (%s)", c["name"], c["url"])
    return {"scanned": len(candidates), "added": added}


if __name__ == "__main__":
    result = run_scout()
    print(f"Scout done: {result['scanned']} hits, {result['added']} new candidates.")
