"""Tests for the A->B->C fallback chain, ChatGPT prompt ensure, and
auto-provisioning result handling (no browser needed)."""
import json
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

tmp = tempfile.mkdtemp()
import src.database as db
db.DB_PATH = os.path.join(tmp, "test2.db")
db.init_db()

from src.backend import free_providers as fp
from src.backend import free_agent_client as fac
from src.backend import free_prompting, free_provision

fp.seed_builtin_providers()

# ── 1. ranked_providers: best-first ordering ─────────────────────────────
chain = fp.ranked_providers("video")
ids = [p["id"] for p in chain]
assert "gemini_web" in ids and "veo_web" in ids, ids
print("1a. ranked_providers(video) ->", ids)

# exhausted providers sink to the back, not dropped
fp.update_provider("gemini_web", balance=0, status="active")
chain = fp.ranked_providers("video")
assert chain[-1]["id"] == "gemini_web", [p["id"] for p in chain]
print("1b. zero-balance provider sinks to end of chain OK")
fp.update_provider("gemini_web", balance=10, status="active")

# ── 2. fallback chain: A fails -> B succeeds ─────────────────────────────
calls = {"enqueued": []}


def fake_alive():
    return True


def fake_ranked(kind):
    return [{"id": "aaa", "kinds": [kind], "priority": 1},
            {"id": "bbb", "kinds": [kind], "priority": 2},
            {"id": "ccc", "kinds": [kind], "priority": 3}]


def fake_enqueue_with(provider, kind, prompt="", input_path=None):
    calls["enqueued"].append(provider["id"])
    return "job_" + provider["id"]


def fake_wait_ok(job_id, timeout=1500):
    pid = job_id.replace("job_", "")
    return {"id": job_id, "status": "done",
            "result_path": f"/tmp/{pid}.mp4"}


def fake_wait_fail_first(job_id, timeout=1500):
    if job_id == "job_aaa":
        raise fac.FreeAgentError("aaa logged out")
    return fake_wait_ok(job_id, timeout)


fac.agent_alive = fake_alive
fp.ranked_providers = fake_ranked
fac._enqueue_with = fake_enqueue_with
orig_wait = fac.wait_for
fac.wait_for = fake_wait_fail_first

r = fac.generate_via_agent("video", "test prompt")
assert r["provider_id"] == "bbb", r
assert r["tried_providers"] == ["aaa", "bbb"], r
assert r["result_path"] == "/tmp/bbb.mp4", r
print("2a. fallback A->B OK:", r["tried_providers"])

# pinned provider: fail loud, no fallback
fac.get_provider = lambda pid: {"id": pid} if pid == "aaa" else None
try:
    fac.generate_via_agent("video", "x", provider_id="aaa")
    raise AssertionError("should have raised")
except fac.FreeAgentError as e:
    assert "aaa" in str(e)
    print("2b. pinned failure raises (no silent swap) OK")

# everything fails + provisioning finds nothing -> clear error
fp.ranked_providers = fake_ranked
fac.get_provider = fp.get_provider


def fake_wait_all_fail(job_id, timeout=1500):
    raise fac.FreeAgentError("site exploded")


fac.wait_for = fake_wait_all_fail
free_provision.ensure_capacity = lambda kind, exclude_ids=frozenset(): []
try:
    fac.generate_via_agent("video", "x")
    raise AssertionError("should have raised")
except fac.FreeAgentError as e:
    assert "aaa" in str(e) and "bbb" in str(e) and "ccc" in str(e), str(e)[:200]
    print("2c. total failure lists every tried option OK")

fac.wait_for = orig_wait

# ── 3. ensure_image_prompts / ensure_video_prompts ───────────────────────
chat_calls = []


def fake_ask(system, user, max_new_tokens=2500):
    chat_calls.append(user)
    n = user.count("Scene ")
    return "\n".join(f"{i}. fake prompt number {i} with cinematic detail"
                     for i in range(1, n + 1))


free_prompting._ask_chatgpt = fake_ask

scenes = [
    {"scene_number": 1, "narration": "The city wakes up.",
     "image_prompt": "existing prompt kept"},
    {"scene_number": 2, "narration": "A robot walks in."},
    {"scene_number": 3, "narration": "The sun sets."},
]
out = free_prompting.ensure_image_prompts(scenes, main_script="A robot story")
assert out[0]["image_prompt"] == "existing prompt kept"
assert out[1]["image_prompt"].startswith("fake prompt number 1"), out[1]
assert out[2]["image_prompt"].startswith("fake prompt number 2"), out[2]
assert out[1]["image_prompt_source"] == "chatgpt-free-web"
assert len(chat_calls) == 1, "should batch into a single chat call"
print("3a. ensure_image_prompts fills gaps, batches, keeps existing OK")

# video prompts: pre-existing image_to_video_prompt untouched,
# missing ones written from main script + image prompt
chat_calls.clear()
scenes2 = [
    {"scene_number": 1, "narration": "The city wakes up.",
     "image_prompt": "city dawn",
     "image_to_video_prompt": "existing motion kept"},
    {"scene_number": 2, "narration": "A robot walks in.",
     "image_prompt": "robot street"},
]
out2 = free_prompting.ensure_video_prompts(scenes2, main_script="A robot story")
assert out2[0]["image_to_video_prompt"] == "existing motion kept"
assert out2[1]["image_to_video_prompt"].startswith("fake prompt number 1")
assert out2[1]["image_to_video_prompt_source"] == "chatgpt-free-web"
print("3b. ensure_video_prompts writes motion scripts from script+image OK")

# ── 4. provision result handling ──────────────────────────────────────────
cid = fp.add_candidate("FakeVid", "https://fakevid.example/", ["video"],
                       "free trial", "unit-test", "")
active_result = {"status": "active", "url": "https://fakevid.example/",
                 "name": "FakeVid", "kinds": ["video"],
                 "reason": "signed in; UI detected",
                 "probe": {"video": {"generate_buttons": 1, "prompt_fields": 1}},
                 "account_ref": "acct_abc123"}
prov = free_provision.apply_provision_result(cid, active_result)
assert prov and prov["id"].startswith("auto_"), prov
got = fp.get_provider(prov["id"])
assert got and "video" in got["kinds"], got
assert got["balance_recipe"].get("auto_provisioned") is True
cands = fp.list_candidates("approved")
assert any(c["id"] == cid for c in cands)
print("4a. active provision -> provider promoted OK:", prov["id"])

cid2 = fp.add_candidate("CaptchaSite", "https://captcha.example/", ["video"],
                        "", "unit-test", "")
prov2 = free_provision.apply_provision_result(
    cid2, {"status": "needs_manual", "url": "https://captcha.example/",
           "name": "CaptchaSite", "kinds": ["video"],
           "reason": "captcha appeared during signup"})
assert prov2 is None
cands2 = fp.list_candidates("needs_manual")
assert any(c["id"] == cid2 for c in cands2)
print("4b. needs_manual provision -> candidate flagged OK")

# signup email config round-trip (temp path, not the real repo file)
cfg_tmp = os.path.join(tmp, "agent_config.json")
free_provision._config_path = lambda: cfg_tmp
free_provision.set_signup_email("tester@example.com")
assert free_provision.get_signup_email() == "tester@example.com"
try:
    free_provision.set_signup_email("not-an-email")
    raise AssertionError("should have raised")
except ValueError:
    print("4c. signup email config round-trip + validation OK")

print("\nALL FALLBACK/PROVISION/PROMPT TESTS PASSED")
