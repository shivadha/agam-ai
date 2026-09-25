# Free-Web Background Agent

Invisible Windows background worker that drives **free website tiers**
(ChatGPT Go, Gemini web, Veo free tier, scout-discovered sites…) with a
headless browser — so workflows get AI generation at **$0 API cost**.

## One-time setup (on your Windows PC)

1. `setup_agent.bat` — installs Playwright + the agent's Chromium (once).
2. Log in once per site (visible browser, session is saved and reused):
   ```
   python -m src.agent.agent --show-login chatgpt_go
   python -m src.agent.agent --show-login gemini_web
   python -m src.agent.agent --show-login veo_web
   ```
   Log in, close the window. Done forever (until the site logs you out).
3. `start_agent.bat` — launches invisibly (no console, no browser window).
   `stop_agent.bat` — stops it.

Tip: put a shortcut to `start_agent.bat` in
`shell:startup` to auto-start with Windows.

## How it works

```
Flask app / workflow  --enqueue-->  agent_jobs (SQLite)
                                            |
Background agent (pythonw, headless)  <--poll--+
  1. claims oldest queued job
  2. drives the provider site with Playwright (persistent profile)
  3. downloads the result into output/agent/
  4. marks job done/failed
  5. reads remaining credits (API-response sniff -> DOM selector -> regex)
     and reports to the credit ledger asynchronously (fire-and-forget)
```

## Using it from workflows

Set a node's model/provider to **`free-web`** (auto-pick) or
**`free-web:<provider_id>`** (pin a provider):

| Node | Field | Value |
|---|---|---|
| gen-script / gen-hook / gen-desc | model | `free-web:chatgpt_go` |
| image-gen | model | `free-web:gemini_web` |
| img-to-video | provider | `free-web:veo_web` |
| gen-thumbnail | base_image_model | `free-web:chatgpt_go` |

Text nodes route through `_chat_via_chain`, so every text consumer
(hook, script, description, tags, SEO) automatically supports `free-web`.

If the agent isn't running, calls fail fast with a clear message
("Background agent is not running…") instead of hanging.

## Credit ledger

`src/backend/free_providers.py` — providers table with live balances.
After each job the agent scrapes the remaining credits; when a site
redesign breaks the scrape, the ledger falls back to usage counting.
Balance hits 0 → provider auto-retires (`exhausted`).
Manage everything in the **Automation → 🆓 Free AI** tab:
enable/disable, delete, approve scout candidates, watch the job queue.

## Scout

`python -m src.agent.scout` (or the "Run scout" button) searches Reddit
and DuckDuckGo for new free AI sites and saves them as **candidates**.
Nothing becomes a live provider until you approve it in the Free AI tab.

## Provider plugins

`src/agent/providers/` — one file per site: `gemini.py`, `veo.py`,
`chatgpt.py`. Each declares `SELECTORS` (marked `# VERIFY` — sites change
their DOM; failures name the broken selector). To add a site: copy
`gemini.py`, implement `needs_login()` + `generate()`, register it in
`registry.py`, and add a row via the Free AI tab or
`free_providers.upsert_provider(...)`.
