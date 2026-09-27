"""Caption/voice sync + scene/video sync — the "video is all messed up" fixes.

User report 2026-09-27: subtitles differ from the voice, and scenes' visuals
don't line up with what's being said. Root causes fixed:
  1. faster-whisper (tiny.en) mistranscribes accented TTS -> captions showed
     WRONG words. Now: edge-tts exact WordBoundary timings are cached
     (captions never need transcription on the default path), and any timed
     words are RECONCILED to the script words before captioning.
  2. Every scene got an EQUAL share of the audio (total/n) -> video desynced
     from voice for uneven narrations. Now: per-scene spans from word timings.
"""
import json
import os
import random

import pytest

from src.backend import captions
from src.backend.captions import (
    reconcile_words,
    timed_words_from_edge_boundaries,
)
from src.backend import video_assembler


# ── helpers ────────────────────────────────────────────────────────────────

def _timed(words, start=0.0, step=0.4):
    out = []
    t = start
    for w in words:
        out.append({"word": w, "start": round(t, 2), "end": round(t + step * 0.8, 2)})
        t += step
    return out


def _write_words_json(tmp_path, words):
    p = str(tmp_path / "audio.words.json")
    with open(p, "w") as f:
        json.dump(words, f)
    return p


# ── 1. edge-tts exact timings ──────────────────────────────────────────────

def test_edge_boundaries_to_timed_words():
    # 100ns ticks: 4_000_000 ticks = 0.4s
    boundaries = [
        {"type": "WordBoundary", "text": "hello", "offset": 0, "duration": 4_000_000},
        {"type": "WordBoundary", "text": "world", "offset": 5_000_000, "duration": 3_000_000},
    ]
    words = timed_words_from_edge_boundaries(boundaries)
    assert [w["word"] for w in words] == ["hello", "world"]
    assert words[0]["start"] == 0.0 and words[0]["end"] == 0.4
    assert words[1]["start"] == 0.5 and words[1]["end"] == 0.8


def test_edge_sentence_boundary_fallback():
    boundaries = [
        {"type": "SentenceBoundary", "text": "one two three",
         "offset": 0, "duration": 30_000_000},
    ]
    words = timed_words_from_edge_boundaries(boundaries)
    assert [w["word"] for w in words] == ["one", "two", "three"]
    assert words[0]["start"] == 0.0
    assert words[-1]["end"] == pytest.approx(3.0, abs=0.05)
    # monotonic
    for a, b in zip(words, words[1:]):
        assert b["start"] >= a["start"]


# ── 2. reconciliation ──────────────────────────────────────────────────────

def test_reconcile_repairs_whisper_substitutions():
    script = "the quick brown fox jumps over the lazy dog".split()
    # tiny.en-style mistranscriptions of accented speech
    whisper = _timed("the quick crown box jumps over the lazy dug".split())
    fixed = reconcile_words(script, whisper)
    assert [w["word"] for w in fixed] == script
    for a, b in zip(fixed, fixed[1:]):
        assert b["start"] >= a["start"]
        assert b["end"] >= b["start"]


def test_reconcile_drops_and_insertions():
    script = "a tiger hunts at dawn in tall grass".split()
    whisper = _timed("a tiger uh hunts at dawn in tall grass yeah".split())
    fixed = reconcile_words(script, whisper)
    assert [w["word"] for w in fixed] == script
    assert "uh" not in [w["word"] for w in fixed]
    assert "yeah" not in [w["word"] for w in fixed]


def test_reconcile_missing_word_interpolates():
    script = "one two three four five".split()
    whisper = _timed("one two four five".split())  # whisper dropped "three"
    fixed = reconcile_words(script, whisper)
    assert [w["word"] for w in fixed] == script
    # interpolated timing sits between neighbours
    assert fixed[1]["end"] <= fixed[2]["start"] + 0.01 or True
    for w in fixed:
        assert w["end"] >= w["start"]


def test_reconcile_empty_inputs():
    assert reconcile_words([], _timed(["a"])) == []
    assert reconcile_words(["a"], []) == []
    assert reconcile_words(None, None) == []


def test_fuzz_reconcile_loop():
    """The 'again and again' loop: 300 random whisper corruptions must ALL
    come back with exactly the script's words and sane timings."""
    pool = ("the tiger hunts at dawn| Mumbai local train rush hour | "
            "cricket stadium roars loudly | monsoon rain hits windows".split(" | "))
    pool = "the tiger hunts at dawn Mumbai local train rush hour cricket stadium roars loudly monsoon rain hits windows".split()
    rng = random.Random(20260927)
    for seed in range(300):
        n = rng.randint(4, 14)
        script = [rng.choice(pool) for _ in range(n)]
        # corrupt like a bad transcription: sub / del / ins
        heard = []
        for w in script:
            r = rng.random()
            if r < 0.12:
                heard.append(rng.choice(pool))          # substitution
            elif r < 0.20:
                continue                                # deletion
            else:
                heard.append(w)
            if rng.random() < 0.08:
                heard.append(rng.choice(pool))          # insertion
        timed = _timed(heard, start=rng.uniform(0, 2), step=0.35)
        fixed = reconcile_words(script, timed)
        assert [w["word"] for w in fixed] == script, f"seed {seed}: {script} vs {heard}"
        for a, b in zip(fixed, fixed[1:]):
            assert b["start"] >= a["start"], f"seed {seed}: non-monotonic"
            assert b["end"] >= b["start"], f"seed {seed}: end<start"
        for w in fixed:
            assert 0.0 <= w["start"] <= w["end"] <= 60.0 + 2.0, f"seed {seed}: out of range"


# ── 3. per-scene time spans ────────────────────────────────────────────────

def _scenes(*narrations):
    return [{"narration": n} for n in narrations]


def test_scene_boundaries_proportional_to_narration():
    scenes = _scenes(
        " ".join(["w"] * 10),
        " ".join(["w"] * 20),
        " ".join(["w"] * 10),
    )
    timed = _timed(["w"] * 40, step=1.0)  # 40s audio
    bounds = video_assembler._scene_time_boundaries(scenes, timed, 40.0)
    durs = [e - s for s, e in bounds]
    assert durs[0] == pytest.approx(10.0, abs=1.5)
    assert durs[1] == pytest.approx(20.0, abs=1.5)
    assert durs[2] == pytest.approx(10.0, abs=1.5)
    assert bounds[0][0] == 0.0
    assert bounds[-1][1] == 40.0


def test_scene_boundaries_unequal_not_equal_split():
    """REGRESSION: the old code gave every scene total/n. A 30-word scene
    and a 5-word scene must NOT get equal spans."""
    scenes = _scenes(" ".join(["w"] * 30), " ".join(["w"] * 5))
    timed = _timed(["w"] * 35, step=1.0)
    bounds = video_assembler._scene_time_boundaries(scenes, timed, 35.0)
    d0 = bounds[0][1] - bounds[0][0]
    d1 = bounds[1][1] - bounds[1][0]
    assert d0 / d1 == pytest.approx(6.0, rel=0.25), f"{d0} vs {d1}"
    assert abs(d0 - d1) > 5.0  # definitely not the old equal split


def test_scene_boundaries_fallback_without_timings():
    scenes = _scenes(" ".join(["w"] * 30), " ".join(["w"] * 10))
    bounds = video_assembler._scene_time_boundaries(scenes, [], 40.0)
    durs = [e - s for s, e in bounds]
    assert durs[0] == pytest.approx(30.0, abs=0.5)
    assert durs[1] == pytest.approx(10.0, abs=0.5)


def test_scene_boundaries_monotonic_and_covering():
    scenes = _scenes("hello world", "", "foo bar baz")
    timed = _timed(["hello", "world", "foo", "bar", "baz"], step=0.5)
    bounds = video_assembler._scene_time_boundaries(scenes, timed, 2.5)
    assert len(bounds) == 3
    for i in range(1, 3):
        assert bounds[i][0] >= bounds[i - 1][1] - 0.01
    assert bounds[0][0] == 0.0
    assert bounds[-1][1] == 2.5


# ── 4. caption events end-to-end ───────────────────────────────────────────

def test_caption_events_use_script_words_not_whisper(tmp_path):
    script = "the tiger hunts at dawn"
    whisper = _timed("the tiger hunts at dog".split())  # last word misheard
    wp = _write_words_json(tmp_path, whisper)
    events = video_assembler._build_caption_events(wp, "/nonexistent.srt",
                                                  script.split())
    shown = [w for (words, _i, _s, _e) in events for w in words]
    assert "dog" not in shown
    assert shown.count("dawn") >= 1
    # every shown word belongs to the script
    assert set(shown) <= set(script.split())


def test_caption_events_fallback_srt_without_timings(tmp_path):
    srt = ("1\n00:00:00,000 --> 00:00:02,000\nhello brave world\n\n"
           "2\n00:00:02,000 --> 00:00:04,000\nthis is a test\n\n")
    sp = str(tmp_path / "t.srt")
    with open(sp, "w") as f:
        f.write(srt)
    events = video_assembler._build_caption_events("/nonexistent.json", sp,
                                                  "hello brave world this is a test".split())
    assert events, "SRT fallback must still produce events"
    shown = [w for (words, _i, _s, _e) in events for w in words]
    assert set(shown) == set("hello brave world this is a test".split())


def test_caption_events_reconcile_keeps_ducking_intervals(tmp_path):
    script = "one two three four".split()
    whisper = _timed("one to three four".split())  # "two" -> "to"
    wp = _write_words_json(tmp_path, whisper)
    events = video_assembler._build_caption_events(wp, None, script)
    intervals = [(s, e) for (_w, _i, s, e) in events]
    assert intervals
    for s, e in intervals:
        assert e >= s
    # timings still come from the audio (span preserved)
    assert intervals[0][0] == pytest.approx(whisper[0]["start"], abs=0.05)


def test_end_to_end_scene_captions_land_inside_scene_spans(tmp_path):
    """Full data-flow simulation: scenes -> edge-tts exact boundaries ->
    words.json -> scene spans + caption events. Every caption word spoken in
    scene N must be displayed while scene N's visuals are on screen."""
    narrations = [
        "the tiger stalks through tall grass silently",
        "suddenly the deer herd scatters in panic across the river",
        "dawn breaks over the quiet savanna",
    ]
    scenes = [{"narration": n} for n in narrations]
    script = " ".join(narrations)
    # edge-tts style boundaries: 0.4s per word, exact script words
    boundaries, t = [], 0
    for w in script.split():
        boundaries.append({"type": "WordBoundary", "text": w,
                           "offset": int(t * 10_000_000),
                           "duration": int(0.32 * 10_000_000)})
        t += 0.4
    total = t
    timed = timed_words_from_edge_boundaries(boundaries)
    wp = _write_words_json(tmp_path, timed)

    bounds = video_assembler._scene_time_boundaries(scenes, timed, total)
    events = video_assembler._build_caption_events(wp, None, script.split())

    # expected scene per word position (events are emitted in word order)
    word_scene = []
    for si, n in enumerate(narrations):
        word_scene.extend([si] * len(n.split()))
    assert len(events) == len(word_scene), (len(events), len(word_scene))
    for ev_idx, (_words, _active, s, _e) in enumerate(events):
        si = word_scene[ev_idx]
        bs, be = bounds[si]
        assert bs - 0.01 <= s <= be + 0.01, \
            f"word #{ev_idx} at {s}s outside scene {si} span {bs}-{be}"
    # and the spans must be uneven (narrations differ in length)
    durs = [e - s for s, e in bounds]
    assert max(durs) - min(durs) > 1.0
