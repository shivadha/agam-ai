"""Tests for src/backend/auto_bootstrap.py — the 'just run it' self-healing preflight."""
import os
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.backend import auto_bootstrap as ab


class TestEnsurePip(unittest.TestCase):
    def test_already_present(self):
        ok, msg, fixed = ab.ensure_pip("json", "json")
        self.assertTrue(ok)
        self.assertFalse(fixed)

    def test_installs_missing(self):
        real_import = ab.importlib.import_module

        def fake_import(name):
            if name == "some_missing_mod":
                raise ImportError("nope")
            return real_import(name)

        with patch.object(ab.importlib, "import_module", side_effect=fake_import), \
             patch.object(ab, "_pip_install", return_value=(False, "no internet")) as pip:
            ok, msg, fixed = ab.ensure_pip("some_missing_mod", "some-pkg")
            self.assertFalse(ok)
            self.assertFalse(fixed)
            pip.assert_called_once_with("some-pkg")
            self.assertIn("no internet", msg)


class TestEnsureFfmpeg(unittest.TestCase):
    def test_system_ffmpeg_wins(self):
        with patch.object(ab.shutil, "which", side_effect=lambda c: f"/usr/bin/{c}"):
            ok, msg, fixed = ab.ensure_ffmpeg()
            self.assertTrue(ok)
            self.assertFalse(fixed)
            self.assertEqual(ab.BIN["ffmpeg"], "/usr/bin/ffmpeg")
            self.assertEqual(ab.BIN["ffprobe"], "/usr/bin/ffprobe")

    def test_falls_back_to_imageio_bundle(self):
        fake_mod = types.SimpleNamespace(get_ffmpeg_exe=lambda: "/fake/ffmpeg-bin")
        with patch.object(ab.shutil, "which", return_value=None), \
             patch.object(ab, "ensure_pip", return_value=(True, "installed", True)), \
             patch.dict(sys.modules, {"imageio_ffmpeg": fake_mod}):
            # importlib.import_module("imageio_ffmpeg") is bypassed — ensure_ffmpeg
            # does `import imageio_ffmpeg` directly, which hits sys.modules.
            ok, msg, fixed = ab.ensure_ffmpeg()
            self.assertTrue(ok)
            self.assertTrue(fixed)
            self.assertEqual(ab.BIN["ffmpeg"], "/fake/ffmpeg-bin")
            self.assertIsNone(ab.BIN["ffprobe"])


class TestFreeWebDetection(unittest.TestCase):
    def test_detects(self):
        wf = {"nodes": [
            {"type": "gen-script", "data": {"model": "free-web:chatgpt_go"}},
            {"type": "tts", "data": {"provider": "edge"}},
        ]}
        self.assertTrue(ab._workflow_uses_free_web(wf))

    def test_ignores_regular(self):
        wf = {"nodes": [{"type": "tts", "data": {"provider": "edge"}}]}
        self.assertFalse(ab._workflow_uses_free_web(wf))


class TestBootstrapWorkflow(unittest.TestCase):
    def test_clone_short_pulls_ytdlp_and_ffmpeg(self):
        calls = []

        def fake_pip(imp, pip_name):
            calls.append(pip_name)
            return True, f"{pip_name} auto-installed", True

        with patch.object(ab, "ensure_pip", side_effect=fake_pip), \
             patch.object(ab, "ensure_ffmpeg", return_value=(True, "ok", False)):
            report = ab.bootstrap_workflow({"nodes": [{"type": "clone-short"}]})
        self.assertIn("yt-dlp", calls)
        self.assertTrue(any("yt-dlp" in f for f in report["fixed"]))
        self.assertEqual(report["failed"], [])

    def test_agent_started_for_free_web(self):
        with patch.object(ab, "ensure_pip", return_value=(True, "ok", False)), \
             patch.object(ab, "ensure_ffmpeg", return_value=(True, "ok", False)), \
             patch.object(ab, "ensure_agent", return_value=(True, "agent auto-started", True)) as ea:
            report = ab.bootstrap_workflow(
                {"nodes": [{"type": "gen-image", "data": {"model": "free-web:gemini_web"}}]})
            ea.assert_called_once()
            self.assertTrue(any("agent" in f for f in report["fixed"]))

    def test_no_agent_for_regular_models(self):
        with patch.object(ab, "ensure_pip", return_value=(True, "ok", False)), \
             patch.object(ab, "ensure_ffmpeg", return_value=(True, "ok", False)), \
             patch.object(ab, "ensure_agent") as ea:
            ab.bootstrap_workflow({"nodes": [{"type": "gen-image", "data": {"model": "pollinations"}}]})
            ea.assert_not_called()

    def test_failed_fix_recorded(self):
        with patch.object(ab, "ensure_pip", return_value=(False, "pip failed", False)), \
             patch.object(ab, "ensure_ffmpeg", return_value=(False, "no ffmpeg", False)):
            report = ab.bootstrap_workflow({"nodes": [{"type": "clone-short"}]})
            self.assertTrue(any("yt-dlp" in f for f in report["failed"]))
            self.assertTrue(any("ffmpeg" in f for f in report["failed"]))


class TestProbeFallback(unittest.TestCase):
    """reference_clone.probe must work when ffprobe is missing (ffmpeg -i parse)."""

    def test_ffmpeg_i_parsing(self):
        from src.backend import reference_clone as rc
        fake_log = (
            "Duration: 00:00:06.50, start: 0.000000, bitrate: 1000 kb/s\n"
            "  Stream #0:0: Video: h264, yuv420p, 640x360 [SAR 1:1 DAR 16:9], 30 fps, 30 tbr\n"
        )

        class R:
            returncode = 1
            stdout = ""
            stderr = fake_log

        with patch.object(rc, "_ffprobe", return_value=None), \
             patch.object(rc, "_ffmpeg", return_value="/fake/ffmpeg"), \
             patch.object(rc, "_run", return_value=R()):
            dur, fps, w, h = rc.probe("/fake/ref.mp4")
        self.assertAlmostEqual(dur, 6.5)
        self.assertEqual((w, h), (640, 360))
        self.assertEqual(fps, 30.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
