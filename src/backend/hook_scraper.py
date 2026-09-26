"""hook_scraper.py — mine real viral hooks from trending video titles.

Why: the LLM hook route fails whenever no free provider is reachable, and the
template fallback always produces the same dull lines. Real, currently-viral
video titles for the SAME topic are proven hooks — we scrape YouTube search
results for "<topic> shorts", extract the top titles, and adapt them into
<=8-word hook lines.

Fetch: reuses the scout's fast -> stealth -> legacy chain (Scrapling
Fetcher -> StealthyFetcher -> urllib) from src/agent/scout.py, so
Cloudflare/bot walls escalate automatically.

Cache: data/hook_cache.json, 24h per topic — repeated runs don't re-scrape.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CACHE_FILE = os.path.join(DATA_DIR, "hook_cache.json")
CACHE_TTL = 24 * 3600

_YT_SEARCH = "https://www.youtube.com/results?search_query="

# "title":{"runs":[{"text":"Real Title Here"
_TITLE_RE = re.compile(r'"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"')
_EMOJI_RE = re.compile(r"[\U00010000-\U0010ffff\u2600-\u27bf\u2b00-\u2bff\ufe0f]", flags=re.UNICODE)
_WS_RE = re.compile(r"\s+")


def _load_cache() -> dict:
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except Exception as e:
        print(f"[hook_scraper] cache write note: {e}")


def _clean_title(raw: str) -> str:
    t = raw.encode().decode("unicode_escape", errors="ignore") if "\\" in raw else raw
    t = _EMOJI_RE.sub("", t)
    t = re.sub(r"#\w+", "", t)                       # hashtags
    t = re.split(r"\s[|\-–—]\s", t)[0]               # "Title | Channel" / "Title - Channel"
    t = _WS_RE.sub(" ", t).strip(" -|–—:;,.\"'")
    return t


def mine_titles(topic: str, limit: int = 12) -> list[str]:
    """Scrape YouTube search titles for '<topic> shorts'. Cached 24h."""
    key = re.sub(r"\W+", "_", topic.lower()).strip("_")[:60] or "general"
    cache = _load_cache()
    hit = cache.get(key)
    if hit and time.time() - hit.get("ts", 0) < CACHE_TTL and hit.get("titles"):
        print(f"[hook_scraper] cache hit for '{topic}' ({len(hit['titles'])} titles)")
        return hit["titles"][:limit]

    titles: list[str] = []
    try:
        from src.agent.scout import _fetch_page, _page_text
    except Exception as e:
        print(f"[hook_scraper] scout import failed: {e}")
        return []

    query = urllib.parse.quote_plus(f"{topic} shorts")
    page, tier = _fetch_page(_YT_SEARCH + query, timeout=25)
    if page is None:
        print(f"[hook_scraper] all fetch tiers failed for '{topic}'")
        return []
    print(f"[hook_scraper] fetched via tier '{tier}' for '{topic}'")

    blob = _page_text(page)
    seen = set()
    for m in _TITLE_RE.finditer(blob):
        t = _clean_title(m.group(1))
        words = t.split()
        if len(words) < 3 or len(words) > 25:
            continue
        low = t.lower()
        if low in seen or "youtube" == low:
            continue
        seen.add(low)
        titles.append(t)
        if len(titles) >= limit:
            break

    if titles:
        cache[key] = {"ts": time.time(), "titles": titles}
        _save_cache(cache)
        print(f"[hook_scraper] mined {len(titles)} titles for '{topic}'")
    else:
        print(f"[hook_scraper] no titles extracted for '{topic}'")
    return titles


def adapt_title_to_hook(title: str) -> str:
    """Squeeze a video title into a <=8-word scroll-stopping hook line."""
    words = title.split()
    if len(words) > 8:
        hook = " ".join(words[:8]).rstrip(",;:") + "..."
    else:
        hook = title
    # Hooks hit harder in title case with the punch up front; keep original
    # casing but ensure it doesn't read like a sentence fragment ending mid-word.
    return hook.strip()


def _looks_valid(hook: str) -> bool:
    if not hook or len(hook.split()) > 8:
        return False
    return not hook.lower().startswith(
        ("today we", "hello", "welcome", "in this video", "hi ", "hey guys"))


def best_scraped_hook(topic: str, category: str = "") -> tuple[str | None, str]:
    """Return (hook, raw_title) — the best scraped hook, or (None, '')."""
    query = topic or category or "AI"
    for title in mine_titles(query):
        hook = adapt_title_to_hook(title)
        if _looks_valid(hook):
            print(f"[hook_scraper] hook from '{title[:50]}...' -> '{hook}'")
            return hook, title
    return None, ""
