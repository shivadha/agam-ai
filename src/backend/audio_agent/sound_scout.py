"""
audio_agent/sound_scout.py

Scrapling-powered sound discovery for the Audio Intelligence Agent.

Reuses the provider scout's fetch chain (src/agent/scout.py):

  fast    — TLS-impersonated Fetcher, quick and light
  stealth — camoufox browser, bypasses Cloudflare Turnstile
  legacy  — plain urllib when Scrapling isn't installed

plus adaptive selectors, so a site redesign doesn't silently kill discovery.

Sources:
  1. MyInstants trending memes — https://www.myinstants.com/en/trending/
  2. Pixabay sound effects     — https://pixabay.com/sound-effects/search/<query>/
  3. Pixabay music              — https://pixabay.com/music/search/<query>/
  4. Mixkit free SFX            — https://mixkit.co/free-sound-effects/<category>/

Every discover_* function returns a list of normalized records::

    {name, audio_url, page_url, source, category, subcategory, tags,
     emotion, energy_level}

Discovery only finds sounds — downloading/indexing stays in scraper.py
(AudioScraper), which owns the library. Nothing here touches the network
except through the scout's fetch chain, and every source is best-effort:
one source failing never aborts the others.
"""

from __future__ import annotations

import logging
import re
import time
import urllib.parse

log = logging.getLogger(__name__)

try:
    from src.agent.scout import _fetch_page, _adaptive_css, _is_blocked
    _SCOUT_AVAILABLE = True
except Exception as e:  # pragma: no cover - defensive
    log.warning("sound_scout: scout fetch chain unavailable (%s)", e)
    _SCOUT_AVAILABLE = False
    _fetch_page = None
    _adaptive_css = None
    _is_blocked = None


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _page_html(page) -> str:
    """Best-effort raw HTML from any scout page object."""
    for attr in ("html", "text"):
        try:
            val = getattr(page, attr, None)
            if callable(val):
                val = val()
            if val and len(str(val)) > 500:
                return str(val)
        except Exception:
            continue
    try:
        return str(page)
    except Exception:
        return ""


_CHROME_WORDS = {"play", "pause", "download", "share", "copy", "copy link",
                 "embed", "report", "like", "likes", "views", "free", "more"}


def _nearest_title(html: str, pos: int, window: int = 2500) -> str:
    """Find the most plausible title preceding position ``pos`` in HTML."""
    start = max(0, pos - window)
    chunk = html[start:pos]
    # Prefer explicit title/alt attributes closest to the match.
    candidates = []
    for m in re.finditer(
        r'(?:title|alt)="([^"]{3,120})"|'
        r'<h[1-3][^>]*>([^<]{3,120})</h[1-3]>|'
        r'class="instant-name"[^>]*>([^<]{3,120})<',
        chunk,
    ):
        text = next((g for g in m.groups() if g), "")
        text = re.sub(r"\s+", " ", text).strip()
        if not text or len(text) < 3:
            continue
        if text.lower() in _CHROME_WORDS:
            continue  # UI chrome ("Play", "Download", ...) — not a title
        candidates.append((m.start(), text))
    if not candidates:
        return ""
    # Closest match wins.
    candidates.sort(key=lambda c: c[0], reverse=True)
    return candidates[0][1]


def _clean_name(name: str, fallback: str = "Untitled sound") -> str:
    name = re.sub(r"\s+", " ", (name or "")).strip(" -–—|")
    if len(name) < 3:
        return fallback
    return name[:120]


# ---------------------------------------------------------------------------
# Emotion / tag inference (keyword based, same convention as scraper.py)
# ---------------------------------------------------------------------------

_EMOTION_KEYWORDS = [
    ("fear", ["scary", "horror", "creepy", "ghost", "jump", "scream", "terror"]),
    ("shock", ["boom", "explosion", "crash", "bang", "impact", "smash", "hit"]),
    ("funny", ["funny", "haha", "lol", "bruh", "fail", "wah", "meme", "fart",
               "boing", "silly", "comedy"]),
    ("suspense", ["suspense", "tension", "dramatic", "sting", "cinematic",
                 "dark", "mystery"]),
    ("energetic", ["win", "success", "level", "achievement", "yay", "celebrate",
                  "party", "hype", "pump", "epic", "phonk", "edm", "drop"]),
    ("calm", ["lofi", "chill", "relax", "ambient", "calm", "sleep", "study",
              "soft", "gentle"]),
    ("inspiration", ["uplift", "motivat", "inspir", "hope", "rise", "anthem",
                    "corporate"]),
]

_STOP_WORDS = {"a", "the", "is", "in", "of", "and", "or", "to", "for", "with",
              "on", "by", "sound", "effect", "effects", "audio", "mp3"}


def _guess_emotion(name: str) -> str:
    lowered = name.lower()
    for emotion, keywords in _EMOTION_KEYWORDS:
        if any(k in lowered for k in keywords):
            return emotion
    return "energetic"


def _extract_tags(name: str, extra: tuple = ()) -> list:
    words = re.sub(r"[-_]", " ", name.lower()).split()
    tags = [w for w in words if len(w) > 2 and w not in _STOP_WORDS]
    tags.extend(extra)
    tags.append("trending" if "trending" in extra else "scraped")
    seen, out = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:10]


def _guess_energy(name: str, emotion: str) -> int:
    lowered = name.lower()
    if any(k in lowered for k in ["explosion", "drop", "phonk", "epic", "boom"]):
        return 9
    if any(k in lowered for k in ["chill", "lofi", "ambient", "soft", "calm"]):
        return 3
    return {"fear": 8, "shock": 9, "funny": 6, "suspense": 7,
            "energetic": 8, "calm": 3, "inspiration": 6}.get(emotion, 6)


# ---------------------------------------------------------------------------
# Source 1: MyInstants trending memes
# ---------------------------------------------------------------------------

_MYINSTANTS_TRENDING = "https://www.myinstants.com/en/trending/"
_MYINSTANTS_MP3_RE = re.compile(r'["\'](/media/sounds/[^"\']+?\.mp3)["\']')


def scrape_myinstants_trending(limit: int = 25) -> list:
    """Scrape currently-trending meme sounds from MyInstants.

    Returns records with category="meme". Best-effort: [] on any failure.
    """
    if not _SCOUT_AVAILABLE:
        return []
    try:
        page, tier = _fetch_page(_MYINSTANTS_TRENDING, timeout=25)
    except Exception as e:
        log.info("myinstants trending fetch failed: %s", e)
        return []
    if page is None:
        return []
    if _is_blocked is not None and _is_blocked(page):
        log.info("myinstants trending: page looks blocked, skipping")
        return []
    html = _page_html(page)

    records, seen = [], set()
    for m in _MYINSTANTS_MP3_RE.finditer(html):
        audio_url = "https://www.myinstants.com" + m.group(1)
        if audio_url in seen:
            continue
        seen.add(audio_url)
        name = _clean_name(_nearest_title(html, m.start()),
                           fallback="Meme sound " + m.group(1).split("/")[-1][:24])
        emotion = _guess_emotion(name)
        records.append({
            "name": name,
            "audio_url": audio_url,
            "page_url": _MYINSTANTS_TRENDING,
            "source": "myinstants",
            "category": "meme",
            "subcategory": "trending-meme",
            "tags": _extract_tags(name, ("meme", "viral", "trending")),
            "emotion": emotion,
            "energy_level": _guess_energy(name, emotion),
            "tier": tier,
        })
        if len(records) >= limit:
            break
    log.info("myinstants trending: %d sounds via tier %s", len(records), tier)
    return records


# ---------------------------------------------------------------------------
# Source 2 & 3: Pixabay sound effects + music search
# ---------------------------------------------------------------------------

_PIXABAY_AUDIO_RE = re.compile(r'https?://cdn\.pixabay\.com/audio/[^"\'\s<>]+?\.mp3')
_PIXABAY_SFX_SEARCH = "https://pixabay.com/sound-effects/search/{q}/"
_PIXABAY_MUSIC_SEARCH = "https://pixabay.com/music/search/{q}/"

# Curated queries that map well to short-form video needs.
TRENDING_SFX_QUERIES = [
    "whoosh transition", "cinematic impact", "ding notification",
    "crowd cheer", "suspense sting", "pop click", "riser",
]
TRENDING_MUSIC_QUERIES = [
    "phonk viral", "upbeat pop", "cinematic epic", "lofi chill",
    "energetic edm", "funny comedy",
]


def _scrape_pixabay_search(search_url: str, category: str, subcategory: str,
                           query: str, limit: int) -> list:
    if not _SCOUT_AVAILABLE:
        return []
    try:
        page, tier = _fetch_page(search_url, timeout=25)
    except Exception as e:
        log.info("pixabay search fetch failed for %r: %s", query, e)
        return []
    if page is None:
        return []
    if _is_blocked is not None and _is_blocked(page):
        return []
    html = _page_html(page)

    records, seen = [], set()
    for m in _PIXABAY_AUDIO_RE.finditer(html):
        audio_url = m.group(0)
        if audio_url in seen:
            continue
        seen.add(audio_url)
        name = _clean_name(_nearest_title(html, m.start()),
                           fallback=f"{query} {len(records) + 1}")
        emotion = _guess_emotion(name + " " + query)
        records.append({
            "name": name,
            "audio_url": audio_url,
            "page_url": search_url,
            "source": "pixabay",
            "category": category,
            "subcategory": subcategory,
            "tags": _extract_tags(name + " " + query, ("pixabay",)),
            "emotion": emotion,
            "energy_level": _guess_energy(name, emotion),
            "tier": tier,
        })
        if len(records) >= limit:
            break
    return records


def scrape_pixabay_sfx(query: str, limit: int = 8) -> list:
    """Scrape Pixabay sound-effects search results for ``query``."""
    url = _PIXABAY_SFX_SEARCH.format(q=urllib.parse.quote(query))
    recs = _scrape_pixabay_search(url, "sfx", "pixabay-sfx", query, limit)
    log.info("pixabay sfx %r: %d sounds", query, len(recs))
    return recs


def scrape_pixabay_music(query: str, limit: int = 6) -> list:
    """Scrape Pixabay music search results for ``query``."""
    url = _PIXABAY_MUSIC_SEARCH.format(q=urllib.parse.quote(query))
    recs = _scrape_pixabay_search(url, "music", "pixabay-music", query, limit)
    log.info("pixabay music %r: %d sounds", query, len(recs))
    return recs


# ---------------------------------------------------------------------------
# Source 4: Mixkit free SFX
# ---------------------------------------------------------------------------

_MIXKIT_AUDIO_RE = re.compile(r'https?://assets\.mixkit\.co/[^"\'\s<>]+?\.mp3')
_MIXKIT_SFX_PAGE = "https://mixkit.co/free-sound-effects/{cat}/"

MIXKIT_CATEGORIES = ["whoosh", "impact", "transition", "notification"]


def scrape_mixkit_sfx(category: str = "whoosh", limit: int = 8) -> list:
    """Scrape Mixkit's free sound-effects category pages (direct MP3s)."""
    if not _SCOUT_AVAILABLE:
        return []
    url = _MIXKIT_SFX_PAGE.format(cat=urllib.parse.quote(category))
    try:
        page, tier = _fetch_page(url, timeout=25)
    except Exception as e:
        log.info("mixkit fetch failed for %r: %s", category, e)
        return []
    if page is None:
        return []
    if _is_blocked is not None and _is_blocked(page):
        return []
    html = _page_html(page)

    records, seen = [], set()
    for m in _MIXKIT_AUDIO_RE.finditer(html):
        audio_url = m.group(0)
        if audio_url in seen:
            continue
        seen.add(audio_url)
        name = _clean_name(_nearest_title(html, m.start()),
                           fallback=f"Mixkit {category} {len(records) + 1}")
        emotion = _guess_emotion(name + " " + category)
        records.append({
            "name": name,
            "audio_url": audio_url,
            "page_url": url,
            "source": "mixkit",
            "category": "sfx",
            "subcategory": f"mixkit-{category}",
            "tags": _extract_tags(name + " " + category, ("mixkit",)),
            "emotion": emotion,
            "energy_level": _guess_energy(name, emotion),
            "tier": tier,
        })
        if len(records) >= limit:
            break
    log.info("mixkit %r: %d sounds", category, len(records))
    return records


# ---------------------------------------------------------------------------
# Combined trending discovery
# ---------------------------------------------------------------------------

def discover_trending(max_per_source: int = 12, polite_delay: float = 1.0) -> dict:
    """Run all trending discovery sources. Always best-effort.

    Returns {"meme": [...], "sfx": [...], "music": [...]} — any list may be
    empty if its sources failed. Never raises.
    """
    out = {"meme": [], "sfx": [], "music": []}
    if not _SCOUT_AVAILABLE:
        log.warning("discover_trending: scout unavailable, skipping")
        return out

    try:
        out["meme"] = scrape_myinstants_trending(limit=max_per_source)
    except Exception as e:
        log.info("trending memes failed: %s", e)
    time.sleep(polite_delay)

    for q in TRENDING_SFX_QUERIES[:4]:
        try:
            out["sfx"].extend(scrape_pixabay_sfx(q, limit=4))
        except Exception as e:
            log.info("trending sfx %r failed: %s", q, e)
        time.sleep(polite_delay)
    for cat in MIXKIT_CATEGORIES[:2]:
        try:
            out["sfx"].extend(scrape_mixkit_sfx(cat, limit=4))
        except Exception as e:
            log.info("mixkit %r failed: %s", cat, e)
        time.sleep(polite_delay)

    for q in TRENDING_MUSIC_QUERIES[:4]:
        try:
            out["music"].extend(scrape_pixabay_music(q, limit=3))
        except Exception as e:
            log.info("trending music %r failed: %s", q, e)
        time.sleep(polite_delay)

    # Dedupe by audio_url across sources.
    for key in out:
        seen, uniq = set(), []
        for r in out[key]:
            if r["audio_url"] not in seen:
                seen.add(r["audio_url"])
                uniq.append(r)
        out[key] = uniq

    log.info("discover_trending: meme=%d sfx=%d music=%d",
             len(out["meme"]), len(out["sfx"]), len(out["music"]))
    return out


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    res = discover_trending(max_per_source=5, polite_delay=0.5)
    for k, v in res.items():
        print(f"{k}: {len(v)}")
        for r in v[:3]:
            print("  -", r["name"], "->", r["audio_url"][:80])
