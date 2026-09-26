"""Tests for the agent memory system (no browser needed)."""
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

from src.agent import memory as mem
from src.agent.providers import base as pbase

# ── 1. remember / recall ─────────────────────────────────────────────────
m1 = mem.remember("veo_web", "fact", "generate button labelled 'Create'")
assert m1 and m1["scope"] == "veo_web" and m1["kind"] == "fact"
print("1a. remember OK:", m1["content"])

# duplicate reinforces instead of duplicating
m2 = mem.remember("veo_web", "fact", "  Generate Button Labelled 'Create' ")
assert m2["id"] == m1["id"] and m2["occurrences"] == 2, m2
assert m2["confidence"] > m1["confidence"]
print("1b. dedupe+reinforce OK (occurrences=2)")

mem.remember("global", "lesson", "chatgpt_go keeps logging out")
mem.remember("veo_web", "preference", "strategy 'video_chip' works for video")

got = mem.recall("veo_web")
scopes = [(m["scope"], m["kind"]) for m in got]
assert ("veo_web", "fact") in scopes and ("global", "lesson") in scopes, scopes
# provider-scoped sorts before global
assert got[0]["scope"] == "veo_web", got[0]
print("1c. recall OK (provider-first, global included):", len(got))

texts = mem.recall_texts("veo_web")
assert any(t.startswith("[known]") and "Create" in t for t in texts), texts
print("1d. recall_texts OK:", texts[0])

# ── 2. reinforce / forget ────────────────────────────────────────────────
c0 = mem.recall("veo_web", kind_filter="fact")[0]["confidence"]
mem.reinforce(m1["id"], success=True)
c1 = mem.recall("veo_web", kind_filter="fact")[0]["confidence"]
assert c1 > c0
mem.reinforce(m1["id"], success=False)
c2 = mem.recall("veo_web", kind_filter="fact")[0]["confidence"]
assert c2 < c1
print("2a. reinforce OK (up on success, down on failure)")

assert mem.forget(m1["id"]) is True
assert mem.recall("veo_web", kind_filter="fact") == []
assert mem.forget(999999) is False
print("2b. forget OK")

# ── 3. learn_from_job ────────────────────────────────────────────────────
job = {"id": "j1", "provider_id": "gemini_web", "kind": "video"}
mem.learn_from_job(job, ok=False, detail="Login required: session expired")
mem.learn_from_job(job, ok=False, detail="logged out, please sign in")
lessons = [m for m in mem.recall("gemini_web", kind_filter="lesson")
           if m["scope"] == "gemini_web"]
assert len(lessons) == 1 and lessons[0]["occurrences"] == 2, lessons
assert "login required" in lessons[0]["content"]
print("3a. failure -> deduped lesson OK:", lessons[0]["content"])

job2 = {"id": "j2", "provider_id": "chatgpt_go", "kind": "text",
        "strategy": "chat_box"}
mem.learn_from_job(job2, ok=True, detail="chat_box")
facts = mem.recall("chatgpt_go", kind_filter="fact")
prefs = mem.recall("chatgpt_go", kind_filter="preference")
assert any("last successful text" in f["content"] for f in facts), facts
assert any("chat_box" in p["content"] for p in prefs), prefs
# success twice -> still one "last successful" fact (upsert, not log)
mem.learn_from_job(job2, ok=True, detail="chat_box")
facts2 = [f for f in mem.recall("chatgpt_go", kind_filter="fact")
          if "last successful text" in f["content"]]
assert len(facts2) == 1 and facts2[0]["occurrences"] == 2
print("3b. success -> last-known-good fact + preference OK")

# repeated login failures escalate to a global lesson
for _ in range(3):
    mem.learn_from_job(job, ok=False, detail="LoginRequired: logged out")
glob = mem.recall("global", kind_filter="lesson")
assert any("gemini_web keeps logging out" in g["content"] for g in glob), glob
print("3c. repeated login failures -> global escalation OK")

# ── 4. error signatures ──────────────────────────────────────────────────
assert "quota" in mem._error_signature("credits exhausted for today")
assert "captcha" in mem._error_signature("blocked: robot challenge")
assert "timed out" in mem._error_signature("page timed out after 30s")
assert "selectors" in mem._error_signature("element not found: bad selector")
print("4. error signatures OK")

# ── 5. provider helper ───────────────────────────────────────────────────
class P(pbase.FreeWebProvider):
    id = "x"

p = P()
jobm = {"agent_memories": ["[known] (x) foo"]}
assert p.memories(jobm) == ["[known] (x) foo"]
assert p.memories({}) == []
print("5. FreeWebProvider.memories OK")

# ── 6. provision hint parsing ────────────────────────────────────────────
from src.agent import provision as prov
hints = ["[known] (auto_foo.com) generate button labelled 'Create'"]
assert prov._hinted_button_labels(hints) == ["Create"]
assert prov._hinted_button_labels(["[lesson] blah"]) == []
print("6. hint label parsing OK")

# ── 7. prune ─────────────────────────────────────────────────────────────
old = mem.remember("veo_web", "lesson", "stale lesson xyz")
with db._db_lock:
    conn = db.get_db()
    try:
        conn.execute("UPDATE agent_memory SET confidence=0.05,"
                     " updated_at=DATETIME('now','-90 days') WHERE id=?",
                     (old["id"],))
        conn.commit()
    finally:
        conn.close()
n = mem.prune(days=60, min_confidence=0.2)
assert n == 1, n
print("7. prune OK")

print("\nALL AGENT-MEMORY TESTS PASSED")
