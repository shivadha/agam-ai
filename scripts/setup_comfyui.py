#!/usr/bin/env python3
"""
PulseForge — ComfyUI + LTX-Video bootstrapper (Windows / Linux / macOS).

Everything the AI-video side needs, idempotent (skip-if-present):

  1. Clones ComfyUI into <repo>/ComfyUI if it isn't there.
     (start_comfyui.bat assumes this folder exists — it never created it,
     which is why "ComfyUI is offline on 127.0.0.1:8188" appeared even
     after running the start script.)
  2. Installs ComfyUI's python requirements (skipped when already done —
     tracked by a marker file hashed against requirements.txt).
  3. Downloads LTX-Video 2B v0.9.5 (~5.3 GB, one time) when no
     image-to-video model (LTX / Wan / SVD) is found in
     ComfyUI/models/checkpoints or ComfyUI/models/diffusion_models.

About "LTX-2": LTX-2 (Lightricks, 19B video+audio) needs 20GB+ VRAM and a
completely different ComfyUI node graph — it CANNOT run on a 6GB card and
the pipeline deliberately never auto-picks it (see src/backend/comfyui_scan.py).
The model you want on an RTX 3060 6GB is LTX-Video 2B (what this script
downloads): ~10s native clips, fully supported by the auto-scan provider.

Usage:
    python scripts/setup_comfyui.py                  # full check + install
    python scripts/setup_comfyui.py --wait-for-port 127.0.0.1 8188 --timeout 180
"""

import argparse
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)  # so `from src.backend...` works standalone

COMFYUI_REPO = "https://github.com/comfyanonymous/ComfyUI"

# The one model this pipeline is tuned for on 6GB cards.
LTX_REPO_ID = "Lightricks/LTX-Video"
LTX_FILENAME = "ltx-video-2b-v0.9.5.safetensors"

PASS = "[ok]"
FAIL = "[!!]"
SKIP = "--"


def log(msg):
    print(msg, flush=True)


def run(cmd, cwd=None):
    log(f"  $ {' '.join(str(c) for c in cmd)}")
    try:
        return subprocess.run(cmd, cwd=cwd).returncode
    except FileNotFoundError as e:
        log(f"  {FAIL} not found: {e}")
        return 127


def comfy_dir():
    return os.path.join(REPO_ROOT, "ComfyUI")


def comfyui_present(cdir=None):
    """True when ComfyUI looks installed (main.py exists)."""
    cdir = cdir or comfy_dir()
    return os.path.isfile(os.path.join(cdir, "main.py"))


def ensure_cloned(cdir=None):
    """git-clone ComfyUI next to the repo when missing. Returns True if present."""
    cdir = cdir or comfy_dir()
    if comfyui_present(cdir):
        log(f"{PASS} ComfyUI already cloned at {cdir}")
        return True
    if shutil.which("git") is None:
        log(f"{FAIL} ComfyUI is not installed and `git` is not on PATH.")
        log("  Install git from https://git-scm.com/downloads, then re-run.")
        return False
    log("ComfyUI not found — cloning (one time, ~200 MB)...")
    rc = run(["git", "clone", "--depth", "1", COMFYUI_REPO, cdir])
    if rc != 0 or not comfyui_present(cdir):
        log(f"{FAIL} git clone failed — check your internet connection and re-run.")
        return False
    log(f"{PASS} ComfyUI cloned.")
    return True


def _requirements_hash(cdir):
    req = os.path.join(cdir, "requirements.txt")
    try:
        with open(req, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return "missing"


def ensure_requirements(cdir=None):
    """pip-install ComfyUI requirements unless the marker says they're done."""
    cdir = cdir or comfy_dir()
    marker = os.path.join(cdir, ".agam_deps_ok")
    want = _requirements_hash(cdir)
    try:
        with open(marker, "r", encoding="utf-8") as f:
            have = f.read().strip()
    except OSError:
        have = ""
    if have == want and want != "missing":
        log(f"{SKIP} ComfyUI python deps already installed (marker matches).")
        return True
    req = os.path.join(cdir, "requirements.txt")
    if not os.path.isfile(req):
        log(f"{FAIL} {req} not found — is the ComfyUI clone complete?")
        return False
    log("Installing ComfyUI python requirements (one time)...")
    rc = run([sys.executable, "-m", "pip", "install", "-r", req])
    if rc != 0:
        log(f"{FAIL} pip install failed — re-run this script after fixing the error above.")
        return False
    try:
        with open(marker, "w", encoding="utf-8") as f:
            f.write(want)
    except OSError:
        pass
    log(f"{PASS} ComfyUI deps installed.")
    return True


def find_i2v_models(cdir=None):
    """Return [filenames] of installed LTX/Wan/SVD models (both model dirs)."""
    from src.backend.comfyui_scan import classify_i2v
    cdir = cdir or comfy_dir()
    found = []
    for sub in ("checkpoints", "diffusion_models"):
        mdir = os.path.join(cdir, "models", sub)
        if not os.path.isdir(mdir):
            continue
        for root, _dirs, files in os.walk(mdir):
            for fn in files:
                if classify_i2v(fn):
                    found.append(os.path.join(root, fn))
    return found


def ensure_ltx_model(cdir=None):
    """Download LTX-Video 2B when no image-to-video model is installed."""
    found = find_i2v_models(cdir)
    if found:
        names = ", ".join(os.path.basename(p) for p in found)
        log(f"{PASS} image-to-video model(s) already installed: {names} — skipping download.")
        return True
    log("No LTX / Wan / SVD model found — downloading LTX-Video 2B v0.9.5 (~5.3 GB, one time)...")
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        log("  installing huggingface_hub first...")
        if run([sys.executable, "-m", "pip", "install", "huggingface_hub"]) != 0:
            log(f"{FAIL} could not install huggingface_hub.")
            return False
        from huggingface_hub import hf_hub_download
    target = os.path.join(cdir or comfy_dir(), "models", "checkpoints")
    os.makedirs(target, exist_ok=True)
    try:
        dest = hf_hub_download(
            repo_id=LTX_REPO_ID,
            filename=LTX_FILENAME,
            local_dir=target,
            local_dir_use_symlinks=False,
        )
    except Exception as e:
        log(f"{FAIL} download failed: {e}")
        log("  Re-run this script later, or download manually from")
        log(f"  https://huggingface.co/{LTX_REPO_ID} into {target}")
        return False
    log(f"{PASS} LTX-Video downloaded: {dest}")
    log("  The pipeline's auto-scan will pick it on the next run (ComfyUI -> refresh).")
    return True


def wait_for_port(host, port, timeout=180):
    """Block until host:port accepts a connection. Returns True on success."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=3):
                return True
        except OSError:
            time.sleep(2)
    return False


def main(argv=None):
    ap = argparse.ArgumentParser(description="PulseForge ComfyUI + LTX bootstrapper")
    ap.add_argument("--wait-for-port", nargs=2, metavar=("HOST", "PORT"),
                    help="only wait until HOST:PORT is listening, then exit")
    ap.add_argument("--timeout", type=int, default=180,
                    help="seconds to wait with --wait-for-port (default 180)")
    args = ap.parse_args(argv)

    if args.wait_for_port:
        host, port = args.wait_for_port[0], int(args.wait_for_port[1])
        log(f"Waiting for {host}:{port} (up to {args.timeout}s)...")
        if wait_for_port(host, port, args.timeout):
            log(f"{PASS} {host}:{port} is listening.")
            return 0
        log(f"{FAIL} {host}:{port} never came up.")
        return 1

    log("PulseForge — ComfyUI + LTX-Video setup")
    log(f"Repo: {REPO_ROOT}")
    ok = True
    log("\n=== 1/3  ComfyUI checkout ===")
    ok &= ensure_cloned()
    if ok:
        log("\n=== 2/3  ComfyUI python dependencies ===")
        ok &= ensure_requirements()
    if ok:
        log("\n=== 3/3  LTX-Video model ===")
        ok &= ensure_ltx_model()
    log("")
    if ok:
        log(f"{PASS} ComfyUI stack ready. Start it with start_comfyui.bat,")
        log("    or just run launch_pulseforge.bat — it does all of this for you.")
        return 0
    log(f"{FAIL} Some steps failed — fix the errors above and re-run.")
    log("    Re-running is safe: finished steps are skipped automatically.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
