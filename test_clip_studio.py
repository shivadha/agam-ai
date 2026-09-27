"""Tests for the Clip Studio backend (src/backend/studio.py).

Sandbox-safe: no ffmpeg / yt-dlp / moviepy needed — subprocess-heavy paths
are not executed; clip_fn is injected; command builders are pure.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.backend import studio


class TestYoutubeUrlValidator(unittest.TestCase):
    def test_accepts_watch(self):
        self.assertTrue(studio.is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))

    def test_accepts_short_variants(self):
        self.assertTrue(studio.is_youtube_url("https://youtu.be/dQw4w9WgXcQ"))
        self.assertTrue(studio.is_youtube_url("https://www.youtube.com/shorts/abc123"))
        self.assertTrue(studio.is_youtube_url("https://m.youtube.com/watch?v=abc123"))
        self.assertTrue(studio.is_youtube_url("http://youtube.com/live/xyz"))
        self.assertTrue(studio.is_youtube_url("https://www.youtube.com/embed/xyz"))

    def test_rejects_non_youtube(self):
        self.assertFalse(studio.is_youtube_url("https://vimeo.com/12345"))
        self.assertFalse(studio.is_youtube_url("https://example.com/watch?v=abc"))
        self.assertFalse(studio.is_youtube_url(""))
        self.assertFalse(studio.is_youtube_url(None))
        self.assertFalse(studio.is_youtube_url("javascript:alert(1)"))
        self.assertFalse(studio.is_youtube_url("https://fakeyoutube.com/watch?v=abc"))


class TestPickRandomWindows(unittest.TestCase):
    def test_n_windows_within_duration(self):
        wins = studio.pick_random_windows(300.0, num_clips=3, min_sec=15, max_sec=45, seed=7)
        self.assertEqual(len(wins), 3)
        for s, e in wins:
            self.assertGreaterEqual(s, 0)
            self.assertLessEqual(e, 300.0)
            self.assertGreaterEqual(e - s, 15.0)
            self.assertLessEqual(e - s, 45.0 + 1e-9)

    def test_non_overlapping(self):
        wins = studio.pick_random_windows(600.0, num_clips=5, min_sec=20, max_sec=40, seed=42)
        ordered = sorted(wins)
        for (s1, e1), (s2, e2) in zip(ordered, ordered[1:]):
            self.assertLessEqual(e1, s2, f"overlap: {(s1, e1)} vs {(s2, e2)}")

    def test_deterministic_with_seed(self):
        a = studio.pick_random_windows(300.0, 3, 15, 45, seed=1234)
        b = studio.pick_random_windows(300.0, 3, 15, 45, seed=1234)
        self.assertEqual(a, b)

    def test_impossible_raises(self):
        with self.assertRaises(ValueError):
            studio.pick_random_windows(10.0, num_clips=3, min_sec=15, max_sec=45)


class TestRenderRandomClips(unittest.TestCase):
    def _fake_clip_ok(self, calls):
        def _fn(video_path, start, end, out_path):
            calls.append((start, end))
            open(out_path, "wb").write(b"fake")
        return _fn

    def test_renders_n_clips(self):
        calls = []
        with tempfile.TemporaryDirectory() as td:
            res = studio.render_random_clips("/fake/in.mp4", 300.0, 3, 15, 45, td,
                                             seed=99, clip_fn=self._fake_clip_ok(calls))
        self.assertEqual(len(res["clips"]), 3)
        self.assertEqual(len(calls), 3)
        for c in res["clips"]:
            self.assertTrue(c["file"].endswith(".mp4"))
            self.assertLess(c["start_sec"], c["end_sec"])

    def test_retry_on_no_speech(self):
        # First 4 windows have no speech -> repicked; still ends with N clips.
        calls = []

        def _fn(video_path, start, end, out_path):
            calls.append((start, end))
            if len(calls) <= 4:
                raise ValueError("no speech found in that range -- can't caption it")
            open(out_path, "wb").write(b"fake")

        with tempfile.TemporaryDirectory() as td:
            res = studio.render_random_clips("/fake/in.mp4", 600.0, 3, 15, 45, td,
                                             seed=5, clip_fn=_fn)
        self.assertEqual(len(res["clips"]), 3)
        self.assertGreater(len(calls), 3)          # repicks happened
        self.assertEqual(res["skipped"], 4)        # silent windows counted

    def test_real_errors_propagate(self):
        def _fn(video_path, start, end, out_path):
            raise RuntimeError("ffmpeg exploded")

        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(RuntimeError):
                studio.render_random_clips("/fake/in.mp4", 300.0, 2, 15, 45, td,
                                           seed=1, clip_fn=_fn)


class TestRenderSingleClip(unittest.TestCase):
    def test_exact_window(self):
        seen = []

        def _fn(vp, s, e, out):
            seen.append((s, e))
            open(out, "wb").write(b"x")

        with tempfile.TemporaryDirectory() as td:
            res = studio.render_single_clip("/fake/in.mp4", 12.5, 42.5, td, clip_fn=_fn)
        self.assertEqual(seen, [(12.5, 42.5)])
        self.assertEqual(res["start_sec"], 12.5)
        self.assertEqual(res["end_sec"], 42.5)

    def test_bad_window_raises(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                studio.render_single_clip("/fake/in.mp4", 40, 10, td, clip_fn=lambda *a: None)


class TestMusicMixCmd(unittest.TestCase):
    def test_with_audio(self):
        cmd = studio.build_music_mix_cmd("in.mp4", "song.mp3", "out.mp4",
                                         volume=0.25, has_audio=True)
        s = " ".join(cmd)
        self.assertIn("-c:v copy", s)
        self.assertIn("-shortest", s)
        self.assertIn("amix=inputs=2", s)
        self.assertIn("volume=0.25", s)
        self.assertIn("-map", s)
        # music input is looped so it covers the whole video
        self.assertIn("-stream_loop", s)

    def test_without_audio(self):
        cmd = studio.build_music_mix_cmd("in.mp4", "song.mp3", "out.mp4",
                                         volume=0.5, has_audio=False)
        s = " ".join(cmd)
        self.assertIn("-c:v copy", s)
        self.assertIn("-shortest", s)
        self.assertNotIn("amix", s)
        self.assertIn("volume=0.5", s)
        self.assertIn("-map", s)

    def test_volume_clamped(self):
        cmd = studio.build_music_mix_cmd("in.mp4", "song.mp3", "out.mp4",
                                         volume=99, has_audio=True)
        self.assertIn("volume=1.0", " ".join(cmd))


if __name__ == "__main__":
    unittest.main(verbosity=2)
