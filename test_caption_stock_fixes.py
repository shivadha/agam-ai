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


if __name__ == "__main__":
    unittest.main(verbosity=2)
