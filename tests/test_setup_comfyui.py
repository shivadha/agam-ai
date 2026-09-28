"""Tests for scripts/setup_comfyui.py — the idempotent ComfyUI + LTX bootstrapper.

No network: model downloads are only exercised on their skip-if-present path.
"""
import importlib.util
import os
import socket
import sys
import threading

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_setup_module():
    spec = importlib.util.spec_from_file_location(
        "setup_comfyui", os.path.join(REPO_ROOT, "scripts", "setup_comfyui.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def sc():
    return load_setup_module()


@pytest.fixture()
def fake_comfy(tmp_path):
    cdir = tmp_path / "ComfyUI"
    (cdir / "models" / "checkpoints").mkdir(parents=True)
    (cdir / "models" / "diffusion_models").mkdir(parents=True)
    return str(cdir)


def test_comfyui_present_true_and_false(sc, fake_comfy, tmp_path):
    assert sc.comfyui_present(fake_comfy) is False
    with open(os.path.join(fake_comfy, "main.py"), "w") as f:
        f.write("# fake")
    assert sc.comfyui_present(fake_comfy) is True
    assert sc.comfyui_present(str(tmp_path / "nope")) is False


def test_ensure_cloned_skips_when_present(sc, fake_comfy):
    with open(os.path.join(fake_comfy, "main.py"), "w") as f:
        f.write("# fake")
    assert sc.ensure_cloned(fake_comfy) is True


def test_find_i2v_models_both_dirs(sc, fake_comfy):
    ckpt = os.path.join(fake_comfy, "models", "checkpoints")
    diff = os.path.join(fake_comfy, "models", "diffusion_models")
    open(os.path.join(ckpt, "ltx-video-2b-v0.9.5.safetensors"), "w").close()
    open(os.path.join(diff, "wan2.1_i2v_480p_14B_fp8_e4m3fn.safetensors"), "w").close()
    open(os.path.join(ckpt, "notes.txt"), "w").close()  # not a model
    found = sc.find_i2v_models(fake_comfy)
    assert len(found) == 2
    assert all("notes.txt" not in p for p in found)


def test_find_i2v_models_ltx2_detected_but_listed(sc, fake_comfy):
    ckpt = os.path.join(fake_comfy, "models", "checkpoints")
    open(os.path.join(ckpt, "ltx-2-19b-distilled.safetensors"), "w").close()
    found = sc.find_i2v_models(fake_comfy)
    # LTX-2 is detected (so the UI can show it) even though the pipeline
    # never auto-picks it for generation.
    assert len(found) == 1


def test_ensure_requirements_skips_when_marker_matches(sc, fake_comfy):
    req = os.path.join(fake_comfy, "requirements.txt")
    with open(req, "w") as f:
        f.write("torch\n")
    marker = os.path.join(fake_comfy, ".agam_deps_ok")
    with open(marker, "w") as f:
        f.write(sc._requirements_hash(fake_comfy))
    assert sc.ensure_requirements(fake_comfy) is True


def test_ensure_ltx_model_skips_when_model_present(sc, fake_comfy):
    ckpt = os.path.join(fake_comfy, "models", "checkpoints")
    open(os.path.join(ckpt, "ltx-video-2b-v0.9.5.safetensors"), "w").close()
    # Would attempt a network download if it didn't skip — must return True fast.
    assert sc.ensure_ltx_model(fake_comfy) is True


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_wait_for_port_success(sc):
    port = _free_port()
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(1)

    def _accept():
        try:
            conn, _ = srv.accept()
            conn.close()
        except OSError:
            pass

    t = threading.Thread(target=_accept, daemon=True)
    t.start()
    try:
        assert sc.wait_for_port("127.0.0.1", port, timeout=10) is True
    finally:
        srv.close()


def test_wait_for_port_timeout(sc):
    port = _free_port()  # nothing listening
    assert sc.wait_for_port("127.0.0.1", port, timeout=2) is False


def test_main_wait_for_port_cli(sc, capsys):
    port = _free_port()
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(1)

    def _accept():
        try:
            conn, _ = srv.accept()
            conn.close()
        except OSError:
            pass

    threading.Thread(target=_accept, daemon=True).start()
    try:
        rc = sc.main(["--wait-for-port", "127.0.0.1", str(port), "--timeout", "10"])
        assert rc == 0
    finally:
        srv.close()
