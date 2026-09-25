"""
free_provision.py — automatic failover to brand-new free providers.

When every known free-web option fails (the A -> B -> C fallback chain in
free_agent_client is exhausted), this module:

  1. runs the scout (Reddit + DuckDuckGo) for fresh free AI sites,
  2. enqueues a `provision` job per promising pending candidate,
  3. the background agent tries to auto-create an account on each site
     (best effort) and probes its image / image-to-video UI,
  4. sites that come online are promoted into the provider ledger
     automatically; sites that need a human (captcha, email verification)
     are flagged in the Free AI tab instead of failing silently.

Account creation needs an email address — set once via
set_signup_email() / the Free AI tab. Stored in
data/agent_config.json (local only, never committed).
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse

from src.agent import queue as jobqueue
from src.agent import scout as scout_mod
from src.backend import free_providers as ledger

PROVISION_TIMEOUT = 900  # seconds to wait per candidate provisioning attempt
MAX_CANDIDATES_PER_RUN = 2


def _repo_root() -> str:
    # src/backend/free_provision.py -> repo root
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


def _config_path() -> str:
    return os.path.join(_repo_root(), "data", "agent_config.json")


def get_config() -> dict:
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def set_signup_email(email: str) -> dict:
    """Store the email the agent uses for automatic free-tier signups."""
    email = (email or "").strip()
    if "@" not in email:
        raise ValueError("That doesn't look like an email address.")
    cfg = get_config()
    cfg["signup_email"] = email
    os.makedirs(os.path.dirname(_config_path()), exist_ok=True)
    with open(_config_path(), "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return cfg


def get_signup_email() -> str | None:
    return get_config().get("signup_email") or None


def _domain(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.lower().split(":")[0]
    except Exception:
        return ""


def _wait_job(job_id: str, timeout: int) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = jobqueue.get_job(job_id)
        if not job:
            raise RuntimeError(f"provision job {job_id} vanished")
        if job["status"] == "done":
            return job
        if job["status"] == "failed":
            raise RuntimeError(f"provision job failed: {job.get('error')}")
        time.sleep(5)
    raise RuntimeError(f"provision job {job_id} timed out after {timeout}s")


def _provider_id_for(url: str) -> str:
    dom = _domain(url).replace(".", "_")
    clean = "".join(ch if ch.isalnum() or ch == "_" else "" for ch in dom)
    return ("auto_" + clean[:28].strip("_")) or "auto_site"


def apply_provision_result(candidate_id: int, result: dict) -> dict | None:
    """Turn an agent provision result into ledger changes.

    Returns the new provider dict when the site came online, else None.
    """
    status = (result or {}).get("status") or "failed"
    url = (result or {}).get("url") or ""
    name = (result or {}).get("name") or _domain(url)
    kinds = (result or {}).get("kinds") or ["image"]
    reason = (result or {}).get("reason") or ""

    if status == "active":
        pid = _provider_id_for(url)
        provider = ledger.approve_candidate(
            candidate_id,
            provider_id=pid,
            balance_recipe={"auto_provisioned": True,
                            "probe": (result or {}).get("probe") or {},
                            "account_ref": (result or {}).get("account_ref") or ""},
        )
        if provider:
            ledger.update_provider(
                pid,
                notes=(f"Auto-provisioned by background agent. "
                       f"{reason}".strip()),
            )
            print(f"[provision] {name} is ONLINE as provider {pid!r}")
        return provider

    # Needs a human (or failed): mark the candidate so the Free AI tab
    # shows what happened instead of retrying forever.
    mark = {"pending_verification": "needs_verification",
            "needs_manual": "needs_manual"}.get(status, "provision_failed")
    try:
        ledger.set_candidate_status(candidate_id, mark)
    except Exception as e:
        print(f"[provision] could not mark candidate: {e}")
    print(f"[provision] {name}: {status} — {reason}")
    return None


def ensure_capacity(kind: str, exclude_ids: frozenset = frozenset(),
                    max_candidates: int = MAX_CANDIDATES_PER_RUN,
                    timeout: int = PROVISION_TIMEOUT) -> list:
    """Scout for new free options, auto-provision, return new providers.

    Called only after every known provider failed. Returns a (possibly
    empty) list of freshly provisioned provider dicts ready to use.
    """
    email = get_signup_email()
    if not email:
        print("[provision] no signup email configured — skipping auto-"
              "provisioning. Set one in the Free AI tab to let the agent "
              "create accounts on new free sites by itself.")
        return []

    print(f"[provision] scouting the web for new free {kind} options...")
    try:
        scout_result = scout_mod.run_scout()
        print(f"[provision] scout: {scout_result.get('scanned')} hits, "
              f"{scout_result.get('added')} new candidates")
    except Exception as e:
        print(f"[provision] scout failed: {e}")
        return []

    existing_domains = {_domain(p["url"]) for p in ledger.list_providers()
                        if p.get("url")}
    tried_domains: set[str] = set()
    new_providers: list = []

    for c in ledger.list_candidates("pending"):
        if len(new_providers) >= max_candidates:
            break
        kinds = c.get("kinds") or []
        if kind not in kinds:
            continue
        dom = _domain(c.get("url") or "")
        if not dom or dom in existing_domains or dom in tried_domains:
            continue
        tried_domains.add(dom)

        payload = {
            "candidate_id": c["id"],
            "name": c.get("name") or dom,
            "url": c.get("url"),
            "kinds": kinds,
            "email": email,
        }
        print(f"[provision] trying auto-signup on {c.get('url')} ...")
        try:
            job_id = jobqueue.enqueue_job(
                "autoprovision", "provision", json.dumps(payload))
            job = _wait_job(job_id, timeout)
            result = json.loads(job.get("result_text") or "{}")
        except Exception as e:
            print(f"[provision] {dom}: agent error: {e}")
            try:
                ledger.set_candidate_status(c["id"], "provision_failed")
            except Exception:
                pass
            continue
        provider = apply_provision_result(c["id"], result)
        if provider:
            new_providers.append(provider)

    return new_providers
