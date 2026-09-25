"""Full test for the free-web background agent system (no browser needed)."""
import json
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

# ── temp DB ──────────────────────────────────────────────────────────────
tmp = tempfile.mkdtemp()
import src.database as db
db.DB_PATH = os.path.join(tmp, "test.db")
db.init_db()

from src.backend import free_providers as fp
from src.agent import queue as jq

# ── 1. ledger ────────────────────────────────────────────────────────────
fp.seed_builtin_providers()
providers = fp.list_providers()
ids = {p["id"] for p in providers}
assert {"chatgpt_go", "gemini_web", "veo_web"} <= ids, ids
print("1a. seed_builtin_providers OK:", sorted(ids))

p = fp.pick_provider("image")
assert p is not None and "image" in p["kinds"], p
print("1b. pick_provider(image) ->", p["id"])

p = fp.pick_provider("image", prefer_id="gemini_web")
assert p["id"] == "gemini_web"
print("1c. pick_provider prefer OK")

# live balance update
fp.record_usage("gemini_web", live_balance=17)
g = fp.get_provider("gemini_web")
assert g["balance"] == 17 and g["used_count"] == 1, g
print("1d. record_usage live balance OK (17)")

# usage-counting fallback
fp.update_provider("gemini_web", balance=3)
fp.record_usage("gemini_web", live_balance=None)
g = fp.get_provider("gemini_web")
assert g["balance"] == 2, g
print("1e. usage-counting fallback OK (3 -> 2)")

# auto-retire at zero
fp.update_provider("gemini_web", balance=1, status="active")
fp.record_usage("gemini_web", live_balance=None)
g = fp.get_provider("gemini_web")
assert g["balance"] == 0 and g["status"] == "exhausted", g
print("1f. auto-retire at zero OK")
assert fp.pick_provider("image", prefer_id="gemini_web") is None
print("1g. exhausted provider no longer picked OK")
fp.update_provider("gemini_web", status="active", balance=10)

# candidates
cid = fp.add_candidate("TestGen", "https://testgen.example/", ["image"],
                       "25 free credits", "unit-test", "")
assert cid
assert len(fp.list_candidates()) == 1
prov = fp.approve_candidate(cid)
assert prov["id"].startswith("web_") and prov["status"] == "active"
assert len(fp.list_candidates()) == 0
print("1h. candidate add/approve OK ->", prov["id"])
assert fp.delete_provider(prov["id"])
print("1i. delete_provider OK")

# ── 2. queue ─────────────────────────────────────────────────────────────
jid = jq.enqueue_job("gemini_web", "image", "a cat astronaut")
job = jq.claim_next_job()
assert job and job["id"] == jid and job["status"] == "running"
assert jq.claim_next_job() is None  # already claimed
jq.complete_job(jid, result_path="/tmp/x.png", balance_after=9)
job = jq.get_job(jid)
assert job["status"] == "done" and job["balance_after"] == 9
jid2 = jq.enqueue_job("veo_web", "video", "orbit")
jq.fail_job(jid2, "boom")
assert jq.get_job(jid2)["status"] == "failed"
print("2. queue enqueue/claim/complete/fail OK")

# ── 3. mock end-to-end agent run (stubbed playwright) ─────────────────────
from src.agent.providers.base import FreeWebProvider
from src.agent.providers import registry as reg

class MockProvider(FreeWebProvider):
    id = "mock_web"
    display_name = "Mock"
    login_url = "https://example.com/"
    kinds = ("image",)
    def needs_login(self, page): return False
    def generate(self, page, job, out_dir):
        path = os.path.join(out_dir, "mock_result.png")
        with open(path, "wb") as f:
            f.write(b"\x89PNG mock")
        return {"result_path": path}

reg._REGISTRY["mock_web"] = MockProvider
fp.upsert_provider("mock_web", "Mock", "https://example.com/", kinds=["image"])

class FakeResp:
    status = 200
    headers = {}
    def body(self): return b"x"

class FakeLocator:
    def __init__(self, text=""): self._t = text
    def inner_text(self, timeout=None): return self._t
    @property
    def first(self): return self

class FakePage:
    def on(self, *a): pass
    def remove_listener(self, *a): pass
    def new_page(self): return self
    def close(self): pass
    def locator(self, sel): return FakeLocator("You have 41 credits left")
    @property
    def request(self):
        class R:
            def get(self, url, timeout=None): return FakeResp()
        return R()

class FakeCtx:
    def new_page(self): return FakePage()
    def close(self): pass

class FakePW:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    @property
    def chromium(self):
        class C:
            def launch_persistent_context(self, *a, **k): return FakeCtx()
        return C()

import src.agent.agent as agent_mod
agent_mod._playwright = lambda: (lambda: FakePW())
agent_mod.OUTPUT_DIR = os.path.join(tmp, "agent_out")

mid = jq.enqueue_job("mock_web", "image", "mock prompt")
assert agent_mod.process_one(None, headless=True) is True
mj = jq.get_job(mid)
assert mj["status"] == "done", mj
assert mj["result_path"] and os.path.exists(mj["result_path"]), mj
assert mj["balance_after"] == 41, mj  # regex balance path
mp = fp.get_provider("mock_web")
assert mp["balance"] == 41 and mp["used_count"] == 1, mp
print("3. mock e2e OK (job done, balance 41 scraped via regex, ledger updated)")
assert agent_mod.process_one(None, headless=True) is False  # queue empty
print("3b. empty queue returns False OK")

# ── 4. Flask API ─────────────────────────────────────────────────────────
import app as appmod
client = appmod.app.test_client()
r = client.post("/login", json={"email": "shivamdhagat1@gmail.com",
                                 "password": "Shivam@9806"})
assert r.status_code in (200, 302), (r.status_code, r.get_data(as_text=True)[:200])

r = client.get("/api/free/providers")
assert r.status_code == 200
data = r.get_json()
assert data["status"] == "success" and len(data["providers"]) >= 3
print("4a. GET /api/free/providers OK")

# fail-fast when agent not running (no heartbeat file in temp BASE... note:
# heartbeat path is under real BASE_DIR/data; ensure it doesn't exist)
hb = os.path.join(BASE, "data", "agent_heartbeat.json")
if os.path.exists(hb):
    os.remove(hb)
r = client.post("/api/free/jobs", json={"kind": "image", "prompt": "x"})
assert r.status_code == 400
assert "not running" in r.get_json()["message"], r.get_json()
print("4b. POST /api/free/jobs fail-fast OK (agent down -> 400)")

r = client.get("/api/free/candidates")
assert r.get_json()["status"] == "success"
print("4c. GET /api/free/candidates OK")

r = client.get("/api/free/jobs?limit=5")
d = r.get_json()
assert d["status"] == "success" and "agent_alive" in d
print("4d. GET /api/free/jobs OK")

# ── 5. video strategy rotation ───────────────────────────────────────────
from src.agent.providers.base import StrategyRotator
from src.agent.providers.gemini import GeminiProvider, VIDEO_STRATEGIES as GEM_STRATS
from src.agent.providers.veo import VeoProvider, VIDEO_STRATEGIES as VEO_STRATS

assert "video" in GeminiProvider().kinds, "gemini must do video now"
assert "video" in VeoProvider().kinds
print("5a. gemini_web + veo_web both serve kind=video OK")

for pid, strats in (("gemini_web", GEM_STRATS), ("veo_web", VEO_STRATS)):
    assert len(strats) >= 3, (pid, len(strats))
    assert all({"name", "desc", "run"} <= set(s) for s in strats), pid
    assert len({s["name"] for s in strats}) == len(strats), "dup strategy names"
    sf = os.path.join(tmp, f"strat_{pid}.json")
    rot = StrategyRotator(pid, strats, state_file=sf)
    picks = [rot.pick()["name"] for _ in range(10)]
    assert all(a != b for a, b in zip(picks, picks[1:])), (pid, picks)
    assert rot.last_used() == picks[-1]
    # persisted: a fresh rotator continues the no-repeat chain
    rot2 = StrategyRotator(pid, strats, state_file=sf)
    assert rot2.last_used() == picks[-1]
    assert rot2.pick()["name"] != picks[-1]
    print(f"5b. {pid}: {len(strats)} recorded strategies, 10 picks no-repeat OK ->",
          [s for s in picks[:4]], "...")

# gemini is now eligible for video jobs through the ledger
fp.seed_builtin_providers()  # re-seed picks up kinds=["image","video"]
g = fp.get_provider("gemini_web")
assert "video" in g["kinds"], g["kinds"]
pv = fp.pick_provider("video")
assert pv is not None and "video" in pv["kinds"], pv
print("5c. pick_provider(video) ->", pv["id"], "(gemini_web eligible)")

print("\nALL TESTS PASSED")
