"""Tests for the Scrapling-upgraded scout (no network; all fetches mocked)."""
import json
import os
import sys
import tempfile
import types

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

# ── temp DB ──────────────────────────────────────────────────────────────
tmp = tempfile.mkdtemp()
import src.database as db
db.DB_PATH = os.path.join(tmp, "test.db")
db.init_db()

from src.agent import scout
from src.backend import free_providers as ledger

print("scrapling available in sandbox:", scout.SCRAPLING_AVAILABLE)

DDG_HTML = """
<html><body>
<div class="result">
  <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Ffreeai.example%2F&rut=abc">
    FreeAI Example - 100 free credits image generator</a>
</div>
<div class="result">
  <a class="result__a" href="https://videofree.example/">VideoFree - free AI video</a>
</div>
<div class="result">
  <a class="result__a" href="https://www.reddit.com/r/test/">should be skipped</a>
</div>
</body></html>
"""


def sel(html, url="https://x.test"):
    assert scout._ScraplingSelector is not None, "need scrapling parser"
    return scout._ScraplingSelector(content=html, url=url)


# ── 1. DDG redirect unwrap ───────────────────────────────────────────────
assert scout._unwrap_ddg("//duckduckgo.com/l/?uddg=https%3A%2F%2Fa.b%2F&x=1") == "https://a.b/"
assert scout._unwrap_ddg("https://plain.example/") == "https://plain.example/"
print("1. _unwrap_ddg OK")

# ── 2. ddg_sweep parsing via Scrapling selectors ─────────────────────────
scout._fetch_page = lambda url, timeout=20: (sel(DDG_HTML, url), "fast")
scout._source_stats.clear()
found = scout.ddg_sweep()
urls = {c["url"] for c in found}
assert "https://freeai.example/" in urls, urls
assert "https://videofree.example/" in urls, urls
assert not any("reddit.com" in u for u in urls), urls  # skip-list works
names = {c["name"] for c in found}
assert any("FreeAI Example" in n for n in names), names
kinds = [c["kinds"] for c in found if c["url"] == "https://videofree.example/"]
assert ["video"] in kinds, kinds  # kinds come from the query ("...video...")
assert any("100 free credits" in c["quota_hint"] for c in found), found
print("2. ddg_sweep via Scrapling selectors OK:", len(found), "candidates")

# ── 3. reddit_sweep JSON parsing ─────────────────────────────────────────
payload = {"data": {"children": [
    {"data": {"title": "Best free video generator 2026",
              "url": "https://clipfree.example/app",
              "selftext": "gives 25 free credits daily",
              "permalink": "/r/aivideo/comments/xyz"}},
    {"data": {"title": "github link", "url": "https://github.com/x",
              "selftext": "", "permalink": "/r/aivideo/comments/x"}},
]}}
scout._fetch_page = lambda url, timeout=20: (
    types.SimpleNamespace(text=json.dumps(payload), status=200), "fast")
scout._source_stats.clear()
found = scout.reddit_sweep()
by_url = {}
for c in found:
    by_url.setdefault(c["url"], c)
assert set(by_url) == {"https://clipfree.example/"}, by_url  # github skipped
c = by_url["https://clipfree.example/"]
assert "25 free credits" in c["quota_hint"], c
assert any(x["kinds"] == ["video"] for x in found), found
print("3. reddit_sweep OK:", c["name"][:40])

# ── 4. fetch fallback chain: fast fails -> stealth ──────────────────────
real_fast, real_stealth, real_legacy = (scout._fetch_fast, scout._fetch_stealth,
                                       scout._fetch_legacy)
import importlib
importlib.reload(scout)  # restore real _fetch_page/_fetch_* after mocks above
real_fast, real_stealth, real_legacy = (scout._fetch_fast, scout._fetch_stealth,
                                       scout._fetch_legacy)
fake_page = types.SimpleNamespace(text="hello world " * 50, status=200)
scout.SCRAPLING_AVAILABLE = True
scout._fetch_fast = lambda url, timeout=20: (_ for _ in ()).throw(
    RuntimeError("boom"))
scout._fetch_stealth = lambda url, timeout=40: fake_page
page, tier = scout._fetch_page("https://x.test/")
assert tier == "stealth" and page is fake_page, tier
print("4a. fast->stealth escalation OK")

# both scrapling tiers fail -> legacy
scout._fetch_stealth = lambda url, timeout=40: (_ for _ in ()).throw(
    RuntimeError("boom2"))
scout._fetch_legacy = lambda url, timeout=20: fake_page
page, tier = scout._fetch_page("https://x.test/")
assert tier == "legacy", tier
print("4b. stealth->legacy escalation OK")

# all fail -> (None, 'none')
scout._fetch_legacy = lambda url, timeout=20: (_ for _ in ()).throw(
    RuntimeError("boom3"))
page, tier = scout._fetch_page("https://x.test/")
assert page is None and tier == "none", tier
print("4c. total failure -> (None, 'none') OK")
scout._fetch_fast, scout._fetch_stealth, scout._fetch_legacy = (
    real_fast, real_stealth, real_legacy)

# ── 5. block detection ───────────────────────────────────────────────────
blocked = types.SimpleNamespace(text="Just a moment... checking your browser "
                                     + "x" * 500, status=200)
assert scout._is_blocked(blocked) is True
assert scout._is_blocked(types.SimpleNamespace(text="real content " * 50,
                                              status=200)) is False
assert scout._is_blocked(
    types.SimpleNamespace(text="real content " * 50, status=403)) is True
print("5. _is_blocked OK")

# ── 6. precheck enriches quota + signup signal ───────────────────────────
home = sel("<html><body><h1>FreeGen</h1><p>Get 50 free credits every day. "
           "Sign up to generate your first video.</p></body></html>")
scout._fetch_page = lambda url, timeout=15: (home, "fast")
info = scout.precheck("https://freegen.example")
assert info["reachable"] is True
assert "50 free credits" in info["quota_hint"], info
assert info["needs_signup"] is True, info
print("6. precheck OK:", info["quota_hint"])

# ── 7. run_scout orchestration (sweeps mocked, real ledger) ───────────────
scout.reddit_sweep = lambda: [{"name": "A", "url": "https://a.example/",
                               "kinds": ["image"], "quota_hint": "",
                               "source": "t", "source_url": ""}]
scout.ddg_sweep = lambda: [{"name": "A dup", "url": "https://a.example/",
                            "kinds": ["image"], "quota_hint": "",
                            "source": "t", "source_url": ""},
                           {"name": "B", "url": "https://b.example/",
                            "kinds": ["video"], "quota_hint": "free tier",
                            "source": "t", "source_url": ""}]
scout.precheck = lambda url: ({"quota_hint": "10 free credits · signup required",
                               "needs_signup": True, "reachable": True}
                              if "a.example" in url else
                              {"quota_hint": "", "needs_signup": False,
                               "reachable": False})
res = scout.run_scout()
assert res["scanned"] == 3 and res["added"] == 2, res  # dup url deduped
assert res["prechecked"] == 1, res
cands = {c["url"]: c for c in ledger.list_candidates()}
assert "10 free credits" in cands["https://a.example/"]["quota_hint"], cands
assert cands["https://b.example/"]["quota_hint"] == "free tier", cands
print("7. run_scout orchestration OK:", res)

# ── 8. scout memory hooks don't crash and record ──────────────────────────
from src.agent import memory as mem
prefs = mem.recall("scout", kind_filter="preference")
assert isinstance(prefs, list)
print("8. memory hooks OK (", len(prefs), "preferences )")

print("\nALL SCOUT-SCRAPLING TESTS PASSED")
