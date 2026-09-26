"""
memory.py — long-term memory for the free-web background agent.

The agent used to start every run from zero. Now it remembers:

  facts       stable truths, e.g. "site X: generate button labelled 'Create'",
              "chatgpt_go: chat input selector = textarea#prompt"
  lessons     learned from failures, e.g. "veo_web: logged out twice this
              week — re-login likely needed", "gemini_web: 'video_chip'
              strategy fails when quota banner visible"
  preferences what worked best, e.g. "strategy 'tools_menu' has the best
              hit-rate on gemini_web for video"

Loop: before each job the agent recalls relevant memories (injected into
the job as job["agent_memories"]); after each job it learns — failures
become lessons (deduplicated, confidence grows with repeats), successes
refresh "last known good" facts. Providers can read job["agent_memories"]
to adapt (e.g. try a remembered selector first).

Nothing here is magic: it's a small SQLite table with confidence
scoring, so the agent accumulates experience instead of repeating the
same mistakes every run.
"""
from __future__ import annotations

import re
import time

from src.database import get_db, _db_lock

MAX_CONTENT = 500


def _norm(content: str) -> str:
    return re.sub(r"\s+", " ", (content or "").strip().lower())[:MAX_CONTENT]


def remember(scope: str, kind: str, content: str,
             confidence: float = 0.5) -> dict | None:
    """Store a memory. Same scope+kind+content reinforces instead of
    duplicating (confidence grows, occurrences count up)."""
    content = (content or "").strip()[:MAX_CONTENT]
    norm = _norm(content)
    if not norm or kind not in ("fact", "lesson", "preference"):
        return None
    scope = (scope or "global").strip() or "global"
    confidence = max(0.05, min(1.0, float(confidence)))
    with _db_lock:
        conn = get_db()
        try:
            conn.execute("""
                INSERT INTO agent_memory (scope, kind, content, norm, confidence)
                VALUES (?,?,?,?,?)
                ON CONFLICT(scope, kind, norm) DO UPDATE SET
                    confidence = MIN(1.0, agent_memory.confidence + 0.1),
                    occurrences = agent_memory.occurrences + 1,
                    updated_at = CURRENT_TIMESTAMP
            """, (scope, kind, content, norm, confidence))
            conn.commit()
            r = conn.execute(
                "SELECT * FROM agent_memory WHERE scope=? AND kind=? AND norm=?",
                (scope, kind, norm)).fetchone()
            return dict(r) if r else None
        finally:
            conn.close()


def recall(scope: str, kind_filter: str | None = None,
           limit: int = 10) -> list[dict]:
    """Relevant memories for a job: provider-scoped first, then global.
    Ordered by confidence, fresher first."""
    scope = (scope or "global").strip() or "global"
    with _db_lock:
        conn = get_db()
        try:
            q = ("SELECT * FROM agent_memory WHERE scope IN (?, 'global')"
                 + (" AND kind = ?" if kind_filter else "")
                 + " ORDER BY (scope = ?) DESC, confidence DESC, updated_at DESC"
                 + " LIMIT ?")
            args = [scope]
            if kind_filter:
                args.append(kind_filter)
            args += [scope, limit]
            return [dict(r) for r in conn.execute(q, args).fetchall()]
        finally:
            conn.close()


def recall_texts(scope: str, limit: int = 8) -> list[str]:
    """Compact strings, ready to inject into a job or prompt."""
    out = []
    for m in recall(scope, limit=limit):
        tag = {"fact": "[known]", "lesson": "[lesson]",
               "preference": "[pref]"}[m["kind"]]
        out.append(f"{tag} ({m['scope']}) {m['content']}")
    return out


def reinforce(memory_id: int, success: bool) -> None:
    """Adjust confidence after a memory was used."""
    with _db_lock:
        conn = get_db()
        try:
            if success:
                conn.execute(
                    "UPDATE agent_memory SET successes = successes + 1,"
                    " confidence = MIN(1.0, confidence + 0.05),"
                    " updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (memory_id,))
            else:
                conn.execute(
                    "UPDATE agent_memory SET confidence = MAX(0.05, confidence - 0.15),"
                    " updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (memory_id,))
            conn.commit()
        finally:
            conn.close()


def forget(memory_id: int) -> bool:
    with _db_lock:
        conn = get_db()
        try:
            cur = conn.execute("DELETE FROM agent_memory WHERE id = ?",
                               (memory_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def prune(days: int = 60, min_confidence: float = 0.2) -> int:
    """Drop stale, low-confidence memories (keeps the store useful)."""
    with _db_lock:
        conn = get_db()
        try:
            cur = conn.execute(
                """DELETE FROM agent_memory
                   WHERE confidence < ? AND kind = 'lesson'
                     AND updated_at < DATETIME('now', ?)""",
                (min_confidence, f"-{int(days)} days"))
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()


def _error_signature(error: str) -> str:
    """Collapse an error into a stable lesson key."""
    e = _norm(error)
    if "login" in e or "logged out" in e or "sign in" in e:
        return "login required — session expired or logged out"
    if "quota" in e or "credit" in e or "limit" in e or "exhausted" in e:
        return "quota/credits exhausted on the site"
    if "captcha" in e or "robot" in e or "challenge" in e:
        return "blocked by captcha/bot challenge"
    if "timeout" in e or "timed out" in e:
        return "site timed out (slow or overloaded)"
    if "selector" in e or "not found" in e or "element" in e:
        return "page layout changed — selectors need updating"
    return (error or "unknown failure").strip()[:120]


def learn_from_job(job: dict, ok: bool, detail: str = "") -> None:
    """Update memory after a job finishes. Called by the agent loop."""
    provider_id = job.get("provider_id") or "global"
    kind = job.get("kind") or ""
    strategy = (job.get("strategy") or detail or "").strip()

    if ok:
        # Refresh the "last known good" fact (single row, not a log).
        remember(provider_id, "fact",
                 f"last successful {kind} job"
                 + (f" via strategy '{strategy}'" if strategy else ""),
                 confidence=0.7)
        if strategy:
            remember(provider_id, "preference",
                     f"strategy '{strategy}' works for {kind}",
                     confidence=0.6)
    else:
        sig = _error_signature(detail)
        mem = remember(provider_id, "lesson",
                       f"{kind} failing: {sig}", confidence=0.6)
        # Repeated identical failures are a strong signal.
        if mem and mem["occurrences"] >= 3 and "login required" in sig:
            remember("global", "lesson",
                     f"{provider_id} keeps logging out — check the login "
                     f"session in --show-login", confidence=0.8)


def stats() -> dict:
    with _db_lock:
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT kind, COUNT(*) c FROM agent_memory GROUP BY kind"
            ).fetchall()
            return {r["kind"]: r["c"] for r in rows}
        finally:
            conn.close()
