"""
local_services.py — Auto-start local AI services on app boot.
=============================================================
When the AGAM app starts, this ensures the local components it depends on
are running, launching them detached in the background if needed:

  - ComfyUI  (image-to-video / local image gen) — http://127.0.0.1:8188
  - Ollama   (local LLM for scripts)            — http://127.0.0.1:11434

Idempotent: if a port is already listening, or this same boot sequence
already spawned the services (marker file + PID liveness), nothing happens.

Disable entirely with:  AGAM_NO_AUTOSTART=1
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_DIR = os.path.join(BASE_DIR, "logs")
MARKER_FILE = os.path.join(DATA_DIR, ".local_services.json")
MARKER_TTL_SEC = 600  # treat a recent marker as "services still booting"


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


def _pid_alive(pid: int) -> bool:
    try:
        if os.name == "nt":
            import ctypes
            PROCESS_QUERY_LIMITED = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
            if not h:
                return False
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _read_marker():
    try:
        with open(MARKER_FILE, "r", encoding="utf-8") as f:
            m = json.load(f)
        if time.time() - float(m.get("started_at", 0)) < MARKER_TTL_SEC:
            return m
    except Exception:
        pass
    return None


def _write_marker(services):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(MARKER_FILE, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "started_at": time.time(),
                       "services": services}, f)
    except Exception as e:
        print(f"[local_services] Could not write marker: {e}", flush=True)


def _spawn_detached(cmd, log_name):
    """Launch a process fully detached so it outlives the Flask process."""
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, log_name)
    log_f = open(log_path, "ab")
    kwargs = {"stdout": log_f, "stderr": subprocess.STDOUT,
              "stdin": subprocess.DEVNULL, "cwd": BASE_DIR}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)
    return proc.pid


def _parse_host_port(url: str, default_port: int):
    try:
        from urllib.parse import urlparse
        u = urlparse(url)
        return (u.hostname or "127.0.0.1"), (u.port or default_port)
    except Exception:
        return "127.0.0.1", default_port


def _ensure_comfyui():
    comfy_url = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")
    host, port = _parse_host_port(comfy_url, 8188)
    if _port_open(host, port):
        print(f"[local_services] ComfyUI already running on {host}:{port}.", flush=True)
        return "already-running"

    comfy_dir = os.path.join(BASE_DIR, "ComfyUI")
    main_py = os.path.join(comfy_dir, "main.py")
    if not os.path.isfile(main_py):
        print("[local_services] ComfyUI not found at ./ComfyUI — skipping auto-start. "
              "Install it next to app.py to enable local video/image generation.", flush=True)
        return "not-installed"

    cmd = [sys.executable, "main.py", "--listen", host, "--port", str(port),
           "--reserve-vram", "0.8", "--disable-mmap"]
    # run from the ComfyUI dir so its relative paths resolve
    os.makedirs(LOG_DIR, exist_ok=True)
    log_f = open(os.path.join(LOG_DIR, "comfyui.log"), "ab")
    kwargs = {"stdout": log_f, "stderr": subprocess.STDOUT,
              "stdin": subprocess.DEVNULL, "cwd": comfy_dir}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    pid = subprocess.Popen(cmd, **kwargs).pid
    print(f"[local_services] Starting ComfyUI (PID {pid}) → {comfy_url} "
          f"(models take a bit to load; status shows in the UI).", flush=True)
    return "started"


def _ensure_ollama():
    host, port = "127.0.0.1", 11434
    if _port_open(host, port):
        print(f"[local_services] Ollama already running on {host}:{port}.", flush=True)
        return "already-running"
    ollama_bin = shutil.which("ollama")
    if not ollama_bin:
        print("[local_services] Ollama not installed — skipping. "
              "Install from ollama.com to enable free local script generation.", flush=True)
        return "not-installed"
    pid = _spawn_detached([ollama_bin, "serve"], "ollama.log")
    print(f"[local_services] Starting Ollama (PID {pid}) → http://{host}:{port}.", flush=True)
    return "started"


def ensure_local_services():
    """
    Make sure local AI services are up. Safe to call on every boot —
    already-running services are never restarted.
    Returns a dict of service -> status.
    """
    if os.environ.get("AGAM_NO_AUTOSTART") == "1":
        print("[local_services] Auto-start disabled (AGAM_NO_AUTOSTART=1).", flush=True)
        return {}

    marker = _read_marker()
    if marker and _pid_alive(int(marker.get("pid", -1))):
        print("[local_services] Services were already auto-started by this boot sequence "
              "(still launching) — skipping.", flush=True)
        return {s: "booting" for s in marker.get("services", [])}

    print("[local_services] Checking local AI services...", flush=True)
    results = {
        "comfyui": _ensure_comfyui(),
        "ollama": _ensure_ollama(),
    }
    started = [k for k, v in results.items() if v == "started"]
    if started:
        _write_marker(started)
        # brief grace period so quick health checks right after boot see progress
        for _ in range(6):
            time.sleep(1)
            if _port_open("127.0.0.1", 8188):
                break
    print(f"[local_services] Done: {results}", flush=True)
    return results
