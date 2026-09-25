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

## Fallback chain: the agent acts like an AI (A → B → C)

`generate_via_agent()` no longer dies when one site fails. It walks the
ranked provider list (`free_providers.ranked_providers()`: known positive
balance first, then unknown, then priority) — option A, then B, then C —
and a pinned `free-web:<id>` keeps the old fail-loud behaviour (never
silently swaps a provider you pinned).

When **every** known option fails, the agent scouts the web for brand-new
free alternatives and tries to bring one online by itself:

1. `free_provision.ensure_capacity(kind)` runs the scout (Reddit + DDG).
2. For the best pending candidates it enqueues a `provision` job.
3. The agent **auto-creates an account** on the site (best effort, with
   the signup email from `POST /api/free/config`) and probes its
   image / image-to-video UI without burning credits.
4. Sites that come online are promoted into the ledger automatically
   (`auto_<domain>` providers). Sites behind CAPTCHA / email verification
   are flagged as `needs_manual` / `needs_verification` in the Free AI tab
   instead of failing silently.

Auto-created account passwords live in `data/agent_accounts.json`
(local only, git-ignored, mode 0600).

## ChatGPT-written prompts (image + motion)

Before any free-web generation, the orchestrator guarantees two things
(`src/backend/free_prompting.py`):

1. **Image prompt** — every scene gets an `image_prompt` written by
   ChatGPT (via the free-web agent, `free-web:chatgpt_go`), grounded in
   the main script: subject, mood, lighting, 9:16 composition.
2. **Motion script** — every scene gets an `image_to_video_prompt` written
   by ChatGPT from the main script **and** the scene's own image prompt:
   camera move + in-frame dynamics (4–6s), continuing that scene's story
   instead of a generic "slow push-in".

Both run as one batched chat call per missing-prompt type (not one call
per scene); scenes that already carry prompts (e.g. from gen-script) are
left untouched. If the agent is down, prompting falls back to the normal
model chain so the pipeline never dies.

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
Manual scout runs need your one-click approval in the Free AI tab;
the automatic fallback chain (above) can also provision candidates by
itself when every known provider has failed.

## Provider plugins

`src/agent/providers/` — one file per site: `gemini.py`, `veo.py`,
`chatgpt.py`. Each declares `SELECTORS` (marked `# VERIFY` — sites change
their DOM; failures name the broken selector). To add a site: copy
`gemini.py`, implement `needs_login()` + `generate()`, register it in
`registry.py`, and add a row via the Free AI tab or
`free_providers.upsert_provider(...)`.

## Strategy rotation (video providers)

`gemini_web` and `veo_web` both do image-to-video, and every run takes a
*different recorded path* to the feature — doing the exact same clicks in
the same order every time is the easiest bot pattern to fingerprint.

- Each plugin has a `VIDEO_STRATEGIES` ledger at the bottom of its file:
  every distinct way to reach image-to-video, with a name and description
  (e.g. Gemini: `video_chip`, `tools_menu`, `model_picker`,
  `chat_intent`; Veo/Flow: `frames_direct`, `new_project_first`,
  `prompt_first`, `keyboard_flow`).
- `StrategyRotator` (in `providers/base.py`) picks one per run at random,
  never repeating the previous run's choice. The choice is persisted in
  `data/agent_strategy_state.json` and logged, and the used strategy name
  is stored on the job result — so every video job records which path it
  took. To teach the agent a new way, add one `_strategy_*` function +
  one ledger entry; nothing else changes.
