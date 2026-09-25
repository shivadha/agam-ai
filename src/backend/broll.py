"""
AGAM — Free stock B-roll from Pexels (free API key).

  pexels_search(query, per_page=6)
      -> [{id, preview_url, download_url, duration, width, height}]
  download_clip(url, dest_path) -> local path
  match_scenes_to_broll(scenes, per_query=3, cache_dir=None)
      -> {scene_idx: {scene, query, clip_id, local_path, download_url,
                      preview_url, duration, width, height} | {"error": ...}}

The key is read from the same store /api/keys uses (PEXELS_API_KEY in
os.environ or BASE_DIR/.env). Clips are cached under output/broll/ so
repeat renders never re-download. Per-scene failures are recorded as
{"error": ...} and never abort the whole match.
"""

import os
import re
from collections import Counter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_CACHE_DIR = os.path.join(BASE_DIR, "output", "broll")

PEXELS_SEARCH_URL = "https://api.pexels.com/videos/search"

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "else", "when",
    "while", "with", "without", "for", "from", "into", "over", "under",
    "this", "that", "these", "those", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "must", "shall", "can",
    "not", "no", "yes", "so", "very", "just", "about", "also", "its",
    "it's", "their", "there", "they", "them", "he", "she", "him", "her",
    "his", "hers", "you", "your", "yours", "we", "our", "ours", "us",
    "what", "which", "who", "whom", "whose", "how", "why", "where",
    "here", "now", "today", "more", "most", "some", "such", "only",
    "than", "too", "out", "off", "all", "any", "each", "few", "own",
    "same", "other", "because", "until", "between", "through", "during",
    "before", "after", "above", "below", "again", "once", "like",
}


def _read_api_key(env_name):
    """Same key store /api/keys uses: os.environ first, then BASE_DIR/.env."""
    val = (os.environ.get(env_name) or "").strip()
    if val:
        return val
    env_path = os.path.join(BASE_DIR, ".env")
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(env_name + "="):
                    v = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if v:
                        return v
    except Exception:
        pass
    return ""


def _pick_file(video):
    """Pick the best downloadable mp4: HD <=1080p preferred."""
    files = [f for f in (video.get("video_files") or []) if f.get("link")]
    if not files:
        return None
    mp4s = [f for f in files if "mp4" in (f.get("file_type") or "").lower()] or files
    hd = [f for f in mp4s if (f.get("height") or 0) <= 1080]
    pool = hd or mp4s
    # Prefer the largest resolution in the pool (best quality under cap).
    pool.sort(key=lambda f: (f.get("width") or 0) * (f.get("height") or 0), reverse=True)
    return pool[0]


def pexels_search(query, per_page=6):
    """Search Pexels videos. Returns [{id, preview_url, download_url, ...}].

    Raises RuntimeError if no PEXELS_API_KEY is set or the API fails.
    """
    import requests

    key = _read_api_key("PEXELS_API_KEY")
    if not key:
        raise RuntimeError(
            "Add a free Pexels API key first (pexels.com/api → PEXELS_API_KEY "
            "in the Keys panel), then search again."
        )
    try:
        r = requests.get(
            PEXELS_SEARCH_URL,
            headers={"Authorization": key},
            params={"query": query or "", "per_page": max(1, min(20, per_page))},
            timeout=25,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        raise RuntimeError(f"Pexels search failed: {e}")

    results = []
    for v in (data.get("videos") or []):
        f = _pick_file(v)
        if not f:
            continue
        results.append({
            "id": v.get("id"),
            "preview_url": v.get("image") or "",
            "download_url": f.get("link"),
            "duration": v.get("duration"),
            "width": f.get("width"),
            "height": f.get("height"),
        })
    return results


def download_clip(url, dest_path):
    """Download a clip to dest_path. Returns dest_path; RuntimeError on failure."""
    import requests

    if not url:
        raise RuntimeError("No download URL provided.")
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    try:
        r = requests.get(url, stream=True, timeout=180)
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
    except Exception as e:
        try:
            if os.path.exists(dest_path):
                os.remove(dest_path)
        except Exception:
            pass
        raise RuntimeError(f"B-roll download failed: {e}")
    print(f"[broll] Cached -> {dest_path}")
    return dest_path


def extract_keywords(text, top_n=5):
    """Content words from scene text -> query terms (stdlib only)."""
    words = re.findall(r"[a-z]{4,}", (text or "").lower())
    freq = Counter(w for w in words if w not in STOPWORDS)
    return [w for w, _ in freq.most_common(top_n)]


def match_scenes_to_broll(scenes, per_query=3, cache_dir=None):
    """Match each scene to a cached Pexels clip via keyword search.

    Returns {scene_idx: clip_info incl. local_path}. Per-scene failures
    are recorded as {"error": ...} and never abort the whole match.
    """
    cache_dir = cache_dir or DEFAULT_CACHE_DIR
    os.makedirs(cache_dir, exist_ok=True)

    if isinstance(scenes, dict):
        scenes = [scenes]
    norm = []
    for sc in scenes or []:
        if isinstance(sc, str):
            norm.append(sc)
        elif isinstance(sc, dict):
            norm.append(sc.get("text") or sc.get("narration") or sc.get("script") or "")
        else:
            norm.append("")

    matched = {}
    for idx, text in enumerate(norm):
        info = {"scene": idx + 1, "query": ""}
        try:
            keywords = extract_keywords(text)
            query = " ".join(keywords[:3]) if keywords else (text or "")[:60]
            info["query"] = query
            clips = pexels_search(query, per_page=per_query)
            if not clips:
                raise RuntimeError(f"No Pexels clips found for '{query}'.")
            # Prefer a clip long enough to cover a scene; else the longest.
            clips.sort(key=lambda c: (c.get("duration") or 0), reverse=True)
            clip = next((c for c in clips if (c.get("duration") or 0) >= 4), clips[0])
            dest = os.path.join(cache_dir, f"scene{idx + 1}_{clip['id']}.mp4")
            if not (os.path.exists(dest) and os.path.getsize(dest) > 0):
                download_clip(clip["download_url"], dest)
            info.update({
                "clip_id": clip["id"],
                "local_path": dest,
                "download_url": clip["download_url"],
                "preview_url": clip["preview_url"],
                "duration": clip["duration"],
                "width": clip["width"],
                "height": clip["height"],
            })
        except Exception as e:
            info["error"] = str(e)
            print(f"[broll] Scene {idx + 1} note: {e}")
        matched[idx] = info
    return matched
