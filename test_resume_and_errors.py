"""
test_resume_and_errors.py — workflow run persistence, resume-from-failed,
per-node regenerate, Errors-tab data, and the gen-hook chain.

Runs against a throwaway SQLite DB (never touches the user's real DB).
"""
import io
import json
import os
import sqlite3
import sys
import tempfile

import pytest

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)

_TMP = tempfile.mkdtemp(prefix="agam_resume_test_")
os.environ["AGAM_TEST_DB"] = os.path.join(_TMP, "test.db")

import src.database as database

# Point the module at the throwaway DB before init.
database.DB_PATH = os.environ["AGAM_TEST_DB"]


@pytest.fixture(scope="module", autouse=True)
def _init_db():
    database.init_db()
    yield


def _wf(*nodes):
    return {
        "nodes": [
            {"id": n[0], "type": n[1], "data": n[2] if len(n) > 2 else {}}
            for n in nodes
        ],
        "edges": [],
    }


def _engine(payload, run_id=None):
    from src.engine.orchestrator import WorkflowEngine
    return WorkflowEngine(payload, run_id=run_id)


def _run_status(run_id: str) -> str:
    """Run status lives in the DB (finish_workflow_run), not on the engine."""
    from src.database import get_workflow_runs
    rows = [r for r in get_workflow_runs(limit=200) if r["run_id"] == run_id]
    assert rows, f"no workflow_runs row for {run_id}"
    return rows[0]["status"]


# ── 1. Persistence of a clean run ────────────────────────────────────────────

def test_success_run_persists_nodes_and_run_row():
    from src.database import get_node_results, get_workflow_runs
    wf = _wf(("n1", "manual-trigger", {}), ("n2", "manual-trigger", {}))
    eng = _engine(wf)
    results = eng.run()
    assert _run_status(eng.run_id) == "success"
    assert results["n1"]["status"] == "success"

    rows = get_node_results(eng.run_id)
    assert {r["node_id"] for r in rows} == {"n1", "n2"}
    n1 = next(r for r in rows if r["node_id"] == "n1")
    assert n1["status"] == "success"
    assert json.loads(n1["result_json"])["status"] == "success"

    runs = get_workflow_runs(limit=50)
    mine = [r for r in runs if r["run_id"] == eng.run_id]
    assert len(mine) == 1 and mine[0]["status"] == "success"


# ── 2. Failure: error persisted, error logged, run halts ─────────────────────

def test_failed_node_persists_error_and_logs():
    """gen-desc with a free-web model raises (no agent in sandbox) -> the
    engine must persist the error, log it, and halt at that node."""
    from src.database import get_node_logs, get_node_results
    wf = _wf(
        ("n1", "manual-trigger", {}),
        ("n2", "gen-desc", {"model": "free-web:chatgpt_go"}),
        ("n3", "manual-trigger", {}),
    )
    eng = _engine(wf)
    eng.run()
    assert _run_status(eng.run_id) == "failed"
    assert "n3" not in eng.state.get_all()  # halted before n3

    rows = get_node_results(eng.run_id)
    n2 = next(r for r in rows if r["node_id"] == "n2")
    assert n2["status"] == "error"
    assert n2["error"]  # exact reason stored

    logs = get_node_logs(eng.run_id, level="error")
    assert logs, "expected error log rows for the failed node"
    assert any(l["node_id"] == "n2" for l in logs)
    assert eng.first_failed_node() == "n2"


# ── 3. Resume from failed node ───────────────────────────────────────────────

def test_resume_skips_prior_success_and_finishes():
    from src.database import get_node_results, get_workflow_runs
    wf_fail = _wf(
        ("n1", "manual-trigger", {}),
        ("n2", "gen-desc", {"model": "free-web:chatgpt_go"}),
        ("n3", "manual-trigger", {}),
    )
    eng1 = _engine(wf_fail)
    eng1.run()
    assert _run_status(eng1.run_id) == "failed"
    run_id = eng1.run_id

    # User fixes the node (swap the failing config for a trivial one).
    wf_fixed = _wf(
        ("n1", "manual-trigger", {}),
        ("n2", "manual-trigger", {"fixed": True}),
        ("n3", "manual-trigger", {}),
    )
    eng2 = _engine(wf_fixed, run_id=run_id)
    results = eng2.run(resume_from_node="n2")

    assert _run_status(run_id) == "success"
    assert results["n2"]["status"] == "success"
    assert results["n3"]["status"] == "success"

    # n1 must NOT have been re-executed: still exactly one attempt.
    con = sqlite3.connect(database.DB_PATH)
    try:
        n1_attempts = con.execute(
            "SELECT COUNT(*) FROM node_results WHERE run_id=? AND node_id='n1'",
            (run_id,)).fetchone()[0]
        n2_attempts = con.execute(
            "SELECT COUNT(*) FROM node_results WHERE run_id=? AND node_id='n2'",
            (run_id,)).fetchone()[0]
    finally:
        con.close()
    assert n1_attempts == 1, f"n1 was re-executed on resume ({n1_attempts} attempts)"
    assert n2_attempts == 2, "n2 should have error attempt + success attempt"

    # Latest-attempt view shows success for n2; run row flipped to success.
    rows = get_node_results(run_id)
    n2 = next(r for r in rows if r["node_id"] == "n2")
    assert n2["status"] == "success"
    assert _run_status(run_id) == "success"


# ── 4. Single-node regenerate ────────────────────────────────────────────────

def test_rerun_node_regenerates_single_node():
    from src.database import get_node_result_history
    wf = _wf(("n1", "manual-trigger", {"topic": "Old Topic"}),
             ("n2", "manual-trigger", {}))
    eng = _engine(wf)
    eng.run()

    out = eng.rerun_node("n1", {"topic": "New Topic"})  # result dict itself
    assert out["status"] == "success"
    assert out["topic_title"] == "New Topic", "override must change the output"

    hist = get_node_result_history(eng.run_id, "n1")
    assert len(hist) == 2, "rerun must store a second attempt"
    # History is ordered oldest-first: hist[-1] is the regenerated attempt.
    assert json.loads(hist[-1]["result_json"])["topic_title"] == "New Topic"
    assert json.loads(hist[0]["result_json"])["topic_title"] == "Old Topic"

    # n2 untouched — still one attempt.
    con = sqlite3.connect(database.DB_PATH)
    try:
        n2_attempts = con.execute(
            "SELECT COUNT(*) FROM node_results WHERE run_id=? AND node_id='n2'",
            (eng.run_id,)).fetchone()[0]
    finally:
        con.close()
    assert n2_attempts == 1


# ── 5. gen-hook: string viral_angle + full chain ─────────────────────────────

def test_gen_hook_survives_string_viral_angle():
    """The historical crash: extract-viral-angle stores viral_angle as a plain
    string; generate_hook must not die on it."""
    wf = _wf(
        ("va", "extract-viral-angle", {"topic": "AI coding agents"}),
        ("gh", "gen-hook", {"topic": "AI coding agents", "model": "Groq (Qwen 3.8 27B) [Free]"}),
    )
    eng = _engine(wf)
    results = eng.run()
    gh = results["gh"]
    assert gh["status"] == "success", f"gen-hook failed: {gh.get('error')}"
    assert gh["hook"], "empty hook"
    assert gh["hook_source"] in ("llm", "scraper", "template")


def test_hook_scraper_adapt_and_cache():
    from src.backend.hook_scraper import adapt_title_to_hook, _save_cache, _load_cache
    hook = adapt_title_to_hook("AI Coding Agents Are Replacing Junior Developers Fast")
    assert hook and len(hook.split()) <= 8
    _save_cache({**_load_cache(), "unit topic": ["Hook One", "Hook Two"]})
    assert _load_cache()["unit topic"] == ["Hook One", "Hook Two"]


# ── 6. Agent fixes ───────────────────────────────────────────────────────────

def test_chatgpt_error_banner_raises():
    """An error banner must raise, never be returned as the script text."""
    from src.agent.providers.chatgpt import ChatGPTProvider
    from src.agent.providers.base import ProviderError

    class FakeTurn:
        def inner_text(self, timeout=None):
            return "Something went wrong. Please try again."

    class FakeLocator:
        def all(self):
            return [FakeTurn()]

    class FakePage:
        def locator(self, sel):
            return FakeLocator()

    p = ChatGPTProvider()
    with pytest.raises(ProviderError, match="error instead of a reply"):
        p._last_assistant_text(FakePage())


def test_balance_prefers_remaining_over_max():
    from src.agent.balance import _search_credit_keys
    # A plan-limit key must not be read as the balance.
    data = {"max_credits": 500, "credits_remaining": 37}
    assert _search_credit_keys(data) == 37
    # Weak key still works when nothing better exists.
    assert _search_credit_keys({"credits": 12}) == 12


def test_upsert_provider_preserves_user_edits():
    from src.backend import free_providers as ledger
    ledger.upsert_provider("unit_x", "Unit X", "unit.example.com",
                           kinds=["text"], priority=5, balance_recipe={})
    ledger.update_provider("unit_x", enabled=False, balance_recipe={"a": 1})
    ledger.upsert_provider("unit_x", "Unit X", "unit.example.com",
                           kinds=["text"], priority=5, balance_recipe={})
    p = ledger.get_provider("unit_x")
    assert not p["enabled"]
    assert p["balance_recipe"] == {"a": 1}


def test_complete_job_stores_strategy():
    from src.agent import queue as jobqueue
    job_id = jobqueue.enqueue_job("unit_x", "text", "hello")
    jobqueue.complete_job(job_id, result_text="ok", strategy="rotated-dom")
    job = jobqueue.get_job(job_id)
    assert job["status"] == "done"
    assert job["strategy"] == "rotated-dom"


def test_wait_for_extends_for_live_running_job():
    """Client must extend the wait (not fail over) when the agent is still
    actively working the job — avoids double-generating."""
    from src.backend import free_agent_client as client
    from src.agent import queue as jobqueue

    real_get, real_alive = jobqueue.get_job, client.agent_alive
    jobqueue.get_job = lambda jid: {"id": jid, "status": "running"}
    client.agent_alive = lambda: True
    try:
        t0 = __import__("time").time()
        with pytest.raises(client.FreeAgentError, match="timed out"):
            client.wait_for("fake", timeout=2, poll=0.05)
        elapsed = __import__("time").time() - t0
        # timeout (2s) + one extension (1s) -> must have waited ~3s, not 2s.
        assert elapsed >= 2.8, f"wait was not extended: {elapsed:.2f}s"
    finally:
        jobqueue.get_job, client.agent_alive = real_get, real_alive
