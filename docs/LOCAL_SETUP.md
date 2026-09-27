# Local setup — AGAM AI Studio

Everything is free. Nothing here goes live; it all runs on your machine.

## After every `git pull`

```bat
install_local.bat
```

(or `python scripts/install_local.py` / `./install_local.sh` on Linux/macOS).

The script is idempotent — it only installs what's missing:

1. `requirements.txt` python packages
2. CUDA PyTorch (only if you have an NVIDIA GPU and torch isn't CUDA-ready)
3. **OmniVoice** local TTS (`pip install omnivoice`) + pre-downloads the
   `k2-fsa/OmniVoice` model so your first render isn't slow
4. Checks `ffmpeg` is present (install hints if not)
5. **Ruflo** agent harness (`npm install -g ruflo@latest`; needs Node.js)

## OmniVoice TTS

Free, local, Apache-2.0. No API key, no character limits, works offline
after the model is cached. Needs ~4GB VRAM (fits a 6GB card); the model
loads in a short-lived worker process, so VRAM is released after each
narration.

TTS node → Voice → **OmniVoice (Local Free)**.

### Voice modes (type into the Voice field)

| What you type | Result |
|---|---|
| `OmniVoice (Local Free)` (the dropdown option) | Auto voice — model picks one |
| `omni:design:female, low pitch, indian accent` | Voice designed from a description (gender, age, pitch, accent…) |
| `omni:clone:C:\voices\my-voice.wav` | Clones your voice from a 3–10s clip |
| `omni:clone:C:\voices\my-voice.wav\|transcript of the clip` | Same, with manual transcript (skips Whisper) |

Tip: set the `OMNIVOICE_REF_AUDIO` environment variable to your voice clip
and every `OmniVoice (Local Free)` render clones it automatically —
your signature channel voice, free forever.

Notes:
- First run downloads the model from HuggingFace (a few GB, one time).
- No word-level timings come from the model; the pipeline's faster-whisper
  pass generates them automatically, same as Fish Audio.
- If OmniVoice isn't installed, the TTS node falls back to Edge-TTS and the
  "Test Live Connection" button tells you to run `install_local.bat`.

## Ruflo

[Ruflo](https://github.com/ruvnet/ruflo) (MIT, formerly claude-flow) is an
agent meta-harness for coding agents (Claude Code, Codex, …). The setup
script installs its CLI globally. To scaffold it inside this project:

```bash
cd <agam-ai folder>
npx ruflo@latest init
```

This generates agent config (`AGENTS.md`, `.claude/`, `.agents/`, `.mcp.json`)
— local-only dev tooling, not part of the app.

## Start the app

```bat
start_agam.bat
```

Then open the URL it prints, add your free API keys in the API Keys modal
(Gemini / Fish Audio), and render.
