"""
auto_bootstrap.py — "just run it" preflight.

The user will not remember setup steps (pip installs, starting the
background agent, ffmpeg). So this runs automatically every time a
workflow is launched (full run, retry, single-node preview) and fixes
everything fixable on its own:

  1. Missing Python packages for the nodes in this workflow  -> pip install
  2. Missing ffmpeg/ffprobe                                   -> pip install imageio-ffmpeg (bundled binary)
  3. Free-web background agent not running                    -> start it detached

Only things that genuinely need the user (API keys, website logins,
ComfyUI server) still block the run — everything else is silent.
"""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
import time

# ── Resolved tool binaries (filled by ensure_ffmpeg) ─────────────────────────
BIN: dict = {"ffmpeg": None, "ffprobe": None}

# node_type -> (import_name, pip_package)
NODE_PIP_DEPS = {
    "clone-short": ("yt_dlp", "yt-dlp"),
    "tts": ("edge_tts", "edge-tts"),
    "voice": ("edge_tts", "edge-tts"),
    "transcribe": ("faster_whisper", "faster-whisper"),
    "whisper": ("faster_whisper", "faster-whisper"),
    "assemble-video": ("moviepy", "moviepy"),
    "make-clips": ("moviepy", "moviepy"),
}

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _pip_install(package: str, timeout: int = 300) -> tuple[bool, str]:
    """pip install a package quietly. Returns (ok, message)."""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", package],
            capture_output=True, text=True, timeout=timeout,
        )
        if r.returncode == 0:
            return True, f"installed {package}"
        tail = (r.stderr or r.stdout or "").strip().splitlines()
        return False, f"pip install {package} failed: {tail[-1] if tail else 'unknown error'}"
    except Exception as e:
        return False, f"pip install {package} crashed: {e}"


def ensure_pip(import_name: str, pip_name: str) -> tuple[bool, str, bool]:
    """Ensure an importable module exists, installing it if needed.
    Returns (ok, message, was_fixed)."""
    try:
        importlib.import_module(import_name)
        return True, f"{pip_name} already present", False
    except ImportError:
        pass
    ok, msg = _pip_install(pip_name)
    if ok:
        try:
            importlib.import_module(import_name)
            return True, f"{pip_name} auto-installed", True
        except ImportError as e:
            return False, f"{pip_name} installed but not importable: {e}", False
    return False, msg, False


def ensure_ffmpeg() -> tuple[bool, str, bool]:
    """Ensure ffmpeg (+ffprobe if possible) is usable. Falls back to the
    imageio-ffmpeg bundled binary when no system ffmpeg exists.
    Fills BIN and returns (ok, message, was_fixed)."""
    global BIN
    ff = shutil.which("ffmpeg")
    fp = shutil.which("ffprobe")
    if ff:
        BIN = {"ffmpeg": ff, "ffprobe": fp}
        return True, "ffmpeg already on PATH", False
    # Auto-fix: imageio-ffmpeg ships a static ffmpeg binary (no ffprobe).
    ok, msg, fixed = ensure_pip("imageio_ffmpeg", "imageio-ffmpeg")
    if ok:
        try:
            import imageio_ffmpeg
            BIN = {"ffmpeg": imageio_ffmpeg.get_ffmpeg_exe(), "ffprobe": None}
            return True, "ffmpeg auto-installed via imageio-ffmpeg (bundled binary)", True
        except Exception as e:
            return False, f"imageio-ffmpeg installed but binary not found: {e}", False
    return False, f"no ffmpeg found and auto-install failed ({msg}); install ffmpeg from https://ffmpeg.org/download.html", False


def ffmpeg_bin() -> str | None:
    """Best available ffmpeg path (auto-ensured)."""
    if BIN.get("ffmpeg"):
        return BIN["ffmpeg"]
    ok, _, _ = ensure_ffmpeg()
    return BIN["ffmpeg"] if ok else None


def ffprobe_bin() -> str | None:
    """Best available ffprobe path, or None (callers should fall back to ffmpeg -i parsing)."""
    if BIN.get("ffprobe"):
        return BIN["ffprobe"]
    ensure_ffmpeg()
    return BIN.get("ffprobe")


def _start_agent_detached() -> tuple[bool, str]:
    """Launch the free-web background agent detached from this process."""
    agent_log = os.path.join(REPO_ROOT, "data", "agent_autostart.log")
    os.makedirs(os.path.dirname(agent_log), exist_ok=True)
    cmd = [sys.executable, "-m", "src.agent.agent"]
    try:
        if os.name == "nt":
            # Prefer pythonw (no console window); fall back to CREATE_NO_WINDOW.
            pythonw = shutil.which("pythonw")
            if pythonw:
                cmd[0] = pythonw
            logf = open(agent_log, "a")
            subprocess.Popen(
                cmd, cwd=REPO_ROOT,
                stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                creationflags=subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
                | getattr(subprocess, "CREATE_NO_WINDOW", 0),
                close_fds=True,
            )
        else:
            # POSIX: fully detached session so cron/worker teardowns can't SIGTERM it.
            with open(agent_log, "a") as logf:
                subprocess.Popen(
                    ["setsid", "nohup"] + cmd, cwd=REPO_ROOT,
                    stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                    start_new_session=True, close_fds=True,
                )
        return True, "agent process launched"
    except Exception as e:
        return False, f"could not launch agent: {e}"


def ensure_agent(wait_s: int = 25) -> tuple[bool, str, bool]:
    """Ensure the free-web background agent is alive, starting it if needed.
    Returns (ok, message, was_fixed)."""
    try:
        from src.backend.free_agent_client import agent_alive
    except Exception as e:
        return False, f"agent client unavailable: {e}", False
    if agent_alive():
        return True, "background agent already running", False
    ok, msg = _start_agent_detached()
    if not ok:
        return False, msg, False
    deadline = time.time() + wait_s
    while time.time() < deadline:
        time.sleep(2)
        try:
            if agent_alive():
                return True, "background agent auto-started", True
        except Exception:
            pass
    return False, ("agent launched but no heartbeat yet — it may still be starting "
                   "(first run needs: setup_agent.bat once, then one --show-login per site)"), False


def _workflow_uses_free_web(workflow: dict) -> bool:
    for node in workflow.get("nodes", []) or []:
        cfg = {**(node.get("data") or {}), **(node.get("config") or {})}
        for key in ("model", "provider"):
            v = str(cfg.get(key) or "")
            if v.startswith("free-web"):
                return True
    return False


def bootstrap_workflow(workflow: dict) -> dict:
    """Auto-fix everything fixable before a workflow runs.
    Returns {"fixed": [...], "failed": [...]} — failed items still need the user."""
    fixed, failed = [], []

    # 1. Per-node Python packages.
    node_types = {(n.get("type") or "").lower() for n in workflow.get("nodes", []) or []}
    for ntype, (imp, pip_name) in NODE_PIP_DEPS.items():
        if ntype in node_types:
            ok, msg, was_fixed = ensure_pip(imp, pip_name)
            if was_fixed:
                fixed.append(f"{pip_name}: {msg}")
            elif not ok:
                failed.append(f"{pip_name}: {msg}")

    # 2. ffmpeg — the video pipeline almost always needs it.
    ok, msg, was_fixed = ensure_ffmpeg()
    if was_fixed:
        fixed.append(f"ffmpeg: {msg}")
    elif not ok:
        failed.append(f"ffmpeg: {msg}")

    # 3. Free-web background agent.
    if _workflow_uses_free_web(workflow):
        ok, msg, was_fixed = ensure_agent()
        if was_fixed:
            fixed.append(f"agent: {msg}")
        elif not ok:
            failed.append(f"agent: {msg}")

    return {"fixed": fixed, "failed": failed}


def bootstrap_report_text(report: dict) -> str:
    lines = []
    for f in report.get("fixed", []):
        lines.append(f"  ✓ auto-setup: {f}")
    for f in report.get("failed", []):
        lines.append(f"  ✗ still missing: {f}")
    return "\n".join(lines)
