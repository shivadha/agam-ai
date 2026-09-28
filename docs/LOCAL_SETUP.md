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
4. **Chatterbox** local TTS (`pip install chatterbox-tts`) — the primary,
   human-grade voice (MIT, ~2GB VRAM). The model downloads from HuggingFace
   on first use (~1GB, one time).
5. Checks `ffmpeg` is present (install hints if not)
6. **Ruflo** agent harness (`npm install -g ruflo@latest`; needs Node.js)

## Chatterbox TTS — the anti-slop voice (recommended default)

Free, local, MIT. Zero-shot voice cloning, prosody controls, and native
`[laugh]` / `[chuckle]` / `[cough]` tags. Needs ~2GB VRAM; the model loads
in a short-lived worker process, so VRAM is released after each narration.

TTS node → Voice → **Chatterbox (Local Free)** (the default).

### Voice modes (type into the Voice field)

| What you type | Result |
|---|---|
| `Chatterbox (Local Free)` (the dropdown option) | Turbo 350M; clones your reference clip if one is set up (see below) |
| `chatterbox:multilingual` | Multilingual 500M — 23+ languages; set `CHATTERBOX_LANGUAGE=hi` for Hindi |
| `chatterbox:clone:C:\voices\my-voice.wav` | Clones exactly this 10–30s clip for one render |

### Your signature channel voice (do this once)

The #1 thing that makes narration sound human: clone a REAL energetic
narrator, not a stock voice.

1. Record (or source) **one 10–30 second clip** of a voice whose energy
   matches your Shorts — upbeat, conversational, clean mic, **no background
   music**.
2. Save it as `assets/chatterbox_ref.wav` in the project folder —
   or set the `CHATTERBOX_REF_AUDIO` environment variable to its path.
3. From now on, every `Chatterbox (Local Free)` render clones that voice.

The emotion in the reference carries into the output: clone an energetic
clip, get energetic narration.

### Prosody knobs (environment variables)

| Variable | Default | What it does |
|---|---|---|
| `CHATTERBOX_EXAGGERATION` | `0.6` | 0.0–1.0 prosody intensity; 0.6–0.7 for dramatic Shorts |
| `CHATTERBOX_CFG_WEIGHT` | `0.4` | ~0.3 = slower/deliberate pacing, ~0.5 = neutral |

Notes:
- First run downloads the model from HuggingFace (~1GB, one time).
- No word-level timings come from the model; the pipeline's faster-whisper
  pass generates them automatically, same as Fish Audio.
- If Chatterbox isn't installed, the TTS node falls back to Edge-TTS and the
  "Test Live Connection" button tells you to run `install_local.bat`.

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

## Image stack — photoreal base + anti-slop prompts (recommended)

The pipeline's image prompts are already hardened against AI slop
(photojournalistic 35mm style anchor, no text/logos ever, plastic-skin
negatives). You get the full benefit by dropping one checkpoint into
ComfyUI — the pipeline auto-detects it and prefers it:

**SDXL-Lightning (8-step, free, MIT-friendly — recommended)**
1. Download `sdxl_lightning_8step.safetensors` from
   https://huggingface.co/ByteDance/SDXL-Lightning (~6.5 GB, one time).
2. Copy it into your ComfyUI `models/checkpoints/` folder.
3. That's it — the pipeline prefers Lightning automatically and renders
   with 8 steps / CFG 1.0 (fast, photoreal).

Without it, the pipeline falls back to your best SDXL/SD1.5 checkpoint at
20 steps / CFG 7.0.

**Optional — FaceDetailer pass (kills waxy/plastic faces)**
1. In ComfyUI Manager: install `ComfyUI-Impact-Pack`, restart ComfyUI.
2. Download `face_yolov8m.pt` (Ultralytics) into
   ComfyUI `models/ultralytics/bbox/`.
3. Set the environment variable `AGAM_FACEDETAIL=1` before starting the app
   (e.g. `set AGAM_FACEDETAIL=1` in the same terminal as `start_agam.bat`).

The pipeline then runs a low-denoise face detail pass on every generated
image. Off by default (needs the Impact Pack), and skipped automatically
when the pack isn't installed.

**Editing finish (always on):** the caption-burn pass also applies a subtle
warm color grade + film grain + vignette to the whole video, so footage
shares one cinematic grade instead of the flat AI-plastic look.

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
