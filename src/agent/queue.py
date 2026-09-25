"""
queue.py — SQLite-backed job queue shared by the Flask app and the
background agent. The web app / orchestrator enqueues generation jobs;
the agent (running headless on the user's PC) picks them up, drives the
provider websites, and writes results back.
"""
from __future__ import annotations

import uuid

from src.database import get_db, _db_lock


def enqueue_job(provider_id: str, kind: str, prompt: str = "",
                input_path: str | None = None) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _db_lock:
        conn = get_db()
        try:
            conn.execute("""
                INSERT INTO agent_jobs (id, provider_id, kind, prompt, input_path, status)
                VALUES (?,?,?,?,?,'queued')
            """, (job_id, provider_id, kind, prompt, input_path))
            conn.commit()
        finally:
            conn.close()
    return job_id


def claim_next_job() -> dict | None:
    """Atomically claim the oldest queued job (agent side)."""
    with _db_lock:
        conn = get_db()
        try:
            row = conn.execute("""
                SELECT * FROM agent_jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC LIMIT 1
            """).fetchone()
            if not row:
                return None
            conn.execute("""
                UPDATE agent_jobs
                SET status = 'running', started_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'queued'
            """, (row["id"],))
            if conn.total_changes == 0:
                return None
            conn.commit()
            return dict(conn.execute("SELECT * FROM agent_jobs WHERE id = ?",
                                     (row["id"],)).fetchone())
        finally:
            conn.close()


def complete_job(job_id: str, result_path: str | None = None,
                 result_text: str | None = None,
                 balance_after: int | None = None):
    with _db_lock:
        conn = get_db()
        try:
            conn.execute("""
                UPDATE agent_jobs
                SET status = 'done', result_path = ?, result_text = ?,
                    balance_after = ?, finished_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (result_path, result_text, balance_after, job_id))
            conn.commit()
        finally:
            conn.close()


def fail_job(job_id: str, error: str):
    with _db_lock:
        conn = get_db()
        try:
            conn.execute("""
                UPDATE agent_jobs
                SET status = 'failed', error = ?, finished_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (error[:2000], job_id))
            conn.commit()
        finally:
            conn.close()


def get_job(job_id: str) -> dict | None:
    with _db_lock:
        conn = get_db()
        try:
            row = conn.execute("SELECT * FROM agent_jobs WHERE id = ?",
                               (job_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def list_jobs(status: str | None = None, limit: int = 50) -> list:
    with _db_lock:
        conn = get_db()
        try:
            if status:
                rows = conn.execute(
                    "SELECT * FROM agent_jobs WHERE status = ? "
                    "ORDER BY created_at DESC LIMIT ?", (status, limit)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM agent_jobs ORDER BY created_at DESC LIMIT ?",
                    (limit,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def queue_stats() -> dict:
    with _db_lock:
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT status, COUNT(*) c FROM agent_jobs GROUP BY status").fetchall()
            return {r["status"]: r["c"] for r in rows}
        finally:
            conn.close()
