"""
agent.py — the invisible background worker.

Runs on the user's Windows PC (pythonw, no console window). Loop:
  1. Claim the oldest queued job from agent_jobs.
  2. Open the provider's site in a headless Chromium with a PERSISTENT
     profile (login once, session reused forever).
  3. Run the provider plugin's generate().
  4. Save the result, mark the job done/failed.
  5. Read the remaining credit balance (API sniff -> DOM -> regex) and
     report it to the ledger asynchronously (fire-and-forget).

Usage:
  python -m src.agent.agent                  # background loop (headless)
  python -m src.agent.agent --once           # process a single job, then exit
  python -m src.agent.agent --show-login gemini_web
      # VISIBLE browser for one-time login; log in, close the window.
  pythonw -m src.agent.agent                 # fully invisible (see start_agent.bat)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import traceback
from contextlib import contextmanager

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

from src.agent import queue as jobqueue
from src.agent import memory as agent_memory
from src.agent.balance import ResponseSniffer, read_balance
from src.agent.providers.base import LoginRequired, ProviderError, get_last_strategy
from src.agent.providers.registry import get_provider, known_providers
from src.backend import free_providers as ledger

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("free-agent")
# pythonw discards stderr — without a file handler every crash is invisible.
try:
    _log_dir = os.path.join(BASE_DIR, "data")
    os.makedirs(_log_dir, exist_ok=True)
    _fh = logging.FileHandler(os.path.join(_log_dir, "agent.log"), encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(_fh)
except Exception:
    pass

PROFILE_DIR = os.path.join(os.path.expanduser("~"), ".agam-agent", "profile")
OUTPUT_DIR = os.path.join(BASE_DIR, "output", "agent")
HEARTBEAT_FILE = os.path.join(BASE_DIR, "data", "agent_heartbeat.json")
PID_FILE = os.path.join(BASE_DIR, "data", "agent.pid")
POLL_SECONDS = 8
HEARTBEAT_TTL = 90  # client treats the agent as down after this many seconds


def _beat():
    """Write a heartbeat so clients fail fast when the agent isn't running."""
    try:
        os.makedirs(os.path.dirname(HEARTBEAT_FILE), exist_ok=True)
        with open(HEARTBEAT_FILE, "w") as f:
            json.dump({"ts": time.time()}, f)
    except Exception:
        pass


def _beat_forever(stop_event):
    """Background heartbeat so long jobs (25-min video renders) don't make
    the agent look dead — the client TTL is only 90s."""
    while not stop_event.wait(30):
        _beat()


def _already_running() -> bool:
    """Single-instance guard: a second pythonw sharing the Chromium profile
    would fail the profile lock AND poison the queue by claiming jobs it
    can never run."""
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
    except Exception:
        return False
    if pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)  # alive?
    except Exception:
        return False  # stale PID file
    return True


def _playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        print("Playwright is not installed. On the agent machine run:\n"
              "  pip install playwright\n"
              "  playwright install chromium")
        sys.exit(3)


def _provider_for_job(job: dict):
    provider = get_provider(job["provider_id"])
    recipe = (ledger.get_provider(job["provider_id"]) or {}).get("balance_recipe") or {}
    return provider, recipe


@contextmanager
def _browser_page(pw, headless: bool = True):
    """Launch the persistent-profile Chromium and yield a fresh page."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(PROFILE_DIR, exist_ok=True)
    sync_playwright = _playwright()
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1366, "height": 900},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0.0.0 Safari/537.36"),
        )
        page = browser.new_page()
        try:
            yield page
        finally:
            try:
                page.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass


def _process_provision(pw, headless: bool, job: dict) -> bool:
    """Run an auto-provision job: sign up on a new free site + probe it."""
    from src.agent import provision as provisioner
    log.info("[job %s] provision: %s", job["id"],
             (job.get("prompt") or "")[:80])
    try:
        with _browser_page(pw, headless) as page:
            result = provisioner.run_provision(page, job)
        jobqueue.complete_job(job["id"], result_text=json.dumps(result))
        log.info("[job %s] provision -> %s (%s)", job["id"],
                 result.get("status"), result.get("reason"))
        # Learn: a successful probe becomes reusable facts about the site.
        if result.get("status") == "active":
            pid = job["provider_id"]
            for kind, entry in (result.get("probe") or {}).items():
                label = entry.get("generate_label")
                if label:
                    agent_memory.remember(
                        pid, "fact",
                        f"generate button labelled '{label}' for {kind}",
                        confidence=0.8)
                if entry.get("prompt_fields"):
                    agent_memory.remember(
                        pid, "fact",
                        f"prompt field present ({entry['prompt_fields']} found) "
                        f"for {kind}", confidence=0.8)
        else:
            agent_memory.learn_from_job(
                job, ok=False,
                detail=f"provision {result.get('status')}: "
                       f"{result.get('reason') or ''}")
    except Exception:
        jobqueue.fail_job(job["id"], traceback.format_exc(limit=5))
        agent_memory.learn_from_job(job, ok=False, detail="provision crashed")
        log.exception("[job %s] provision crashed", job["id"])
    return True


def process_one(pw, headless: bool = True) -> bool:
    """Claim and run a single job. Returns True if a job was processed."""
    job = jobqueue.claim_next_job()
    if not job:
        return False
    log.info("[job %s] claimed: %s/%s", job["id"], job["provider_id"], job["kind"])

    # ── memory: recall what the agent learned, learn from this run ──
    job["agent_memories"] = agent_memory.recall_texts(job["provider_id"])
    if job["agent_memories"]:
        log.info("[job %s] recalling %d memories", job["id"],
                 len(job["agent_memories"]))

    # ── auto-provisioning: scouted site -> try to bring it online ──
    if job["kind"] == "provision":
        return _process_provision(pw, headless, job)

    try:
        provider, recipe = _provider_for_job(job)
    except KeyError as e:
        jobqueue.fail_job(job["id"], str(e))
        agent_memory.learn_from_job(job, ok=False, detail=str(e))
        return True

    sniffer = ResponseSniffer(recipe.get("api_patterns"))
    try:
        with _browser_page(pw, headless) as page:
            sniffer.attach(page)
            try:
                if provider.needs_login(page):
                    raise LoginRequired(
                        f"{provider.display_name}: logged out. Run "
                        f"'python -m src.agent.agent --show-login {provider.id}' "
                        f"once to log in.")
                result = provider.generate(page, job, OUTPUT_DIR)
            finally:
                sniffer.detach(page)
                try:
                    live_balance = read_balance(page, recipe, sniffer)
                except Exception:
                    live_balance = None
            jobqueue.complete_job(
                job["id"],
                result_path=result.get("result_path"),
                result_text=result.get("result_text"),
                balance_after=live_balance,
                strategy=get_last_strategy(job["provider_id"]) or "",
            )
            # Learn: record what worked (strategy from the rotator, if any).
            agent_memory.learn_from_job(
                job, ok=True, detail=get_last_strategy(job["provider_id"]) or "")
            # Async ledger update: fire-and-forget, never blocks the loop.
            try:
                updated = ledger.record_usage(job["provider_id"], live_balance)
                if updated and updated["status"] == "exhausted":
                    log.warning("[ledger] %s exhausted, auto-retired",
                                job["provider_id"])
            except Exception as e:
                log.warning("[ledger] record_usage failed: %s", e)
            log.info("[job %s] done (balance=%s)", job["id"], live_balance)
    except (ProviderError, LoginRequired) as e:
        jobqueue.fail_job(job["id"], str(e))
        agent_memory.learn_from_job(job, ok=False, detail=str(e))
        log.warning("[job %s] failed: %s", job["id"], e)
    except Exception:
        jobqueue.fail_job(job["id"], traceback.format_exc(limit=5))
        agent_memory.learn_from_job(job, ok=False, detail="unexpected crash")
        log.exception("[job %s] crashed", job["id"])
    return True


def show_login(provider_id: str):
    """Visible one-time login flow using the same persistent profile."""
    provider = get_provider(provider_id)
    os.makedirs(PROFILE_DIR, exist_ok=True)
    sync_playwright = _playwright()
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            PROFILE_DIR, headless=False,
            viewport={"width": 1366, "height": 900})
        page = browser.new_page()
        page.goto(provider.login_url)
        print(f"\nLog in to {provider.display_name} in the opened window,")
        print("then close the window (or press Enter here). The session is saved")
        print(f"to {PROFILE_DIR} and reused by headless runs.\n")
        try:
            input()
        except EOFError:
            pass
        browser.close()
    print("Login profile saved.")


def main():
    ap = argparse.ArgumentParser(description="Agam free-web background agent")
    ap.add_argument("--once", action="store_true",
                    help="process a single queued job, then exit")
    ap.add_argument("--show-login", metavar="PROVIDER",
                    help=f"visible one-time login ({'/'.join(known_providers())})")
    ap.add_argument("--poll", type=int, default=POLL_SECONDS,
                    help="seconds between queue polls")
    ap.add_argument("--headful", action="store_true",
                    help="run with a visible browser (debugging)")
    args = ap.parse_args()

    if args.show_login:
        show_login(args.show_login)
        return

    sync_playwright = _playwright()  # fail fast if missing
    if _already_running():
        # Message goes to agent.log (file handler) since pythonw has no console.
        log.error("[agent] another instance is already running (see data/agent.pid) — exiting.")
        print("[agent] another instance is already running — exiting.")
        sys.exit(2)
    log.info("[agent] starting (headless=%s, poll=%ss)",
             not args.headful, args.poll)
    try:
        os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass
    import threading as _threading
    _hb_stop = _threading.Event()
    _hb_thread = _threading.Thread(target=_beat_forever, args=(_hb_stop,),
                                   daemon=True, name="agent-heartbeat")
    _hb_thread.start()
    try:
        while True:
            _beat()
            worked = process_one(sync_playwright, headless=not args.headful)
            if args.once:
                break
            if not worked:
                time.sleep(args.poll)
    except KeyboardInterrupt:
        log.info("[agent] stopped")
    finally:
        _hb_stop.set()
        for p in (PID_FILE, HEARTBEAT_FILE):
            try:
                os.remove(p)
            except Exception:
                pass


if __name__ == "__main__":
    main()
