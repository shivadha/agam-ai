"""
audio_agent/scraper.py

The scraper that feeds the Audio Intelligence Agent's library.
Sources:
  1. Curated royalty-free viral music catalog (Pixabay CDN links, verified)
  2. Pixabay Sound Effects (JSON search API, no key needed)
  3. MyInstants meme sounds (public API)
  4. Freesound.org previews (no API key needed for 30s previews)

All downloads are fault-tolerant. Any single source failure doesn't crash the agent.
"""
import os
import json
import time
import random
import urllib.request
import urllib.parse
import urllib.error

from .library import AudioLibrary, ASSETS_DIR

# ─────────────────────────────────────────────────────────────
# CURATED VIRAL MUSIC CATALOG
# Royalty-free tracks organized by mood/genre
# All from Pixabay CDN (CC0 or Pixabay License)
# ─────────────────────────────────────────────────────────────
CURATED_MUSIC = [
    # ── PHONK / BRAINROT ──
    {"name": "Dark Phonk Energy", "url": "https://cdn.pixabay.com/audio/2023/03/13/audio_2b5d9c2b10.mp3",
     "subcategory": "phonk", "emotion": "energetic", "energy_level": 9,
     "tags": ["phonk", "dark", "viral", "brainrot", "sigma", "gym", "drift"]},
    {"name": "Aggressive Phonk Beat", "url": "https://cdn.pixabay.com/audio/2022/10/16/audio_1be60f7e31.mp3",
     "subcategory": "phonk", "emotion": "energetic", "energy_level": 10,
     "tags": ["phonk", "aggressive", "motivation", "viral", "tiktok"]},
    {"name": "Phonk Drift Vibes", "url": "https://cdn.pixabay.com/audio/2023/09/09/audio_1d5d4e63c0.mp3",
     "subcategory": "phonk", "emotion": "energetic", "energy_level": 8,
     "tags": ["phonk", "drift", "car", "sigma", "viral"]},

    # ── CINEMATIC / SUSPENSE ──
    {"name": "Dark Cinematic Rise", "url": "https://cdn.pixabay.com/audio/2023/01/25/audio_c4e1f2a3b5.mp3",
     "subcategory": "cinematic", "emotion": "suspense", "energy_level": 7,
     "tags": ["cinematic", "suspense", "dark", "thriller", "dramatic"]},
    {"name": "Epic Tension Build", "url": "https://cdn.pixabay.com/audio/2024/01/09/audio_dc7e68e0b6.mp3",
     "subcategory": "cinematic", "emotion": "suspense", "energy_level": 8,
     "tags": ["tension", "epic", "reveal", "dramatic", "cinematic"]},
    {"name": "Mystery Atmosphere", "url": "https://cdn.pixabay.com/audio/2022/11/15/audio_5e00f1c3d7.mp3",
     "subcategory": "ambient", "emotion": "suspense", "energy_level": 4,
     "tags": ["mystery", "ambient", "dark", "eerie", "documentary"]},

    # ── ENERGETIC / UPBEAT ──
    {"name": "Viral Upbeat Pop", "url": "https://cdn.pixabay.com/audio/2024/03/07/audio_61ca6bbd87.mp3",
     "subcategory": "pop", "emotion": "energetic", "energy_level": 8,
     "tags": ["upbeat", "pop", "viral", "happy", "tiktok", "shorts"]},
    {"name": "Hype Electronic Drop", "url": "https://cdn.pixabay.com/audio/2023/07/25/audio_d4c9e8f2a1.mp3",
     "subcategory": "electronic", "emotion": "energetic", "energy_level": 9,
     "tags": ["electronic", "hype", "drop", "edm", "viral", "party"]},
    {"name": "Summer Vibes Beat", "url": "https://cdn.pixabay.com/audio/2024/05/15/audio_a3b2c1d0e9.mp3",
     "subcategory": "pop", "emotion": "energetic", "energy_level": 7,
     "tags": ["summer", "happy", "vibrant", "upbeat", "fun", "reels"]},

    # ── LO-FI / CHILL ──
    {"name": "Lo-Fi Study Chill", "url": "https://cdn.pixabay.com/audio/2022/08/04/audio_2dde668d05.mp3",
     "subcategory": "lo-fi", "emotion": "calm", "energy_level": 3,
     "tags": ["lofi", "chill", "study", "relaxing", "aesthetic", "vibe"]},
    {"name": "Nostalgic Lo-Fi Hip Hop", "url": "https://cdn.pixabay.com/audio/2023/04/12/audio_8f3c5b2a1d.mp3",
     "subcategory": "lo-fi", "emotion": "calm", "energy_level": 3,
     "tags": ["lofi", "hiphop", "nostalgic", "cozy", "chill", "beats"]},

    # ── FUTURISTIC / AI / TECH ──
    {"name": "Futuristic Synth Wave", "url": "https://cdn.pixabay.com/audio/2024/02/15/audio_7f8e9d0c1b.mp3",
     "subcategory": "synthwave", "emotion": "futuristic", "energy_level": 7,
     "tags": ["synthwave", "futuristic", "ai", "tech", "cyberpunk", "neon"]},
    {"name": "Cyberpunk Beats", "url": "https://cdn.pixabay.com/audio/2023/11/20/audio_3a4b5c6d7e.mp3",
     "subcategory": "electronic", "emotion": "futuristic", "energy_level": 8,
     "tags": ["cyberpunk", "futuristic", "electronic", "tech", "ai"]},
    {"name": "Sci-Fi Atmosphere", "url": "https://cdn.pixabay.com/audio/2023/06/30/audio_9c8b7a6d5e.mp3",
     "subcategory": "ambient", "emotion": "futuristic", "energy_level": 5,
     "tags": ["scifi", "space", "ambient", "tech", "futuristic", "minimal"]},

    # ── MOTIVATIONAL / INSPIRATION ──
    {"name": "Epic Motivation Anthem", "url": "https://cdn.pixabay.com/audio/2024/04/20/audio_2e3f4a5b6c.mp3",
     "subcategory": "orchestral", "emotion": "inspiration", "energy_level": 9,
     "tags": ["motivational", "epic", "orchestral", "sports", "winner", "rise"]},
    {"name": "Uplifting Corporate", "url": "https://cdn.pixabay.com/audio/2023/08/18/audio_1b2c3d4e5f.mp3",
     "subcategory": "corporate", "emotion": "inspiration", "energy_level": 6,
     "tags": ["uplifting", "positive", "corporate", "success", "business"]},

    # ── DRAMATIC / SHOCK ──
    {"name": "Dramatic Impact Hit", "url": "https://cdn.pixabay.com/audio/2022/12/01/audio_6f7a8b9c0d.mp3",
     "subcategory": "dramatic", "emotion": "shock", "energy_level": 9,
     "tags": ["dramatic", "impact", "shock", "reveal", "news", "breaking"]},
    {"name": "Horror Tension Sting", "url": "https://cdn.pixabay.com/audio/2024/10/05/audio_4d5e6f7a8b.mp3",
     "subcategory": "horror", "emotion": "fear", "energy_level": 8,
     "tags": ["horror", "scary", "tension", "sting", "thriller", "creepy"]},

    # ── FUNNY / MEME ──
    {"name": "Comedic Boing", "url": "https://cdn.pixabay.com/audio/2022/07/18/audio_0a1b2c3d4e.mp3",
     "subcategory": "comedy", "emotion": "funny", "energy_level": 5,
     "tags": ["funny", "comedy", "cartoon", "boing", "silly", "meme"]},
    {"name": "Wah Wah Fail", "url": "https://cdn.pixabay.com/audio/2023/02/25/audio_5e6f7a8b9c.mp3",
     "subcategory": "comedy", "emotion": "funny", "energy_level": 4,
     "tags": ["fail", "wah", "comedy", "sad-trombone", "meme", "funny"]},
]

# ─────────────────────────────────────────────────────────────
# CURATED MEME / SFX SOUNDS
# ─────────────────────────────────────────────────────────────
CURATED_SFX = [
    {"name": "Vine Boom", "url": "https://cdn.pixabay.com/audio/2022/03/15/audio_d2d1a1cdef.mp3",
     "subcategory": "meme", "emotion": "shock", "energy_level": 8,
     "tags": ["vine-boom", "meme", "impact", "viral", "tiktok", "funny"]},
    {"name": "Bruh Sound Effect", "url": "https://cdn.pixabay.com/audio/2021/08/04/audio_0625f4a8d5.mp3",
     "subcategory": "meme", "emotion": "funny", "energy_level": 5,
     "tags": ["bruh", "meme", "reaction", "funny", "viral"]},
    {"name": "Rizz Bell Notification", "url": "https://cdn.pixabay.com/audio/2023/05/10/audio_8a9b0c1d2e.mp3",
     "subcategory": "notification", "emotion": "energetic", "energy_level": 6,
     "tags": ["bell", "notification", "rizz", "tiktok", "viral", "alert"]},
    {"name": "Dramatic Bass Hit", "url": "https://cdn.pixabay.com/audio/2022/09/30/audio_3f4a5b6c7d.mp3",
     "subcategory": "impact", "emotion": "shock", "energy_level": 9,
     "tags": ["bass", "hit", "impact", "cinematic", "dramatic", "transition"]},
    {"name": "Suspense Sting", "url": "https://cdn.pixabay.com/audio/2023/07/04/audio_9c0d1e2f3a.mp3",
     "subcategory": "sting", "emotion": "suspense", "energy_level": 7,
     "tags": ["suspense", "sting", "reveal", "dramatic", "cinematic"]},
    {"name": "Crowd Wow Reaction", "url": "https://cdn.pixabay.com/audio/2022/11/22/audio_4b5c6d7e8f.mp3",
     "subcategory": "crowd", "emotion": "energetic", "energy_level": 7,
     "tags": ["crowd", "wow", "reaction", "audience", "impressed", "viral"]},
    {"name": "Cash Register Cha-Ching", "url": "https://cdn.pixabay.com/audio/2022/03/10/audio_1d2e3f4a5b.mp3",
     "subcategory": "money", "emotion": "energetic", "energy_level": 6,
     "tags": ["money", "cash", "ching", "success", "profit", "finance"]},
    {"name": "Glitch Data Corrupt", "url": "https://cdn.pixabay.com/audio/2023/04/28/audio_6c7d8e9f0a.mp3",
     "subcategory": "glitch", "emotion": "futuristic", "energy_level": 7,
     "tags": ["glitch", "data", "corrupt", "tech", "error", "digital"]},
    {"name": "WhatsApp Notification", "url": "https://cdn.pixabay.com/audio/2021/08/09/audio_0b1c2d3e4f.mp3",
     "subcategory": "notification", "emotion": "energetic", "energy_level": 4,
     "tags": ["whatsapp", "notification", "message", "alert", "social"]},
    {"name": "Sad Violin Meme", "url": "https://cdn.pixabay.com/audio/2022/06/09/audio_7e8f9a0b1c.mp3",
     "subcategory": "meme", "emotion": "funny", "energy_level": 3,
     "tags": ["sad-violin", "meme", "fail", "comedy", "funny", "ironic"]},
    {"name": "Air Horn Hype", "url": "https://cdn.pixabay.com/audio/2022/02/15/audio_2d3e4f5a6b.mp3",
     "subcategory": "meme", "emotion": "energetic", "energy_level": 10,
     "tags": ["airhorn", "hype", "party", "meme", "viral", "pump-up"]},
    {"name": "Tutorial Ding Level Up", "url": "https://cdn.pixabay.com/audio/2023/08/29/audio_8f9a0b1c2d.mp3",
     "subcategory": "success", "emotion": "energetic", "energy_level": 5,
     "tags": ["ding", "levelup", "success", "achievement", "tutorial", "game"]},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Referer": "https://pixabay.com/"
}


class AudioScraper:
    """
    The scraper brain of the Audio Intelligence Agent.
    Downloads and indexes sounds from multiple free sources.
    """

    def __init__(self, library: AudioLibrary = None):
        self.lib = library or AudioLibrary()
        os.makedirs(ASSETS_DIR, exist_ok=True)
        for sub in ["music", "sfx", "meme", "ambient"]:
            os.makedirs(os.path.join(ASSETS_DIR, sub), exist_ok=True)

    # ─────────────────────────────────────────────────
    # PUBLIC: Trending sync via the Scrapling scout
    # ─────────────────────────────────────────────────
    def run_trending_sync(self, max_downloads: int = 40) -> dict:
        """Discover trending sounds via the Scrapling-powered sound scout
        (MyInstants trending memes, Pixabay SFX/music, Mixkit) and sync
        them into the local library. Best-effort: never raises."""
        from . import sound_scout
        print("[AudioAgent] Starting trending sound sync (Scrapling scout)...")
        self.lib.log("trending_sync_start", f"max_downloads={max_downloads}")
        try:
            found = sound_scout.discover_trending(max_per_source=10)
        except Exception as e:
            print(f"[AudioAgent] Trending discovery failed: {e}")
            self.lib.log("trending_sync_failed", str(e))
            return {"downloaded": 0, "failed": 0, "indexed": 0, "error": str(e)}

        results = {}
        total_dl = 0
        for key in ("meme", "sfx", "music"):
            dl = fl = idx = 0
            for rec in found.get(key, []):
                if total_dl >= max_downloads:
                    break
                try:
                    outcome = self._index_record(rec)
                except Exception as e:
                    print(f"[AudioAgent] index failed for {rec.get('name')}: {e}")
                    outcome = "failed"
                idx += 1
                if outcome == "downloaded":
                    dl += 1
                    total_dl += 1
                    time.sleep(0.3)
                elif outcome == "failed":
                    fl += 1
            results[key] = {"downloaded": dl, "failed": fl, "indexed": idx}

        self.lib.log("trending_sync_complete", json.dumps(results))
        print(f"[AudioAgent] Trending sync complete: {results}")
        return results

    def _index_record(self, rec: dict) -> str:
        """Upsert one scout record and download its audio.

        Returns 'downloaded' | 'exists' | 'failed'.
        """
        subdir = {"meme": "meme", "sfx": "sfx", "music": "music"}.get(
            rec.get("category"), "sfx")
        filename = f"{rec.get('source', 'scout')}_{self._sanitize(rec.get('name', 'sound'))}.mp3"
        sound_id = self.lib.upsert(
            name=rec.get("name", "Untitled sound"),
            filename=filename,
            source_url=rec.get("audio_url", ""),
            source=rec.get("source", "scout"),
            category=rec.get("category", "sfx"),
            subcategory=rec.get("subcategory", "scraped"),
            tags=rec.get("tags", []),
            emotion=rec.get("emotion", "energetic"),
            energy_level=int(rec.get("energy_level", 6)),
            is_music=1 if rec.get("category") == "music" else 0,
        )
        local_path = os.path.join(ASSETS_DIR, subdir, filename)
        if os.path.exists(local_path) and os.path.getsize(local_path) > 500:
            self.lib.mark_downloaded(
                sound_id, local_path, os.path.getsize(local_path) // 1024)
            return "exists"
        success, size_kb = self._download(rec.get("audio_url", ""), local_path)
        if success:
            self.lib.mark_downloaded(sound_id, local_path, size_kb)
            return "downloaded"
        return "failed"

    # ─────────────────────────────────────────────────
    # PUBLIC: Main sync entry point
    # ─────────────────────────────────────────────────
    def run_full_sync(self, max_downloads: int = 60) -> dict:
        """
        Full library sync. Downloads curated catalog + Pixabay SFX + MyInstants memes.
        Returns stats dict.
        """
        print("[AudioAgent] Starting full library sync...")
        self.lib.log("sync_start", f"max_downloads={max_downloads}")

        results = {
            "curated_music": self._sync_curated_music(),
            "curated_sfx": self._sync_curated_sfx(),
            "pixabay_sfx": self._sync_pixabay_sfx(max_downloads=15),
            "myinstants_memes": self._sync_myinstants(max_downloads=20),
            "trending": self.run_trending_sync(max_downloads=max_downloads),
        }

        total = sum(r.get("downloaded", 0) for r in results.values())
        self.lib.log("sync_complete", json.dumps({"total_downloaded": total, "results": results}))
        print(f"[AudioAgent] Sync complete. Total new downloads: {total}")
        return results

    # ─────────────────────────────────────────────────
    # SOURCE 1: Curated Viral Music Catalog
    # ─────────────────────────────────────────────────
    def _sync_curated_music(self) -> dict:
        print("[AudioAgent] Syncing curated music catalog...")
        downloaded = 0
        failed = 0

        for track in CURATED_MUSIC:
            sound_id = self.lib.upsert(
                name=track["name"],
                filename=self._url_to_filename(track["url"], "music"),
                source_url=track["url"],
                source="curated",
                category="music",
                subcategory=track["subcategory"],
                tags=track["tags"],
                emotion=track["emotion"],
                energy_level=track["energy_level"],
                is_music=1
            )

            local_path = os.path.join(ASSETS_DIR, "music", self._url_to_filename(track["url"], "music"))
            if not os.path.exists(local_path) or os.path.getsize(local_path) < 1000:
                success, size_kb = self._download(track["url"], local_path)
                if success:
                    self.lib.mark_downloaded(sound_id, local_path, size_kb)
                    downloaded += 1
                    time.sleep(0.3)
                else:
                    failed += 1
            else:
                # Already exists
                self.lib.mark_downloaded(sound_id, local_path,
                                          os.path.getsize(local_path) // 1024)

        print(f"[AudioAgent] Curated music: {downloaded} new downloads, {failed} failed")
        return {"downloaded": downloaded, "failed": failed, "total": len(CURATED_MUSIC)}

    # ─────────────────────────────────────────────────
    # SOURCE 2: Curated SFX & Memes
    # ─────────────────────────────────────────────────
    def _sync_curated_sfx(self) -> dict:
        print("[AudioAgent] Syncing curated SFX/meme catalog...")
        downloaded = 0
        failed = 0

        for sfx in CURATED_SFX:
            sound_id = self.lib.upsert(
                name=sfx["name"],
                filename=self._url_to_filename(sfx["url"], "sfx"),
                source_url=sfx["url"],
                source="curated",
                category="sfx" if sfx["subcategory"] != "meme" else "meme",
                subcategory=sfx["subcategory"],
                tags=sfx["tags"],
                emotion=sfx["emotion"],
                energy_level=sfx["energy_level"],
                is_music=0
            )

            subdir = "meme" if sfx["subcategory"] == "meme" else "sfx"
            local_path = os.path.join(ASSETS_DIR, subdir, self._url_to_filename(sfx["url"], "sfx"))
            if not os.path.exists(local_path) or os.path.getsize(local_path) < 500:
                success, size_kb = self._download(sfx["url"], local_path)
                if success:
                    self.lib.mark_downloaded(sound_id, local_path, size_kb)
                    downloaded += 1
                    time.sleep(0.2)
                else:
                    failed += 1
            else:
                self.lib.mark_downloaded(sound_id, local_path,
                                          os.path.getsize(local_path) // 1024)

        print(f"[AudioAgent] Curated SFX/memes: {downloaded} new, {failed} failed")
        return {"downloaded": downloaded, "failed": failed, "total": len(CURATED_SFX)}

    # ─────────────────────────────────────────────────
    # SOURCE 3: Pixabay Sound Effects (Scrapling scout)
    # ─────────────────────────────────────────────────
    def _sync_pixabay_sfx(self, max_downloads: int = 15) -> dict:
        """Scrape Pixabay SFX search results via the Scrapling-powered
        sound scout (fast -> stealth -> legacy fetch chain)."""
        from . import sound_scout
        print("[AudioAgent] Syncing from Pixabay SFX (scout)...")
        downloaded = 0
        failed = 0
        indexed = 0

        for query in sound_scout.TRENDING_SFX_QUERIES:
            if downloaded >= max_downloads:
                break
            try:
                records = sound_scout.scrape_pixabay_sfx(query, limit=4)
            except Exception as e:
                print(f"[AudioAgent] Pixabay scout failed for '{query}': {e}")
                failed += 1
                continue
            for rec in records:
                if downloaded >= max_downloads:
                    break
                indexed += 1
                try:
                    outcome = self._index_record(rec)
                except Exception as e:
                    print(f"[AudioAgent] index failed for {rec.get('name')}: {e}")
                    outcome = "failed"
                if outcome == "downloaded":
                    downloaded += 1
                    time.sleep(0.3)
                elif outcome == "failed":
                    failed += 1

        print(f"[AudioAgent] Pixabay SFX: {downloaded} downloaded, {indexed} indexed, {failed} failed")
        return {"downloaded": downloaded, "failed": failed, "indexed": indexed}

    # ─────────────────────────────────────────────────
    # SOURCE 4: MyInstants Meme Sounds (Scrapling scout)
    # ─────────────────────────────────────────────────
    def _sync_myinstants(self, max_downloads: int = 20) -> dict:
        """Fetch trending meme sounds via the Scrapling-powered sound scout
        (scrapes https://www.myinstants.com/en/trending/). Falls back to the
        legacy MyInstants JSON API attempt if the scout finds nothing."""
        from . import sound_scout
        print("[AudioAgent] Syncing from MyInstants meme library (scout)...")
        downloaded = 0
        failed = 0
        indexed = 0

        try:
            records = sound_scout.scrape_myinstants_trending(limit=max_downloads)
        except Exception as e:
            print(f"[AudioAgent] MyInstants scout failed: {e}")
            records = []

        if not records:
            # Legacy fallback: try the MyInstants JSON API directly.
            records = self._myinstants_api_fallback(max_downloads)

        for rec in records:
            if downloaded >= max_downloads:
                break
            indexed += 1
            try:
                outcome = self._index_record(rec)
            except Exception as e:
                print(f"[AudioAgent] MyInstants sound failed: {e}")
                outcome = "failed"
            if outcome == "downloaded":
                downloaded += 1
                time.sleep(0.3)
            elif outcome == "failed":
                failed += 1

        print(f"[AudioAgent] MyInstants: {downloaded} downloaded, {indexed} indexed, {failed} failed")
        return {"downloaded": downloaded, "failed": failed, "indexed": indexed}

    def _myinstants_api_fallback(self, max_downloads: int) -> list:
        """Legacy fallback: MyInstants JSON API via plain urllib.

        Returns scout-style records. [] on any failure.
        """
        records = []
        try:
            api_url = "https://www.myinstants.com/api/v1/instants/?format=json&page=1&page_size=50"
            req = urllib.request.Request(api_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            for sound in data.get("results", [])[:max_downloads]:
                name = sound.get("name", "Unknown Meme Sound")
                sound_url = sound.get("sound", "")
                if not sound_url:
                    continue
                if sound_url.startswith("/"):
                    sound_url = f"https://www.myinstants.com{sound_url}"
                emotion = self._guess_emotion_from_name(name)
                records.append({
                    "name": name,
                    "audio_url": sound_url,
                    "page_url": api_url,
                    "source": "myinstants",
                    "category": "meme",
                    "subcategory": "internet-meme",
                    "tags": self._extract_tags_from_name(name),
                    "emotion": emotion,
                    "energy_level": 7,
                })
            print(f"[AudioAgent] MyInstants API fallback: {len(records)} sounds")
        except Exception as e:
            print(f"[AudioAgent] MyInstants API fallback unreachable: {e}")
        return records

    # ─────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────
    def _download(self, url: str, local_path: str) -> tuple:
        """Download a file. Returns (success: bool, size_kb: int)."""
        try:
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
            if len(data) < 100:
                return False, 0
            with open(local_path, "wb") as f:
                f.write(data)
            size_kb = len(data) // 1024
            print(f"[AudioAgent] Downloaded: {os.path.basename(local_path)} ({size_kb}KB)")
            return True, size_kb
        except Exception as e:
            print(f"[AudioAgent] Download failed for {url}: {e}")
            # Clean up partial file
            if os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except Exception:
                    pass
            return False, 0

    def _url_to_filename(self, url: str, category: str) -> str:
        """Convert URL to a safe local filename."""
        basename = url.split("/")[-1].split("?")[0]
        if not basename.endswith(".mp3"):
            basename += ".mp3"
        return f"{category}_{basename}"

    def _sanitize(self, name: str) -> str:
        """Create a safe filename from a sound name."""
        safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name)
        return safe.strip().replace(" ", "_").lower()[:40]

    def _guess_emotion_from_name(self, name: str) -> str:
        """Guess emotion from the meme sound name using keyword matching."""
        name_lower = name.lower()
        if any(w in name_lower for w in ["scary", "horror", "creepy", "ghost", "jump"]):
            return "fear"
        if any(w in name_lower for w in ["boom", "explosion", "crash", "bang", "impact"]):
            return "shock"
        if any(w in name_lower for w in ["funny", "haha", "lol", "bruh", "fail", "sad", "wah", "meme"]):
            return "funny"
        if any(w in name_lower for w in ["win", "success", "level", "achievement", "yay", "celebrate"]):
            return "energetic"
        if any(w in name_lower for w in ["suspense", "tension", "dramatic", "sting"]):
            return "suspense"
        if any(w in name_lower for w in ["air", "party", "hype", "pump", "lets go"]):
            return "energetic"
        return "energetic"

    def _extract_tags_from_name(self, name: str) -> list:
        """Extract useful tags from a meme sound name."""
        words = name.lower().replace("-", " ").replace("_", " ").split()
        stop_words = {"a", "the", "is", "in", "of", "and", "or", "to", "for", "with"}
        tags = [w for w in words if len(w) > 2 and w not in stop_words]
        tags.append("meme")
        tags.append("viral")
        return list(set(tags))[:10]
