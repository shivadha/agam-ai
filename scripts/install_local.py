#!/usr/bin/env python3
"""
AGAM AI Studio — one-command local setup (Windows / Linux / macOS).

Run this after EVERY `git pull`:
    python scripts/install_local.py
    (on Windows you can also double-click install_local.bat)

It installs / verifies everything the project needs, including things
mentioned in chat: python dependencies, NVIDIA CUDA torch, the OmniVoice
local TTS engine (+ its model download), and the Ruflo agent harness.

Everything here is free. The only network use is downloading packages.
"""

import os
import platform
import shutil
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IS_WINDOWS = platform.system() == "Windows"

PASS = "[ok]"
FAIL = "[!!]"
SKIP = "--"


def log(msg):
    print(msg, flush=True)


def run(cmd, **kwargs):
    """Run a command, streaming output. Returns exit code."""
    log(f"  $ {' '.join(str(c) for c in cmd)}")
    try:
        return subprocess.run(cmd, **kwargs).returncode
    except FileNotFoundError as e:
        log(f"  {FAIL} not found: {e}")
        return 127


def pip_install(*packages, extra_args=()):
    cmd = [sys.executable, "-m", "pip", "install", *packages, *extra_args]
    return run(cmd)


def step(title):
    log("")
    log(f"=== {title} ===")


def _hf_model_cached(repo_id: str) -> bool:
    """True when a HuggingFace Hub snapshot of repo_id is already cached."""
    hub_root = os.environ.get("HF_HOME", os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub"))
    cache_dir = os.path.join(hub_root, "models--" + repo_id.replace("/", "--"), "snapshots")
    try:
        if not os.path.isdir(cache_dir):
            return False
        for snap in os.listdir(cache_dir):
            snap_path = os.path.join(cache_dir, snap)
            if os.path.isdir(snap_path) and os.listdir(snap_path):
                return True
    except OSError:
        pass
    return False


def main():
    log("AGAM AI Studio — local setup")
    log(f"Python {platform.python_version()} on {platform.system()} {platform.machine()}")
    if sys.version_info < (3, 10):
        log(f"{FAIL} Python 3.10+ is required (OmniVoice needs it).")
        return 1

    # 1. pip + project requirements -------------------------------------
    step("1/6  Python dependencies (requirements.txt)")
    run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
    req = os.path.join(REPO_ROOT, "requirements.txt")
    if os.path.exists(req):
        if pip_install("-r", req) != 0:
            log(f"{FAIL} requirements.txt install had errors — continuing anyway.")
        else:
            log(f"{PASS} requirements installed.")
    else:
        log(f"{SKIP} requirements.txt not found.")

    # 2. Torch (NVIDIA CUDA first, so OmniVoice never pulls a CPU torch) --
    step("2/6  PyTorch (CUDA for NVIDIA GPUs)")
    torch_ok_cuda = False
    try:
        import torch  # noqa: F401
        import torch as _t
        torch_ok_cuda = _t.cuda.is_available()
        log(f"{PASS} torch {_t.__version__} already installed "
            f"(CUDA available: {torch_ok_cuda}).")
    except Exception:
        log(f"{SKIP} torch not installed yet.")
    if not torch_ok_cuda:
        has_nvidia = shutil.which("nvidia-smi") is not None
        if has_nvidia:
            log("NVIDIA GPU detected — installing CUDA torch (per OmniVoice README)...")
            rc = pip_install("torch==2.8.0+cu128", "torchaudio==2.8.0+cu128",
                             extra_args=("--extra-index-url",
                                         "https://download.pytorch.org/whl/cu128"))
            if rc == 0:
                log(f"{PASS} CUDA torch installed.")
            else:
                log(f"{FAIL} CUDA torch install failed — OmniVoice will fall back "
                    "to plain `pip install omnivoice` (CPU torch, slow).")
        else:
            log(f"{SKIP} no NVIDIA GPU detected — skipping CUDA torch "
                "(plain pip install will pull a CPU build if needed).")

    # 3. OmniVoice --------------------------------------------------------
    step("3/6  OmniVoice local TTS (k2-fsa/OmniVoice, free, Apache-2.0)")
    import importlib.util
    if importlib.util.find_spec("omnivoice") is None:
        log("Installing `omnivoice` from PyPI (stable release)...")
        if pip_install("omnivoice") != 0:
            log(f"{FAIL} `pip install omnivoice` failed.")
        import importlib
        importlib.invalidate_caches()
    if importlib.util.find_spec("omnivoice") is not None:
        log(f"{PASS} `omnivoice` package installed.")
    else:
        log(f"{FAIL} `omnivoice` still not importable — TTS node option "
            "'OmniVoice (Local Free)' will fall back to Edge-TTS.")
    if shutil.which("omnivoice-infer"):
        log(f"{PASS} `omnivoice-infer` CLI on PATH.")
    else:
        log(f"{SKIP} `omnivoice-infer` not on PATH (pip scripts dir may not be "
            "on PATH — the app uses the package directly, so this is fine).")

    # 3b. Pre-download the model so the first render isn't slow -----------
    step("3b/6 Pre-downloading the OmniVoice model (~a few GB, one time)")
    if _hf_model_cached("k2-fsa/OmniVoice"):
        log(f"{PASS} model already cached — skipping download.")
    else:
        dl_code = (
            "from huggingface_hub import snapshot_download;"
            "snapshot_download('k2-fsa/OmniVoice');"
            "print('model cached')"
        )
        rc = run([sys.executable, "-c", dl_code])
        if rc == 0:
            log(f"{PASS} model cached.")
        else:
            log(f"{SKIP} model pre-download failed (it will download on first "
                "TTS use instead — needs internet + HF access).")

    # 3c. Chatterbox (MIT, human-grade local TTS — primary voice) --------
    step("3c/6 Chatterbox local TTS (resemble-ai/chatterbox, free, MIT)")
    import importlib.util
    if importlib.util.find_spec("chatterbox") is None:
        log("Installing `chatterbox-tts` from PyPI (stable release)...")
        if pip_install("chatterbox-tts") != 0:
            log(f"{FAIL} `pip install chatterbox-tts` failed.")
        import importlib
        importlib.invalidate_caches()
    if importlib.util.find_spec("chatterbox") is not None:
        log(f"{PASS} `chatterbox-tts` package installed.")
    else:
        log(f"{FAIL} `chatterbox-tts` still not importable — TTS node option "
            "'Chatterbox (Local Free)' will fall back to Edge-TTS.")
    # The Turbo model (~1GB) auto-downloads from HF on first use; no
    # pre-download here (HF cache check for this repo family is unreliable).
    log(f"{SKIP} Chatterbox model downloads on first TTS use (one time, ~1GB).")

    # 4. ffmpeg ------------------------------------------------------------
    step("4/6  ffmpeg (audio/video conversion)")
    if shutil.which("ffmpeg"):
        log(f"{PASS} ffmpeg found.")
    else:
        log(f"{FAIL} ffmpeg not found.")
        if IS_WINDOWS:
            log("  Install with:  winget install Gyan.FFmpeg")
        elif platform.system() == "Darwin":
            log("  Install with:  brew install ffmpeg")
        else:
            log("  Install with:  sudo apt install ffmpeg")

    # 5. Node.js + Ruflo ---------------------------------------------------
    step("5/6  Ruflo agent harness (github.com/ruvnet/ruflo, MIT)")
    if not shutil.which("node") or not shutil.which("npm"):
        log(f"{SKIP} node/npm not found — skipping Ruflo.")
        log("  To get Ruflo later: install Node.js LTS from https://nodejs.org, "
            "then re-run this script (or: npm install -g ruflo@latest).")
    else:
        if shutil.which("ruflo"):
            log(f"{PASS} Ruflo already installed — skipping.")
        else:
            log("Installing Ruflo (npm `ruflo@latest` — official dist of ruvnet/ruflo)...")
            npm_cmd = ["npm", "install", "-g", "ruflo@latest"]
            rc = run(npm_cmd)
            if rc != 0 and not IS_WINDOWS:
                log("  Retrying with sudo (npm global dir not writable)...")
                rc = run(["sudo", *npm_cmd])
            if shutil.which("ruflo"):
                run(["ruflo", "--version"])
                log(f"{PASS} Ruflo installed. Scaffold it in this project with:")
                log(f"  cd {REPO_ROOT} && npx ruflo@latest init")
            else:
                log(f"{FAIL} Ruflo install failed — try manually: npm install -g ruflo@latest")

    # 6. Summary ------------------------------------------------------------
    step("6/6  Summary")
    log(f"{PASS} Setup pass finished.")
    log("")
    log("Next steps:")
    log("  1. Add API keys in the app's API Keys modal (Gemini / Fish Audio — all free).")
    log("  2. Start the app:  start_agam.bat  (Windows) or  python app.py")
    log("  3. TTS node now offers 'OmniVoice (Local Free)'.")
    log("     Voice cloning: set voice to  omni:clone:C:\\path\\to\\your-voice.wav")
    log("     Voice design:  set voice to  omni:design:female, low pitch, indian accent")
    log("     (Or set OMNIVOICE_REF_AUDIO env var to always clone your voice.)")
    log("")
    log("Re-run this script after every `git pull` — it only installs what's missing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
