"""
base.py — Interface every free-web provider plugin implements.

A provider drives a website with Playwright:
  * login_url        — where the user logs in once (persistent profile)
  * needs_login(page) -> bool — heuristic: True if we look logged out
  * generate(page, job, out_dir) -> dict — performs the generation,
      returns {"result_path": ...} and/or {"result_text": ...}
  * kinds            — subset of {"text", "image", "video"}

Balance reading is NOT per-provider code: it lives in balance.py and uses
the provider's balance_recipe from the DB (API-response sniffing, then DOM
selector, then regex). Providers only declare a default recipe hint.

Conventions for generate():
  * job = {"id", "kind", "prompt", "input_path"}
  * raise ProviderError on any failure (agent marks job failed)
  * download results into out_dir, return absolute path
  * keep selectors in one SELECTORS dict at the top of each plugin and
    mark any unverified selector with  # VERIFY — sites change their DOM
    often; the agent logs a clear error naming the selector when it breaks.

Strategy rotation:
  * Video providers (image-to-video) declare a STRATEGIES ledger: several
    distinct, human-plausible paths to the same feature (different entry
    points, different click order, keyboard vs mouse). Driving a site the
    exact same way every run is the easiest bot pattern to fingerprint, so
    StrategyRotator picks a different strategy every run — random, never
    repeating the previous run's choice — persists the choice in
    data/agent_strategy_state.json, and the plugin logs which strategy ran
    so every job record shows the path taken.
"""
from __future__ import annotations

import json
import logging
import os
import random

log = logging.getLogger("free-agent.strategy")


class ProviderError(Exception):
    pass


class LoginRequired(ProviderError):
    """Raised when the site shows a logged-out state.

    The user must log in once: run the agent with --show-login, which opens
    a VISIBLE browser on the provider's login page using the same persistent
    profile; closing it after login is enough — subsequent headless runs
    reuse the session.
    """


def _default_state_file() -> str:
    # src/agent/providers/base.py -> repo root -> data/agent_strategy_state.json
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    return os.path.join(root, "data", "agent_strategy_state.json")


class StrategyRotator:
    """Rotates a provider's interaction strategies so no two consecutive
    runs take the same path.

    strategies: list of {"name": str, "desc": str, "run": callable}.
        The list itself is the recorded ledger — names and descriptions
        live in the plugin's code.
    """

    def __init__(self, provider_id: str, strategies: list,
                 state_file: str | None = None):
        if not strategies:
            raise ValueError("StrategyRotator needs at least one strategy")
        self.provider_id = provider_id
        self.strategies = strategies
        self.state_file = state_file or _default_state_file()

    # ── persistence ────────────────────────────────────────────────
    def _load_state(self) -> dict:
        try:
            with open(self.state_file) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_state(self, state: dict) -> None:
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, "w") as f:
                json.dump(state, f)
        except Exception as e:
            log.warning("could not persist strategy state: %s", e)

    # ── picking ────────────────────────────────────────────────────
    def pick(self) -> dict:
        """Return a strategy dict, never the same as last run's.

        The choice is persisted and logged, so the job record shows
        exactly which path was taken.
        """
        state = self._load_state()
        last = (state.get(self.provider_id) or {}).get("last_strategy")
        pool = [s for s in self.strategies if s["name"] != last]
        chosen = random.choice(pool or self.strategies)
        state[self.provider_id] = {"last_strategy": chosen["name"]}
        self._save_state(state)
        log.info("[%s] video strategy for this run: %s — %s",
                 self.provider_id, chosen["name"], chosen["desc"])
        return chosen

    def last_used(self) -> str | None:
        return (self._load_state().get(self.provider_id) or {}).get("last_strategy")


class FreeWebProvider:
    id: str = ""
    display_name: str = ""
    login_url: str = ""
    kinds: tuple = ()

    # Default balance recipe; the DB copy (admin-editable) wins at runtime.
    balance_recipe: dict = {}

    def needs_login(self, page) -> bool:
        raise NotImplementedError

    def generate(self, page, job: dict, out_dir: str) -> dict:
        raise NotImplementedError
