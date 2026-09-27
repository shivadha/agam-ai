"""Regression tests for the 2026-09-27 short-video quality fixes.

Covers the issues visible in the user's generated short:
1. Caption lines breaking hyphenated compounds ("LIVE" / "-ACTION", "SPIN" / "-OFF").
2. Karaoke word events overlapping -> stacked duplicate caption lines.
3. Stock-image title validation matching substrings ("now" matching "NOW ON",
   "ice" matching "meeting") -> irrelevant photos (soldiers, meeting room,
   Lt. Gov graphic) for a Gotham/Mr. Freeze narration.
"""
import io
import os
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.backend import video_assembler as va
from src.backend import image_gen as ig


def _parse_dialogues(ass_path):
    """Return [(start_sec, end_sec, visible_text)] for each Dialogue event."""
    out = []

    def to_sec(ts):
        h, m, s = ts.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    with open(ass_path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"Dialogue: 0,([^,]+),([^,]+),Cap,,0,0,0,,(.*)$", line.rstrip("\n"))
            if m:
                vis = re.sub(r"\{\\[^}]*\}", "", m.group(3))
                out.append((to_sec(m.group(1)), to_sec(m.group(2)), vis))
    return out


def _word_events(text):
    """Build caption_events like the assembler does, with whisper-style
    slightly-overlapping word timings (even words run 60ms into the next)."""
    events = []
    t = 0.0
    for i, w in enumerate(text.split()):
        dur = 0.28 + (i % 3) * 0.05
        s = round(t, 2)
        e = round(t + dur + (0.06 if i % 2 == 0 else 0.0), 2)
        events.append(([w], 0, s, e))
        t += dur
    return events


class TestCaptionAss(unittest.TestCase):
    def test_no_hyphen_dangle_and_lines_fit(self):
        events = _word_events(
            "Stuart Bloom stumbles into live-action Gotham. "
            "Eric Allen Kramer is Mr. Freeze. He launches a giant icy bowling ball.")
        ass = "/tmp/test_fix_cap.ass"
        self.assertTrue(va.build_caption_ass(events, ass))
        dialogs = _parse_dialogues(ass)
        self.assertTrue(dialogs)
        for _s, _e, vis in dialogs:
            # No dangling "-XXX" line starts from a mid-word hyphen break.
            self.assertIsNone(
                re.search(r"(^|\s)-[A-Za-z]", vis),
                f"dangling hyphen in caption line: {vis!r}")
            # Every line fits the frame without libass rewrapping it.
            self.assertLessEqual(len(vis), va._MAX_LINE_CHARS,
                                 f"caption line too long ({len(vis)}): {vis!r}")
        # The compound survives on one line with a non-breaking hyphen.
        whole = " ".join(v for _, _, v in dialogs)
        self.assertIn("LIVE\u2011ACTION", whole)

    def test_no_overlapping_word_events(self):
        events = _word_events(
            "Suddenly Andy Writings appears. He is the Golden Age Flash. "
            "Speed blurs the dark city streets.")
        ass = "/tmp/test_fix_cap2.ass"
        va.build_caption_ass(events, ass)
        dialogs = _parse_dialogues(ass)
        self.assertTrue(len(dialogs) > 1)
        for (s1, e1, _), (s2, _e2, _) in zip(dialogs, dialogs[1:]):
            self.assertLessEqual(
                e1, s2 + 1e-9,
                f"overlapping karaoke events {s1:.2f}-{e1:.2f} vs {s2:.2f} "
                "(renders as stacked duplicate lines)")

    def test_sanitize_keeps_plain_hyphens_outside_words(self):
        # A leading dash (dialogue "- go!") must stay a normal hyphen.
        self.assertEqual(va._sanitize_caption_word("-"), "-")
        self.assertEqual(va._sanitize_caption_word("live-action"), "live\u2011action")
        self.assertEqual(va._sanitize_caption_word("{bad}"), "(bad)")


class _FakeResp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen_factory(api_pages, download_bytes):
    def _fake(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        if "commons.wikimedia.org/w/api.php" in url:
            import json as _json
            return _FakeResp(_json.dumps(api_pages).encode())
        return _FakeResp(download_bytes)
    return _fake


class TestStockValidation(unittest.TestCase):
    def test_rejects_substring_title_match(self):
        # The exact failure from the user's video: query tokens "comment"/"now"
        # matched the Commons file "Lt. Gov. Brian Calley is NOW ON Medium"
        # via substring ("now" in "NOW ON") -> wrong photo burned into the short.
        pages = {"query": {"pages": {"1": {
            "title": "File:Lt. Gov. Brian Calley is NOW ON Medium.jpg",
            "imageinfo": [{"url": "https://upload.wikimedia.org/x/calley.jpg"}]}}}}
        out = "/tmp/test_fix_stock.jpg"
        if os.path.exists(out):
            os.remove(out)
        with patch("urllib.request.urlopen",
                   side_effect=_fake_urlopen_factory(pages, b"x" * 20000)):
            self.assertFalse(ig._fetch_topic_stock_image(
                "comment now subscribe button", 1080, 1920, out, topic=""))
        self.assertFalse(os.path.exists(out))

    def test_accepts_whole_word_title_match(self):
        pages = {"query": {"pages": {"1": {
            "title": "File:Gotham City skyline at night.jpg",
            "imageinfo": [{"url": "https://upload.wikimedia.org/x/gotham.jpg"}]}}}}
        out = "/tmp/test_fix_stock2.jpg"
        if os.path.exists(out):
            os.remove(out)
        with patch("urllib.request.urlopen",
                   side_effect=_fake_urlopen_factory(pages, b"y" * 20000)):
            self.assertTrue(ig._fetch_topic_stock_image(
                "gotham city night", 1080, 1920, out, topic=""))
        self.assertTrue(os.path.exists(out) and os.path.getsize(out) == 20000)

    def test_lone_short_token_never_searched(self):
        # "ice" must not validate against "meeting"/"police" via substring.
        vocab = ig._title_vocab("File:Business meeting in office.jpg")
        self.assertNotIn("ice", vocab)  # whole-word tokenization, no substring


# ── prepare_video_shot: short AI clips must not visibly loop ──────────────
# moviepy is not installed in this sandbox, so stub the small surface that
# prepare_video_shot touches. Frames are solid colors that brighten
# monotonically with t: a loop would snap the brightness back to the start
# (the sawtooth seen in the user's video); play-once + drift never does.

import types as _types
import numpy as _np


class _FakeClip:
    def __init__(self, w=540, h=960, duration=1.0, rate=30.0, base=50.0):
        self.w, self.h, self.duration = w, h, duration
        self._rate, self._base = rate, base  # brightness units per second

    def _copy(self, **kw):
        c = _FakeClip(kw.get("w", self.w), kw.get("h", self.h),
                      kw.get("duration", self.duration),
                      kw.get("rate", self._rate), kw.get("base", self._base))
        return c

    def resized(self, *a, **k):
        c = self._copy()
        if "height" in k:
            s = k["height"] / self.h
            c.w, c.h = self.w * s, k["height"]
        elif "width" in k:
            s = k["width"] / self.w
            c.w, c.h = k["width"], self.h * s
        elif a and isinstance(a[0], (int, float)):
            c.w, c.h = self.w * a[0], self.h * a[0]
        return c

    def cropped(self, x_center=None, y_center=None, width=None, height=None):
        return self._copy(w=width or self.w, h=height or self.h)

    def subclipped(self, a, b):
        return self._copy(duration=b - a)

    def with_duration(self, d):
        return self._copy(duration=d)

    def without_audio(self):
        return self

    def get_frame(self, t):
        v = int(min(255, self._base + self._rate * max(0.0, t)))
        return _np.full((int(self.h), int(self.w), 3), v, dtype=_np.uint8)


class _FakeConcat(_FakeClip):
    def __init__(self, clips):
        self._clips = clips
        super().__init__(w=clips[0].w, h=clips[0].h,
                         duration=sum(c.duration for c in clips))

    def get_frame(self, t):
        acc = 0.0
        for c in self._clips:
            if t < acc + c.duration:
                return c.get_frame(t - acc)
            acc += c.duration
        return self._clips[-1].get_frame(self._clips[-1].duration - 1e-3)


def _install_fake_moviepy(video_duration):
    fake = _types.ModuleType("moviepy")
    fake.VideoFileClip = lambda path: _FakeClip(w=640, h=960,
                                                duration=video_duration,
                                                rate=60.0, base=40.0)
    fake.ColorClip = lambda *a, **k: _FakeClip(duration=k.get("duration", 1.0),
                                              rate=0.0, base=0.0)
    fake.concatenate_videoclips = lambda clips, method="compose": _FakeConcat(clips)
    sys.modules["moviepy"] = fake
    return fake


def _frame_diffs(clip, upto, step=0.2):
    from PIL import Image as _PILImage, ImageChops as _IC
    f0 = _PILImage.fromarray(clip.get_frame(0)).convert("L")
    diffs = []
    t = 0.0
    while t <= upto + 1e-9:
        f = _PILImage.fromarray(clip.get_frame(t)).convert("L")
        h = _IC.difference(f0, f).histogram()
        diffs.append(sum(i * c for i, c in enumerate(h)) / sum(h))
        t += step
    return diffs


class TestPrepareVideoShot(unittest.TestCase):
    def test_short_clip_plays_once_then_drifts_no_loop(self):
        # 1.0s AI clip filling a 3.4s shot: old code vfx.Loop'ed it (visible
        # 1s snap-back repeat); new code plays once + drifts on last frame.
        _install_fake_moviepy(video_duration=1.0)
        tail_calls = []

        def fake_drift(path, dur, w, h, effect):
            tail_calls.append((dur, effect))
            self.assertTrue(os.path.exists(path))  # last-frame PNG was written
            return _FakeClip(w=w, h=h, duration=dur, rate=8.0, base=100.0)

        with patch.object(va, "create_advanced_motion_effect", side_effect=fake_drift):
            out = va.prepare_video_shot("fake.mp4", 3.4, 1080, 1920)
        self.assertEqual(len(tail_calls), 1)
        self.assertAlmostEqual(tail_calls[0][0], 2.4, places=6)
        self.assertAlmostEqual(out.duration, 3.4, places=6)

        diffs = _frame_diffs(out, 3.3)
        # Once the picture has clearly moved on, it must never snap back to
        # (near) the start frame — that snap-back IS the loop glitch.
        moved = next(i for i, d in enumerate(diffs) if d > 8.0)
        for d in diffs[moved:]:
            self.assertGreater(d, 3.0,
                               f"frame snapped back toward start (loop glitch): {diffs}")

    def test_long_clip_is_trimmed_not_extended(self):
        _install_fake_moviepy(video_duration=5.0)
        with patch.object(va, "create_advanced_motion_effect") as drift:
            out = va.prepare_video_shot("fake.mp4", 3.4, 1080, 1920)
        drift.assert_not_called()
        self.assertAlmostEqual(out.duration, 3.4, places=6)

    def test_broken_video_falls_back_without_crash(self):
        fake = _install_fake_moviepy(video_duration=1.0)
        fake.VideoFileClip = lambda path: (_ for _ in ()).throw(RuntimeError("nope"))
        out = va.prepare_video_shot("fake.mp4", 3.4, 1080, 1920)
        self.assertAlmostEqual(out.duration, 3.4, places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
