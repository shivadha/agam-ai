"""
aggregator.py — PulseForge Zero-Cost News Pipeline
====================================================
Sources (all free, zero signup, zero API keys):
  1. OpenRouter public registry  → AI model drops
  2. HackerNews RSS (hnrss.org)  → AI keyword streams
  3. Free RSS feeds               → Pop culture, gaming, tech, etc.

Each new article is persisted to SQLite. Duplicate links are skipped.
Robust try/except on every network call — server never crashes on source failure.
"""

import requests
import feedparser
import re
import hashlib
from urllib.parse import quote_plus
from .backend.trend_analyzer import calculate_viral_score, calculate_video_score
from . import database

# ── Feed Definitions ───────────────────────────────────────────────────────

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/models"

HN_FEEDS = {
    "AI & LLMs":     "https://hnrss.org/newest?q=LLM+OR+AI+OR+GPT+OR+Claude",
    "Open Source":   "https://hnrss.org/newest?q=open+source+model+OR+open+source+AI",
    "AI Tools":      "https://hnrss.org/newest?q=AI+tool+OR+AI+agent+OR+automation",
    "Breakthroughs": "https://hnrss.org/newest?q=AI+breakthrough+OR+state+of+the+art",
}

POP_CULTURE_FEEDS = {
    "Pop Culture":   "https://www.reddit.com/r/popculturechat/.rss",
    "Entertainment": "https://feeds.feedburner.com/ign/all",
    "Gaming":        "https://www.reddit.com/r/gaming/top/.rss?t=day",
    "Tech":          "https://feeds.feedburner.com/TechCrunch",
    "Science":       "https://www.reddit.com/r/science/top/.rss?t=day",
    "World News":    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "Space":         "https://www.reddit.com/r/space/top/.rss?t=day",
    "Finance":       "https://feeds.finance.yahoo.com/rss/2.0/headline",
    "Sports":        "https://www.reddit.com/r/sports/top/.rss?t=day",
}

REQUEST_TIMEOUT = 12   # seconds

# Curated high-res topic visual backdrops for instant rich UI rendering
TOPIC_DEFAULT_IMAGES = {
    "AI & LLMs":     "https://images.unsplash.com/photo-1677442136019-21780ecad995?w=800&auto=format&fit=crop&q=80",
    "AI News":       "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=800&auto=format&fit=crop&q=80",
    "AI Tools":      "https://images.unsplash.com/photo-1620712943543-bcc4688e7485?w=800&auto=format&fit=crop&q=80",
    "Breakthroughs": "https://images.unsplash.com/photo-1635070041078-e363dbe005cb?w=800&auto=format&fit=crop&q=80",
    "Open Source":   "https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?w=800&auto=format&fit=crop&q=80",
    "Pop Culture":   "https://images.unsplash.com/photo-1514525253161-7a46d19cd819?w=800&auto=format&fit=crop&q=80",
    "Entertainment": "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?w=800&auto=format&fit=crop&q=80",
    "Gaming":        "https://images.unsplash.com/photo-1538481199705-c710c4e965fc?w=800&auto=format&fit=crop&q=80",
    "Tech":          "https://images.unsplash.com/photo-1518770660439-4636190af475?w=800&auto=format&fit=crop&q=80",
    "Science":       "https://images.unsplash.com/photo-1507668077129-56e32842fceb?w=800&auto=format&fit=crop&q=80",
    "World News":    "https://images.unsplash.com/photo-1504711434969-e33886168f5c?w=800&auto=format&fit=crop&q=80",
    "Space":         "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=800&auto=format&fit=crop&q=80",
    "Finance":       "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?w=800&auto=format&fit=crop&q=80",
    "Sports":        "https://images.unsplash.com/photo-1461896836934-ffe607ba8211?w=800&auto=format&fit=crop&q=80",
}


# ── Helpers ────────────────────────────────────────────────────────────────

def _clean_html(text: str) -> str:
    """Strip HTML tags from RSS summary text."""
    return re.sub(r'<[^>]+>', '', text).strip() if text else ''


def _extract_image(entry=None, raw_html="", topic="Tech", title="") -> str:
    """Extract real image URL from feed item or generate high-quality relevant fallback."""
    # 1. Feedparser media thumbnails
    if entry:
        if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
            url = entry.media_thumbnail[0].get('url')
            if url and url.startswith('http'):
                return url
        if hasattr(entry, 'media_content') and entry.media_content:
            url = entry.media_content[0].get('url')
            if url and url.startswith('http'):
                return url
        if hasattr(entry, 'enclosures') and entry.enclosures:
            for enc in entry.enclosures:
                href = enc.get('href') or enc.get('url')
                if href and href.startswith('http') and ('image' in enc.get('type', '') or any(ext in href.lower() for ext in ('.jpg', '.png', '.jpeg', '.webp'))):
                    return href
        if hasattr(entry, 'links'):
            for link in entry.links:
                if 'image' in link.get('type', '') and link.get('href', '').startswith('http'):
                    return link['href']

    # 2. Parse img src from raw html / summary
    if raw_html:
        img_match = re.search(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', raw_html, re.IGNORECASE)
        if img_match:
            img_url = img_match.group(1)
            # Filter out tiny tracking pixels or badges
            if not any(bad in img_url.lower() for bad in ('1x1', 'pixel', 'feedburner', 'beacon', 'doubleclick')):
                return img_url

    # 3. Topic Curated High-Definition Fallback with deterministic seed
    base = TOPIC_DEFAULT_IMAGES.get(topic, TOPIC_DEFAULT_IMAGES.get("Tech"))
    if title:
        seed = int(hashlib.md5(title.encode('utf-8')).hexdigest()[:6], 16) % 100
        return f"{base}&sig={seed}"
    return base


def _try_save(title: str, link: str, source: str,
              topic: str, description: str, alert_badge: str = None, image_url: str = None) -> bool:
    """
    Score and persist a single article if its link is not already in the DB.
    Returns True if a new article was written, False if duplicate.
    """
    if not link or database.article_exists(link):
        return False

    full_title  = f"{alert_badge} {title}" if alert_badge else title
    score       = calculate_viral_score(full_title)
    video_score = calculate_video_score(full_title, topic)

    if not image_url:
        image_url = _extract_image(raw_html=description, topic=topic, title=full_title)

    database.upsert_article(
        title       = full_title,
        link        = link,
        source      = source,
        topic       = topic,
        score       = score,
        video_score = video_score,
        description = description[:500] if description else '',
        image_url   = image_url
    )
    return True


# ── Source 1: OpenRouter ───────────────────────────────────────────────────

def _fetch_openrouter_models() -> int:
    """Fetches the OpenRouter model registry. Each new model = MODEL DROP alert."""
    print("  [OpenRouter] Fetching model registry...")
    count = 0
    try:
        resp = requests.get(OPENROUTER_API_URL, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        models = resp.json().get('data', [])
        for model in models:
            model_id = model.get('id', '')
            link     = f"https://openrouter.ai/models/{model_id}"
            name     = model.get('name', model_id)
            desc     = model.get('description', '')
            img_url  = _extract_image(topic='AI News', title=name)
            if _try_save(name, link, 'OpenRouter', 'AI News', desc, '⚡ [MODEL DROP]', image_url=img_url):
                count += 1
        print(f"  [OpenRouter] {count} new models stored.")
    except requests.exceptions.Timeout:
        print("  WARNING [OpenRouter] Request timed out.")
    except requests.exceptions.ConnectionError:
        print("  WARNING [OpenRouter] Connection failed — service may be down.")
    except Exception as e:
        print(f"  WARNING [OpenRouter] Unexpected error: {e}")
    return count


# ── Source 2: HackerNews RSS ───────────────────────────────────────────────

def _fetch_hn_feeds() -> int:
    """Fetches keyword-filtered HackerNews RSS streams."""
    print("  [HackerNews] Fetching feeds...")
    count = 0
    for label, url in HN_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                link = getattr(entry, 'link', '')
                raw_summary = getattr(entry, 'summary', '')
                desc = _clean_html(raw_summary)
                img = _extract_image(entry, raw_summary, label, entry.title)
                if _try_save(entry.title, link, f'HackerNews / {label}', label, desc, image_url=img):
                    count += 1
        except Exception as e:
            print(f"  WARNING [HN:{label}]: {e}")
    print(f"  [HackerNews] {count} new items stored.")
    return count


# ── Source 3: Pop Culture & General RSS ───────────────────────────────────

def _fetch_pop_culture_feeds() -> int:
    """Fetches general free RSS feeds across multiple categories."""
    print("  [RSS] Fetching general feeds...")
    count = 0
    for label, url in POP_CULTURE_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                link = getattr(entry, 'link', '')
                raw_summary = getattr(entry, 'summary', '')
                desc = _clean_html(raw_summary)
                img = _extract_image(entry, raw_summary, label, entry.title)
                if _try_save(entry.title, link, label, label, desc, image_url=img):
                    count += 1
        except Exception as e:
            print(f"  WARNING [RSS:{label}]: {e}")
    print(f"  [RSS] {count} new items stored.")
    return count


# ── One-time Image Backfill Helper ─────────────────────────────────────────

def backfill_missing_article_images() -> int:
    """Assign high-quality images to existing articles that have null or empty image_url."""
    with database._db_lock:
        conn = database.get_db()
        rows = conn.execute("SELECT id, title, topic, description FROM articles WHERE image_url IS NULL OR image_url = ''").fetchall()
        updated = 0
        for r in rows:
            aid, title, topic, desc = r[0], r[1], r[2] or 'Tech', r[3] or ''
            img = _extract_image(raw_html=desc, topic=topic, title=title)
            conn.execute("UPDATE articles SET image_url = ? WHERE id = ?", (img, aid))
            updated += 1
        conn.commit()
        conn.close()
    if updated:
        print(f"[Aggregator] Backfilled images for {updated} legacy articles.")
    return updated


# ── Public API ─────────────────────────────────────────────────────────────

def fetch_and_process_news() -> int:
    """
    Master pipeline. Calls all sources, persists to DB, returns count of NEW items.
    """
    print("\n=== PulseForge Aggregation Pipeline ===")
    total  = 0
    total += _fetch_openrouter_models()
    total += _fetch_hn_feeds()
    total += _fetch_pop_culture_feeds()
    backfill_missing_article_images()
    print(f"=== Pipeline complete. {total} new articles saved to DB ===\n")
    return total
