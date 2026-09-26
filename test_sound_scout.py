"""Tests for the Scrapling-powered sound library (no network; all fetches mocked)."""
import os
import sys
import tempfile
import types

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

# ── temp DB + temp assets BEFORE importing library (paths read at import) ──
tmp = tempfile.mkdtemp()
os.environ["PULSEFORGE_DB_PATH"] = os.path.join(tmp, "sounds_test.db")
ASSETS_TMP = os.path.join(tmp, "sounds")
os.makedirs(os.path.join(ASSETS_TMP, "meme"), exist_ok=True)
os.makedirs(os.path.join(ASSETS_TMP, "sfx"), exist_ok=True)
os.makedirs(os.path.join(ASSETS_TMP, "music"), exist_ok=True)

from src.backend.audio_agent import sound_scout
from src.backend.audio_agent import scraper as scraper_mod
from src.backend.audio_agent import library as library_mod

# Point the scraper at the temp assets dir (library keeps its own ASSETS_DIR;
# we only exercise scraper._index_record + library upsert here).
scraper_mod.ASSETS_DIR = ASSETS_TMP

print("scout available:", sound_scout._SCOUT_AVAILABLE)
assert sound_scout._SCOUT_AVAILABLE, "scout fetch chain must import"


def fake_page(html):
    # text=html keeps the scout's _is_blocked() happy (len > 200, no markers)
    return types.SimpleNamespace(html=html, text=html)


# ── fixtures ─────────────────────────────────────────────────────────────
MYINSTANTS_HTML = """
<html><body>
<div class="instant">
  <a href="/en/media/bruh-sound-effect/" title="Bruh Sound Effect"><img alt="Bruh Sound Effect"></a>
  <div class="instant-btn"><div title="Play" onclick="play('/media/sounds/bruh-sound-effect_WTLZOxM.mp3')"></div></div>
  <div class="instant-name">Bruh Sound Effect</div>
</div>
<div class="instant">
  <a href="/en/media/vine-boom/" title="Vine Boom Sound"><img alt="Vine Boom Sound"></a>
  <div class="instant-btn"><div title="Play" onclick='play("/media/sounds/vine-boom_abc123.mp3")'></div></div>
</div>
<div class="instant">
  <a href="/en/media/bruh-sound-effect-2/" title="Bruh Sound Effect 2"></a>
  <div onclick="play('/media/sounds/bruh-sound-effect_WTLZOxM.mp3')"></div>
</div>
</body></html>
"""

PIXABAY_HTML = """
<html><body>
<div class="result">
  <img alt="Epic cinematic whoosh transition" src="x.jpg">
  <audio src="https://cdn.pixabay.com/audio/2024/01/01/audio_aaa111.mp3"></audio>
</div>
<div class="result">
  <img alt="Big boom impact hit" src="y.jpg">
  <audio src="https://cdn.pixabay.com/audio/2024/02/02/audio_bbb222.mp3"></audio>
</div>
</body></html>
"""

MIXKIT_HTML = """
<html><body>
<!-- Mixkit free sound effects are royalty-free for commercial use. Browse categories. -->
<div class="item">
  <h3>Fast Whoosh Sweep</h3>
  <p>A quick airy whoosh sweep, perfect for transitions and fast movement.</p>
  <a href="https://assets.mixkit.co/sfx/preview/mixkit-fast-whoosh-123.mp3">Download</a>
</div>
</body></html>
"""


# ── 1. MyInstants trending parse ─────────────────────────────────────────
sound_scout._fetch_page = lambda url, timeout=25: (fake_page(MYINSTANTS_HTML), "fast")
recs = sound_scout.scrape_myinstants_trending(limit=10)
assert len(recs) == 2, f"expected 2 unique memes, got {len(recs)}"  # dup mp3 deduped
names = [r["name"] for r in recs]
assert any("Bruh Sound Effect" in n for n in names), names
assert any("Vine Boom" in n for n in names), names
assert all(r["category"] == "meme" for r in recs)
assert all(r["audio_url"].startswith("https://www.myinstants.com/media/sounds/") for r in recs)
assert all("meme" in r["tags"] for r in recs)
print("1. myinstants trending parse OK:", names)


# ── 2. Pixabay SFX parse ─────────────────────────────────────────────────
sound_scout._fetch_page = lambda url, timeout=25: (fake_page(PIXABAY_HTML), "stealth")
recs = sound_scout.scrape_pixabay_sfx("whoosh transition", limit=10)
assert len(recs) == 2, recs
assert any("whoosh" in r["name"].lower() for r in recs), [r["name"] for r in recs]
assert all(r["category"] == "sfx" and r["source"] == "pixabay" for r in recs)
assert all(r["audio_url"].startswith("https://cdn.pixabay.com/audio/") for r in recs)
print("2. pixabay sfx parse OK:", [r["name"] for r in recs])


# ── 3. Pixabay music parse ───────────────────────────────────────────────
recs = sound_scout.scrape_pixabay_music("phonk viral", limit=10)
assert len(recs) == 2 and all(r["category"] == "music" for r in recs), recs
print("3. pixabay music parse OK")


# ── 4. Mixkit parse ──────────────────────────────────────────────────────
sound_scout._fetch_page = lambda url, timeout=25: (fake_page(MIXKIT_HTML), "fast")
recs = sound_scout.scrape_mixkit_sfx("whoosh", limit=10)
assert len(recs) == 1, recs
assert recs[0]["name"] == "Fast Whoosh Sweep", recs[0]["name"]
assert recs[0]["source"] == "mixkit" and recs[0]["category"] == "sfx"
print("4. mixkit parse OK")


# ── 5. _index_record: upsert + fake download ─────────────────────────────
lib = library_mod.AudioLibrary()
scr = scraper_mod.AudioScraper(library=lib)

def fake_download(url, local_path):
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "wb") as f:
        f.write(b"ID3" + b"\x00" * 2000)
    return True, 2

scr._download = fake_download
rec = {"name": "Bruh Sound Effect", "audio_url": "https://www.myinstants.com/media/sounds/bruh.mp3",
       "page_url": "https://www.myinstants.com/en/trending/", "source": "myinstants",
       "category": "meme", "subcategory": "trending-meme",
       "tags": ["bruh", "meme", "viral", "trending"], "emotion": "funny", "energy_level": 6}
outcome = scr._index_record(rec)
assert outcome == "downloaded", outcome
# Second index of the same record -> exists (no re-download)
outcome2 = scr._index_record(rec)
assert outcome2 == "exists", outcome2
memes = lib.find_by_tags(["bruh"], limit=5)
assert memes and memes[0]["is_downloaded"] == 1, memes
assert os.path.exists(memes[0]["local_path"])
print("5. _index_record upsert+download OK:", memes[0]["local_path"])


# ── 6. build_sfx_timeline_from_library with fake library ─────────────────
import src.backend.sfx_engine as sfx_engine

FAKE_SFX = [
    {"id": 101, "name": "Epic Whoosh", "local_path": os.path.join(ASSETS_TMP, "sfx", "whoosh.mp3"),
     "energy_level": 8},
    {"id": 102, "name": "Boom Impact", "local_path": os.path.join(ASSETS_TMP, "sfx", "boom.mp3"),
     "energy_level": 9},
    {"id": 103, "name": "Swift Swoosh Transition", "local_path": os.path.join(ASSETS_TMP, "sfx", "swoosh.mp3"),
     "energy_level": 6},
]
for s in FAKE_SFX:
    with open(s["local_path"], "wb") as f:
        f.write(b"ID3" + b"\x00" * 500)

class FakeLib:
    def find_by_tags(self, tags, limit=10):
        tl = [t.lower() for t in tags]
        return [s for s in FAKE_SFX
                if any(t in s["name"].lower() for t in tl)][:limit]
    def find_by_emotion(self, emotion, category=None, limit=10):
        return []

orig_lib = library_mod.AudioLibrary
library_mod.AudioLibrary = FakeLib
try:
    scenes = [
        {"start_time": 0.0, "sfx": "whoosh"},
        {"start_time": 3.0, "sfx": "impact"},
        {"start_time": 3.5, "sfx": "whoosh"},   # too close to 3.0 -> dropped
        {"start_time": 8.0},                     # boundary -> transition whoosh
    ]
    tl = sfx_engine.build_sfx_timeline_from_library(scenes, total_duration=10.0)
    assert len(tl) == 3, tl
    assert tl[0]["time"] == 0.0 and "whoosh" in tl[0]["path"]
    assert tl[1]["time"] == 3.0 and "boom" in tl[1]["path"]
    assert tl[2]["time"] == 8.0
    assert all("volume" in e and "path" in e for e in tl)
    print("6. build_sfx_timeline_from_library OK:", [(e["time"], os.path.basename(e["path"])) for e in tl])
    # Empty library -> []
    class EmptyLib:
        def find_by_tags(self, tags, limit=10): return []
        def find_by_emotion(self, emotion, category=None, limit=10): return []
    library_mod.AudioLibrary = EmptyLib
    assert sfx_engine.build_sfx_timeline_from_library(scenes, 10.0) == []
    print("   empty-library fallback OK")
finally:
    library_mod.AudioLibrary = orig_lib


# ── 7. orchestrator _collect_sfx_timelines merges all nodes ──────────────
from src.engine.orchestrator import WorkflowEngine
eng = WorkflowEngine({"nodes": [], "edges": []})
eng.state.set("gen-sfx", {"sfx_timeline": [{"time": 2.0, "path": "/a.wav", "volume": 0.7}]})
eng.state.set("meme-sound", {"sfx_timeline": [{"time": 0.5, "path": "/m.mp3", "volume": 0.8}]})
eng.state.set("gen-script", {"script": "hello"})  # no timeline -> ignored
merged = eng._collect_sfx_timelines()
assert len(merged) == 2, merged
assert merged[0]["time"] == 0.5 and merged[1]["time"] == 2.0, merged  # sorted
print("7. _collect_sfx_timelines merge OK")


# ── 8. discover_trending never raises, dedupes ───────────────────────────
def _fake_fetch_8(url, timeout=25):
    if "myinstants" in url:
        return fake_page(MYINSTANTS_HTML), "fast"
    return fake_page("<html></html>"), "fast"

sound_scout._fetch_page = _fake_fetch_8
out = sound_scout.discover_trending(max_per_source=5, polite_delay=0)
assert set(out.keys()) == {"meme", "sfx", "music"}
assert len(out["meme"]) == 2, out["meme"]
print("8. discover_trending OK (best-effort, deduped)")


print("\nALL SOUND LIBRARY TESTS PASSED")
