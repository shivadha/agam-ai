"""
provision.py — agent-side auto-provisioning of newly scouted free sites.

Runs inside the background agent (it owns the persistent browser). Given
a `provision` job whose prompt is a JSON candidate
{candidate_id, name, url, kinds, email}, it:

  1. opens the site and checks whether an account is needed,
  2. best-effort auto-signup with the configured email + generated password,
  3. probes the page for a usable image / image-to-video UI (upload input,
     prompt field, generate button) WITHOUT submitting anything,
  4. stores the new account locally and reports back:
     {status, url, name, kinds, probe, account_ref, reason}

Statuses: active | pending_verification | needs_manual | failed

Honest limits: sites behind CAPTCHA / phone / invite-only verification
come back as needs_manual (or pending_verification for email checks) so
the user can finish them by hand in the Free AI tab instead of the agent
pretending it succeeded.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import time

SIGNUP_LINK_RE = re.compile(
    r"sign\s*up|get\s*started|join\s*free|try\s*free|create.*account|start.*free",
    re.I)
SIGNIN_RE = re.compile(r"log\s*in|sign\s*in", re.I)
LOGGED_IN_HINTS = (
    "a[href*='dashboard']", "a[href*='/app']", "[data-testid='avatar']",
    "button[aria-label*='account' i]", "img[alt*='avatar' i]",
)
VERIFY_RE = re.compile(r"verif.*email|check.*inbox|confirm.*email|sent.*link", re.I)
CAPTCHA_RE = re.compile(r"captcha|are you a robot|verify you are human|challenge", re.I)
GENERATE_RE = re.compile(r"generate|create|make|render|produce", re.I)


def _repo_root() -> str:
    # src/agent/provision.py -> repo root
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


def _config_path() -> str:
    return os.path.join(_repo_root(), "data", "agent_config.json")


def _accounts_path() -> str:
    return os.path.join(_repo_root(), "data", "agent_accounts.json")


def _load_accounts() -> list:
    try:
        with open(_accounts_path(), "r", encoding="utf-8") as f:
            return json.load(f) or []
    except Exception:
        return []


def _save_account(url: str, email: str, password: str) -> str:
    """Store an auto-created account locally. Returns an opaque ref."""
    ref = "acct_" + secrets.token_hex(6)
    accounts = _load_accounts()
    accounts.append({
        "ref": ref, "url": url, "email": email, "password": password,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    os.makedirs(os.path.dirname(_accounts_path()), exist_ok=True)
    with open(_accounts_path(), "w", encoding="utf-8") as f:
        json.dump(accounts, f, indent=2)
    try:
        os.chmod(_accounts_path(), 0o600)
    except Exception:
        pass
    return ref


def _page_text(page) -> str:
    try:
        return page.evaluate("() => document.body ? document.body.innerText.slice(0, 4000) : ''")
    except Exception:
        return ""


def _looks_logged_in(page) -> bool:
    for sel in LOGGED_IN_HINTS:
        try:
            if page.locator(sel).first.is_visible(timeout=500):
                return True
        except Exception:
            continue
    return False


def _try_signup(page, url: str, email: str) -> dict:
    """Best-effort account creation. Returns {ok, state, reason}."""
    password = "Ag" + secrets.token_urlsafe(14) + "9!"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception as e:
        return {"ok": False, "state": "failed",
                "reason": f"could not load site: {e}", "password": None}

    if _looks_logged_in(page):
        return {"ok": True, "state": "no_signup_needed",
                "reason": "site usable without an account", "password": None}

    text = _page_text(page)
    if CAPTCHA_RE.search(text or ""):
        return {"ok": False, "state": "needs_manual",
                "reason": "site shows a captcha/challenge", "password": None}

    # Find and click the signup entry point.
    clicked = False
    for role in ("link", "button"):
        try:
            loc = page.get_by_role(role, name=SIGNUP_LINK_RE)
            if loc.count() > 0:
                loc.first.click(timeout=8000)
                clicked = True
                break
        except Exception:
            continue
    if not clicked:
        # Maybe the landing page IS the signup/app page.
        pass
    page.wait_for_timeout(2500)

    # Fill the signup form.
    try:
        email_inputs = page.locator(
            "input[type='email'], input[name*='email' i], input[id*='email' i]")
        if email_inputs.count() == 0:
            # No email field — maybe SSO-only or already inside the app.
            if _looks_logged_in(page):
                return {"ok": True, "state": "no_signup_needed",
                        "reason": "already inside the app", "password": None}
            return {"ok": False, "state": "needs_manual",
                    "reason": "no email signup form found (SSO-only?)",
                    "password": None}
        email_inputs.first.fill(email, timeout=8000)

        pw_inputs = page.locator(
            "input[type='password']")
        if pw_inputs.count() > 0:
            pw_inputs.first.fill(password, timeout=8000)

        # Optional name fields — fill harmlessly if present.
        for sel in ("input[name*='name' i]:not([name*='user' i])",
                    "input[autocomplete='name']"):
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and not loc.first.input_value(timeout=1000):
                    loc.first.fill("Agam User", timeout=3000)
            except Exception:
                pass

        # Submit: prefer a submit button, else press Enter in the form.
        submitted = False
        for name_re in (re.compile(r"sign\s*up|create.*account|get\s*started|continue|agree", re.I),):
            try:
                btn = page.get_by_role("button", name=name_re)
                if btn.count() > 0:
                    btn.first.click(timeout=8000)
                    submitted = True
                    break
            except Exception:
                continue
        if not submitted:
            try:
                email_inputs.first.press("Enter", timeout=5000)
                submitted = True
            except Exception:
                pass
        if not submitted:
            return {"ok": False, "state": "needs_manual",
                    "reason": "could not submit the signup form",
                    "password": None}
    except Exception as e:
        return {"ok": False, "state": "failed",
                "reason": f"form fill failed: {e}", "password": None}

    page.wait_for_timeout(4000)
    text = _page_text(page)
    if CAPTCHA_RE.search(text or ""):
        return {"ok": False, "state": "needs_manual",
                "reason": "captcha appeared during signup", "password": password}
    if VERIFY_RE.search(text or ""):
        return {"ok": False, "state": "pending_verification",
                "reason": "account created — email verification needed",
                "password": password}
    if _looks_logged_in(page):
        return {"ok": True, "state": "signed_in",
                "reason": "signed in after signup", "password": password}
    # Ambiguous — treat as signed in only if the page clearly moved into
    # the app; otherwise ask the human to check.
    if re.search(r"dashboard|workspace|my creations|generate", text or "", re.I):
        return {"ok": True, "state": "signed_in",
                "reason": "landed inside the app", "password": password}
    return {"ok": False, "state": "needs_manual",
            "reason": "signup outcome unclear — needs a human check",
            "password": password}


def _hinted_button_labels(hints: list[str] | None) -> list[str]:
    """Extract remembered generate-button labels from memory texts like
    "[known] (auto_example.com) generate button labelled 'Create'"."""
    labels = []
    for h in hints or []:
        m = re.search(r"generate button labelled '([^']+)'", h)
        if m and m.group(1) not in labels:
            labels.append(m.group(1))
    return labels


def _probe_capabilities(page, kinds: list, hints: list[str] | None = None) -> dict:
    """Detect usable generation UI without submitting anything.

    Returns e.g. {"video": {"upload": "input[type=file] selector ...",
    "prompt": ..., "generate": ...}, "image": {...}}.

    hints: remembered button labels from agent memory — tried first, so
    the probe reuses what worked before instead of re-guessing.
    """
    hinted = _hinted_button_labels(hints)
    probe: dict = {}
    for kind in kinds:
        entry: dict = {}
        # File input (image upload for image-to-video / img2img).
        try:
            files = page.locator("input[type='file']")
            if files.count() > 0:
                entry["upload_inputs"] = files.count()
        except Exception:
            pass
        # Prompt field.
        try:
            prompt_loc = page.locator(
                "textarea, input[type='text'][name*='prompt' i], "
                "input[placeholder*='prompt' i], textarea[placeholder*='describe' i]")
            if prompt_loc.count() > 0:
                entry["prompt_fields"] = prompt_loc.count()
        except Exception:
            pass
        # Generate button — remembered labels first, generic regex fallback.
        try:
            found = None
            for label in hinted:
                cand = page.get_by_role(
                    "button", name=re.compile(re.escape(label), re.I))
                if cand.count() > 0:
                    found = label
                    break
            if found is None:
                gen = page.get_by_role("button", name=GENERATE_RE)
                if gen.count() > 0:
                    try:
                        found = (gen.first.inner_text() or "").strip()[:40]
                    except Exception:
                        found = "generic"
            if found:
                entry["generate_buttons"] = 1
                entry["generate_label"] = found
        except Exception:
            pass
        # A <video> element already on the page hints at video output.
        try:
            if kind == "video" and page.locator("video").count() > 0:
                entry["video_elements"] = page.locator("video").count()
        except Exception:
            pass
        probe[kind] = entry
    return probe


def _recipe_usable(probe: dict, kinds: list) -> bool:
    for kind in kinds:
        entry = probe.get(kind) or {}
        if entry.get("generate_buttons") and entry.get("prompt_fields"):
            return True
    return False


def run_provision(page, job: dict) -> dict:
    """Execute a provision job. Returns the result dict for the ledger."""
    try:
        cand = json.loads(job.get("prompt") or "{}")
    except Exception:
        return {"status": "failed", "reason": "bad candidate payload",
                "kinds": ["image"]}
    url = cand.get("url") or ""
    name = cand.get("name") or url
    kinds = cand.get("kinds") or ["image"]
    email = cand.get("email") or ""

    base = {"url": url, "name": name, "kinds": kinds}

    if not email:
        return {**base, "status": "failed",
                "reason": "no signup email configured"}

    signup = _try_signup(page, url, email)
    state = signup.get("state")

    if state in ("needs_manual", "failed"):
        return {**base, "status": state,
                "reason": signup.get("reason") or state}

    if state == "pending_verification":
        ref = _save_account(url, email, signup.get("password") or "")
        return {**base, "status": "pending_verification",
                "reason": signup.get("reason"), "account_ref": ref}

    # Signed in (or no signup needed) — probe the UI.
    # Pass remembered selectors so the probe reuses what worked before.
    probe = _probe_capabilities(page, kinds, hints=job.get("agent_memories"))
    ref = ""
    if signup.get("password"):
        ref = _save_account(url, email, signup["password"])

    if not _recipe_usable(probe, kinds):
        return {**base, "status": "needs_manual",
                "reason": ("signed in but no usable generation UI detected — "
                           "site may need manual mapping"),
                "probe": probe, "account_ref": ref}

    return {**base, "status": "active",
            "reason": (f"signed in ({state}); generation UI detected"),
            "probe": probe, "account_ref": ref}
