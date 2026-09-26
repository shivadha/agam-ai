"""Tests for the node failure policy: fallback vs fail-the-whole-cycle. No network."""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from src.engine import node_fallbacks
from src.engine.node_fallbacks import (
    fallback, resolve_policy, attempt_fallbacks, FALLBACK, FAIL,
)

# ── 1. resolve_policy ──────────────────────────────────────────────────
assert resolve_policy({}, {}) == FALLBACK, "default must be fallback"
assert resolve_policy({"on_failure": "fail"}, {}) == FAIL
assert resolve_policy({"on_failure": "Fail whole cycle"}, {}) == FAIL, "UI label"
assert resolve_policy({"on_failure": "Try other ways (fallback)"}, {}) == FALLBACK, "UI label"
assert resolve_policy({"on_failure": "fallback"}, {}) == FALLBACK
assert resolve_policy({}, {"failure_policy": "fail"}) == FAIL, "workflow default"
assert resolve_policy({"on_failure": "fallback"}, {"failure_policy": "fail"}) == FALLBACK, "node wins"
print("1. resolve_policy: OK")


# ── 2. attempt_fallbacks ───────────────────────────────────────────────
class FakeEngine:
    def _find_in_state(self, key):
        return None


eng = FakeEngine()
calls = []


@fallback("test-boom", name="first-fails")
def _s1(engine, node, node_data, inputs, err):
    calls.append("s1")
    raise RuntimeError("s1 boom")


@fallback("test-boom", name="second-wins")
def _s2(engine, node, node_data, inputs, err):
    calls.append("s2")
    return {"status": "success", "node_type": "test-boom", "x": 1}


res = attempt_fallbacks(eng, {"id": "n1"}, "test-boom", {}, {}, RuntimeError("primary"))
assert res["status"] == "success" and res["recovered_via"] == "second-wins", res
assert "recovery_note" in res and calls == ["s1", "s2"], calls


@fallback("test-allfail", name="nope")
def _s3(engine, node, node_data, inputs, err):
    raise RuntimeError("x")


assert attempt_fallbacks(eng, {"id": "n2"}, "test-allfail", {}, {}, RuntimeError("p")) is None
assert attempt_fallbacks(eng, {"id": "n3"}, "nope-type", {}, {}, RuntimeError("p")) is None
print("2. attempt_fallbacks: OK")


# ── 3. orchestrator integration ────────────────────────────────────────
from src.engine.orchestrator import WorkflowEngine


def _wf(nodes):
    return {"nodes": nodes,
            "edges": [{"source": "n1", "target": "n2"}]}


# 3a. on_failure=fail -> whole cycle halts immediately
w = _wf([{"id": "n1", "type": "score-script", "data": {"on_failure": "Fail whole cycle"}},
         {"id": "n2", "type": "gen-title", "data": {}}])
state = WorkflowEngine(w).run()
assert state["n1"]["status"] == "error" and state["n1"]["on_failure"] == "fail", state["n1"]
assert "n2" not in state, "fail policy must halt the cycle before n2"
print("3a. fail-policy halts cycle: OK")

# 3b. default fallback policy, no strategies for score-script -> error + halt
w = _wf([{"id": "n1", "type": "score-script", "data": {}},
         {"id": "n2", "type": "gen-title", "data": {}}])
state = WorkflowEngine(w).run()
assert state["n1"]["status"] == "error" and state["n1"]["on_failure"] == "fallback", state["n1"]
assert "n2" not in state, "exhausted fallbacks must still halt"
print("3b. exhausted fallbacks halt: OK")

# 3c. recovery -> cycle continues
@fallback("score-script", name="test-recovery")
def _rec(engine, node, node_data, inputs, err):
    return {"status": "success", "node_type": "score-script",
            "scenes": [{"narration": "x", "image_prompt": "y"}]}


w = _wf([{"id": "n1", "type": "score-script", "data": {}},
         {"id": "n2", "type": "gen-title", "data": {}}])
state = WorkflowEngine(w).run()
assert state["n1"]["status"] == "success", state["n1"]
assert state["n1"]["recovered_via"] == "test-recovery", state["n1"]
assert state["n2"]["status"] == "success", "cycle must continue after recovery"
print("3c. fallback recovery continues cycle: OK")


# ── 4. template-script fallback yields valid scenes ────────────────────
res = node_fallbacks._fb_script_template(
    FakeEngine(), {"id": "t"}, {"topic_title": "Mars"}, {}, RuntimeError("x"))
assert res["status"] == "success" and len(res["scenes"]) >= 3, res
assert all(s.get("narration") and s.get("image_prompt") for s in res["scenes"])
assert res["script"] and res["title"]
print("4. template-script fallback: OK")

print("ALL NODE-FALLBACK TESTS PASSED")
