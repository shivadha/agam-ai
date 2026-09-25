"""
free_providers.py — Credit ledger for free-web background agent providers.

Tracks every free-tier website the background agent can drive (Gemini,
Veo, ChatGPT Go, scout-discovered sites...). Balances are updated two ways:

  1. Live scrape (preferred): after each job the agent reads the remaining
     credits from the site (API-response sniffing, then DOM selector, then
     regex over page text) and reports it back asynchronously.
  2. Usage counting (fallback): when no live balance is available we
     decrement our own counter per completed job.

A provider whose balance reaches 0 is auto-retired (status='exhausted').
Admin can re-enable / edit / delete providers from the Free AI tab.
"""
from __future__ import annotations

import json
import time
import uuid

from src.database import get_db, _db_lock


# ── helpers ────────────────────────────────────────────────────────────────
def _row_to_provider(row) -> dict:
    p = dict(row)
    for k in ("kinds", "balance_recipe"):
        try:
            p[k] = json.loads(p[k] or ("[]" if k == "kinds" else "{}"))
        except Exception:
            p[k] = [] if k == "kinds" else {}
    return p


# ── providers ──────────────────────────────────────────────────────────────
def list_providers(include_disabled: bool = True) -> list:
    with _db_lock:
        conn = get_db()
        try:
            q = "SELECT * FROM free_providers"
            if not include_disabled:
                q += " WHERE enabled = 1"
            q += " ORDER BY priority ASC, name ASC"
            return [_row_to_provider(r) for r in conn.execute(q).fetchall()]
        finally:
            conn.close()


def get_provider(provider_id: str) -> dict | None:
    with _db_lock:
        conn = get_db()
        try:
            r = conn.execute("SELECT * FROM free_providers WHERE id = ?",
                             (provider_id,)).fetchone()
            return _row_to_provider(r) if r else None
        finally:
            conn.close()


def upsert_provider(provider_id: str, name: str, url: str,
                    kinds: list | None = None, quota_total: int | None = None,
                    balance: int | None = None,
                    balance_recipe: dict | None = None,
                    priority: int = 10, notes: str = "",
                    enabled: bool = True) -> dict:
    kinds = kinds or ["image"]
    with _db_lock:
        conn = get_db()
        try:
            conn.execute("""
                INSERT INTO free_providers
                    (id, name, url, kinds, quota_total, balance, balance_recipe,
                     priority, notes, enabled, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name, url=excluded.url, kinds=excluded.kinds,
                    quota_total=COALESCE(excluded.quota_total, free_providers.quota_total),
                    balance=COALESCE(excluded.balance, free_providers.balance),
                    balance_recipe=excluded.balance_recipe,
                    priority=excluded.priority, notes=excluded.notes,
                    enabled=excluded.enabled, updated_at=CURRENT_TIMESTAMP
            """, (provider_id, name, url, json.dumps(kinds), quota_total, balance,
                  json.dumps(balance_recipe or {}), priority, notes, int(enabled)))
            conn.commit()
        finally:
            conn.close()
    return get_provider(provider_id)


def update_provider(provider_id: str, **fields) -> dict | None:
    allowed = {"name", "url", "kinds", "quota_total", "balance", "balance_recipe",
               "status", "enabled", "priority", "notes"}
    sets, params = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k in ("kinds", "balance_recipe"):
            v = json.dumps(v)
        if k == "enabled":
            v = int(bool(v))
        sets.append(f"{k} = ?")
        params.append(v)
    if not sets:
        return get_provider(provider_id)
    sets.append("updated_at = CURRENT_TIMESTAMP")
    with _db_lock:
        conn = get_db()
        try:
            conn.execute(f"UPDATE free_providers SET {', '.join(sets)} WHERE id = ?",
                         params + [provider_id])
            conn.commit()
        finally:
            conn.close()
    return get_provider(provider_id)


def delete_provider(provider_id: str) -> bool:
    with _db_lock:
        conn = get_db()
        try:
            cur = conn.execute("DELETE FROM free_providers WHERE id = ?",
                               (provider_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def pick_provider(kind: str, prefer_id: str | None = None) -> dict | None:
    """Pick the best enabled provider for a kind with balance remaining."""
    providers = [p for p in list_providers(include_disabled=False)
                 if kind in p["kinds"] and p["status"] == "active"]
    if prefer_id:
        # Explicit pin: return it only if usable, else None (fail loud —
        # never silently swap a provider the user pinned).
        for p in providers:
            if p["id"] == prefer_id:
                return p
        return None
    # Prefer providers with a known positive balance, then unknown, by priority.
    def rank(p):
        bal = p["balance"]
        has = 0 if (bal is None or bal > 0) else 1
        return (has, p["priority"])
    providers.sort(key=rank)
    return providers[0] if providers else None


def record_usage(provider_id: str, live_balance: int | None = None) -> dict | None:
    """
    Called (asynchronously) after each completed job.
    live_balance: scraped remaining credits, if the agent could read them.
    Falls back to decrementing our own counter otherwise.
    Auto-retires the provider at zero.
    """
    with _db_lock:
        conn = get_db()
        try:
            r = conn.execute("SELECT * FROM free_providers WHERE id = ?",
                             (provider_id,)).fetchone()
            if not r:
                return None
            p = _row_to_provider(r)
            if live_balance is not None:
                new_balance = max(0, int(live_balance))
            elif p["balance"] is not None:
                new_balance = max(0, p["balance"] - 1)
            else:
                new_balance = None
            status = p["status"]
            if new_balance == 0:
                status = "exhausted"
            conn.execute("""
                UPDATE free_providers
                SET used_count = used_count + 1,
                    balance = ?, status = ?,
                    last_checked = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (new_balance, status, provider_id))
            conn.commit()
        finally:
            conn.close()
    return get_provider(provider_id)


# ── candidates (scout) ─────────────────────────────────────────────────────
def add_candidate(name: str, url: str, kinds: list | None = None,
                  quota_hint: str = "", source: str = "",
                  source_url: str = "") -> int | None:
    with _db_lock:
        conn = get_db()
        try:
            cur = conn.execute("""
                INSERT OR IGNORE INTO free_candidates
                    (name, url, kinds, quota_hint, source, source_url)
                VALUES (?,?,?,?,?,?)
            """, (name, url, json.dumps(kinds or ["image"]),
                  quota_hint, source, source_url))
            conn.commit()
            return cur.lastrowid or None
        finally:
            conn.close()


def list_candidates(status: str = "pending") -> list:
    with _db_lock:
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT * FROM free_candidates WHERE status = ? ORDER BY created_at DESC",
                (status,)).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                try:
                    d["kinds"] = json.loads(d["kinds"] or "[]")
                except Exception:
                    d["kinds"] = []
                out.append(d)
            return out
        finally:
            conn.close()


def approve_candidate(candidate_id: int, provider_id: str | None = None,
                      balance_recipe: dict | None = None) -> dict | None:
    """Promote a candidate to a real provider (admin one-click approve)."""
    with _db_lock:
        conn = get_db()
        try:
            r = conn.execute("SELECT * FROM free_candidates WHERE id = ?",
                             (candidate_id,)).fetchone()
            if not r:
                return None
            c = dict(r)
            conn.execute("UPDATE free_candidates SET status = 'approved' WHERE id = ?",
                         (candidate_id,))
            conn.commit()
        finally:
            conn.close()
    kinds = json.loads(c["kinds"] or "[]") or ["image"]
    pid = provider_id or ("web_" + "".join(ch for ch in c["url"].split("//")[-1].split("/")[0]
                                           if ch.isalnum())[:24].lower())
    return upsert_provider(pid, c["name"], c["url"], kinds=kinds,
                           notes=f"Approved from scout candidate #{candidate_id} "
                                 f"({c['source']}). {c['quota_hint'] or ''}".strip(),
                           balance_recipe=balance_recipe or {})


def reject_candidate(candidate_id: int) -> bool:
    with _db_lock:
        conn = get_db()
        try:
            cur = conn.execute("UPDATE free_candidates SET status = 'rejected' WHERE id = ?",
                               (candidate_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def seed_builtin_providers():
    """Seed the providers the user asked for: ChatGPT Go, Gemini, Veo."""
    upsert_provider(
        "chatgpt_go", "ChatGPT Go (web)", "https://chatgpt.com/",
        kinds=["text", "image"], priority=1,
        notes="User's ChatGPT Go plan: hooks, scripts, descriptions, thumbnails, images.",
        balance_recipe={"api_patterns": ["backend-api"], "regex": r"(\d+)\s*(?:credits?|remaining)",
                        "note": "ChatGPT web rarely exposes a numeric balance; usage counting applies."},
    )
    upsert_provider(
        "gemini_web", "Gemini Web (AI Pro)", "https://gemini.google.com/",
        kinds=["image", "video"], priority=2,
        notes="User's Google AI plan: free image generation + image-to-video (Veo model) via website. "
              "Video runs rotate through recorded strategies (video chip / tools menu / model picker / chat intent), "
              "a different path every run.",
        balance_recipe={"api_patterns": ["batchexecute"], "dom_selector": "",
                        "regex": r"(\d+)\s*(?:images?|generations?|videos?)\s*(?:left|remaining|per day)"},
    )
    upsert_provider(
        "veo_web", "Veo Web (free tier)", "https://labs.google/fx/",
        kinds=["video"], priority=3,
        notes="Free Veo tier via Google Flow: image-to-video, few videos/day. "
              "Each run rotates through recorded strategies (frames-direct / new-project-first / "
              "prompt-first / keyboard-driven), a different path every run.",
        balance_recipe={"api_patterns": ["flow", "credits"], "dom_selector": "",
                        "regex": r"(\d+)\s*(?:credits?|videos?)\s*(?:left|remaining)"},
    )
