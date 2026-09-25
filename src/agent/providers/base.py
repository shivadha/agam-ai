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
"""
from __future__ import annotations


class ProviderError(Exception):
    pass


class LoginRequired(ProviderError):
    """Raised when the site shows a logged-out state.

    The user must log in once: run the agent with --show-login, which opens
    a VISIBLE browser on the provider's login page using the same persistent
    profile; closing it after login is enough — subsequent headless runs
    reuse the session.
    """


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
