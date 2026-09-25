"""
free_agent_client.py — used by the orchestrator and Flask API to run
generations through the invisible background agent.

generate_via_agent() enqueues a job and blocks (with timeout) until the
agent finishes it. Returns the result file path (image/video) or text.
Raises FreeAgentError when no provider is available or the job fails.
"""
from __future__ import annotations

import json
import os
import time

from src.agent import queue as jobqueue
from src.backend import free_providers as ledger


class FreeAgentError(Exception):
    pass


def _heartbeat_path() -> str:
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "data", "agent_heartbeat.json")


def agent_alive(max_age: int = 90) -> bool:
    """True if the background agent wrote a recent heartbeat."""
    try:
        with open(_heartbeat_path()) as f:
            ts = json.load(f).get("ts", 0)
        return (time.time() - ts) < max_age
    except Exception:
        return False


def agent_available(kind: str | None = None) -> bool:
    """True if at least one enabled, non-exhausted provider exists."""
    providers = ledger.list_providers(include_disabled=False)
    if kind:
        providers = [p for p in providers
                     if kind in p["kinds"] and p["status"] == "active"]
    else:
        providers = [p for p in providers if p["status"] == "active"]
    return bool(providers)


def enqueue(kind: str, prompt: str = "", input_path: str | None = None,
            provider_id: str | None = None) -> tuple[str, dict]:
    """Enqueue a job. Returns (job_id, provider)."""
    if not agent_alive():
        raise FreeAgentError(
            "Background agent is not running. Start it on your PC with "
            "start_agent.bat (it runs invisibly in the background), then retry.")
    provider = ledger.pick_provider(kind, prefer_id=provider_id)
    if provider is None:
        raise FreeAgentError(
            f"No active free-web provider for kind={kind!r}. "
            f"Enable one in the Free AI tab.")
    job_id = jobqueue.enqueue_job(provider["id"], kind, prompt, input_path)
    return job_id, provider


def _enqueue_with(provider: dict, kind: str, prompt: str = "",
                  input_path: str | None = None) -> str:
    """Enqueue a job against one specific provider dict (no re-picking)."""
    return jobqueue.enqueue_job(provider["id"], kind, prompt, input_path)


def wait_for(job_id: str, timeout: int = 1500, poll: int = 5) -> dict:
    """Block until the job finishes. Returns the job dict."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = jobqueue.get_job(job_id)
        if not job:
            raise FreeAgentError(f"job {job_id} vanished from the queue")
        if job["status"] == "done":
            return job
        if job["status"] == "failed":
            raise FreeAgentError(f"agent job failed: {job.get('error') or 'unknown'}")
        time.sleep(poll)
    raise FreeAgentError(f"agent job {job_id} timed out after {timeout}s")


def generate_via_agent(kind: str, prompt: str = "", input_path: str | None = None,
                       provider_id: str | None = None,
                       timeout: int = 1500) -> dict:
    """
    Full round-trip: enqueue -> wait -> return
    {"result_path": ...} and/or {"result_text": ...}.

    Acts like an AI with a plan B: tries providers in priority order
    (option A, then B, then C...). If one fails — logged out, quota hit,
    site changed — the job automatically moves to the next option instead
    of dying. A pinned provider_id keeps the old fail-loud behaviour.

    When every known option fails, the agent scouts the web for new free
    alternatives, tries to provision one automatically, and retries once.
    """
    if not agent_alive():
        raise FreeAgentError(
            "Background agent is not running. Start it on your PC with "
            "start_agent.bat (it runs invisibly in the background), then retry.")

    tried: list[str] = []
    errors: list[str] = []

    def chain() -> list[dict]:
        if provider_id:
            p = ledger.get_provider(provider_id)
            return [p] if p else []
        return ledger.ranked_providers(kind)

    candidates = chain()
    if provider_id and not candidates:
        raise FreeAgentError(
            f"Pinned provider {provider_id!r} is not usable "
            f"(disabled/exhausted/unknown). Fix it in the Free AI tab.")

    job_id = ""
    provider = None
    prev_failed = None
    for cand in candidates:
        tried.append(cand["id"])
        try:
            if prev_failed:
                print(f"[free-agent] option {prev_failed!r} failed — "
                      f"falling back to next option: {cand['id']!r}")
            job_id = _enqueue_with(cand, kind, prompt, input_path)
            job = wait_for(job_id, timeout=timeout)
            provider = cand
            break
        except FreeAgentError as e:
            errors.append(f"{cand['id']}: {e}")
            print(f"[free-agent] option {cand['id']!r} failed: {e}")
            prev_failed = cand["id"]
            continue
    else:
        # Every known option failed — scout the web for a new free
        # alternative, auto-provision it, and retry once.
        print(f"[free-agent] all {len(candidates)} known option(s) failed; "
              f"scouting the web for new free alternatives...")
        try:
            from src.backend import free_provision
            new_providers = free_provision.ensure_capacity(
                kind, exclude_ids=set(tried))
        except Exception as e:
            new_providers = []
            errors.append(f"provision: {e}")
            print(f"[free-agent] auto-provisioning failed: {e}")
        for cand in new_providers:
            tried.append(cand["id"])
            try:
                job_id = _enqueue_with(cand, kind, prompt, input_path)
                job = wait_for(job_id, timeout=timeout)
                provider = cand
                break
            except FreeAgentError as e:
                errors.append(f"{cand['id']}: {e}")
                continue
        else:
            raise FreeAgentError(
                f"All free-web options failed for kind={kind!r} "
                f"(tried: {', '.join(tried) or 'none'}). "
                f"Details: {' | '.join(errors[:3])}. "
                f"Check the Free AI tab — new candidates may need approval.")

    return {
        "job_id": job_id,
        "provider_id": provider["id"],
        "result_path": job.get("result_path"),
        "result_text": job.get("result_text"),
        "tried_providers": tried,
    }


def generate_image_file(prompt: str, provider_id: str | None = None,
                        timeout: int = 900) -> str:
    """Convenience: returns the image file path or raises."""
    r = generate_via_agent("image", prompt, provider_id=provider_id, timeout=timeout)
    path = r.get("result_path")
    if not path or not os.path.exists(path):
        raise FreeAgentError("agent returned no image file")
    return path


def generate_video_file(prompt: str, input_path: str | None = None,
                        provider_id: str | None = None,
                        timeout: int = 1800) -> str:
    """Convenience: returns the video file path or raises."""
    r = generate_via_agent("video", prompt, input_path=input_path,
                           provider_id=provider_id, timeout=timeout)
    path = r.get("result_path")
    if not path or not os.path.exists(path):
        raise FreeAgentError("agent returned no video file")
    return path


def generate_text(prompt: str, provider_id: str | None = None,
                  timeout: int = 600) -> str:
    """Convenience: returns generated text or raises."""
    r = generate_via_agent("text", prompt, provider_id=provider_id, timeout=timeout)
    text = (r.get("result_text") or "").strip()
    if not text:
        raise FreeAgentError("agent returned no text")
    return text
