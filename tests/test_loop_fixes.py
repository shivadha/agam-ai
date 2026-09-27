"""Regression tests for the Style Lab / motion loop-test fixes.

Covers the bugs found by rendering synthetic reference shorts and
verifying the analyzer + clipper output frame-by-frame:
- scene-cut threshold catches cuts on textured content (not just luma jumps)
- caption-zone numpy detector works on busy backgrounds + negative control
- music bed detected without any transcript
- style thumbs don't produce garbage relpaths when work_dir is outside OUTPUT_DIR
- zoom search can't invent phantom zooms on pan/periodic content (dual gate)
- phase-correlation sign: content moving left == camera panning right
- aliasing sanity cap: huge spurious shifts zero out, not partially kept
- ASS captions: hyphenated compounds never break, no line starts with '-'
"""
import json
import os
import re
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.backend import reference_clone as rc
from src.backend import style_analyzer as sa
from src.backend import clipper


def _run(cmd):
    subprocess.run(cmd, capture_output=True, check=True)


def textured(n, hue, dur=3.0, w=1080, h=1920, caption=None):
    """One textured scene; even n zooms in, odd n is static.

    Alternating dark/bright gives unambiguous hard cuts (like real
    scene changes) on top of the texture."""
    bright = "eq=brightness=0.35" if n % 2 else "eq=brightness=-0.35"
    vf = (f"testsrc2=s={w}x{h}:r=30:d={dur},hue=h={hue},{bright},"
          f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
          f"text='SCENE{n}':fontsize=120:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2")
    if n % 2 == 0:
        vf += (",zoompan=z='1+0.25*on/90':x='iw/2-(iw/zoom/2)':"
               "y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30")
    return vf


def make_ref(path, caption=False):
    segs = []
    tmp = os.path.dirname(path)
    # 180-degree hue jumps: unambiguous hard cuts for scene detection
    for i, hue in enumerate((0, 180, 90)):
        seg = os.path.join(tmp, f"lseg{i}.mp4")
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
              "-f", "lavfi", "-i", textured(i, hue),
              "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
              "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
              "-shortest", seg])
        segs.append(seg)
    if caption:  # burn a bottom caption into the middle scene
        cap = os.path.join(tmp, "lseg1c.mp4")
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", segs[1],
              "-vf", "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
                     "text='HELLO WORLD CAPTION HERE':fontsize=64:fontcolor=white:"
                     "x=(w-text_w)/2:y=h-160",
              "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy", cap])
        segs[1] = cap
    lst = os.path.join(tmp, "llist.txt")
    with open(lst, "w") as f:
        for s in segs:
            f.write(f"file '{s}'\n")
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
          "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", path])
    return path


# ── scene cuts ────────────────────────────────────────────────────────────

def test_cuts_found_on_textured_content(tmp_path):
    ref = make_ref(str(tmp_path / "ref.mp4"))
    shots = sa._detect_shots(ref, 9.0)
    cuts = [s[0] for s in shots[1:]]
    assert len(cuts) == 2, f"expected 2 cuts, got {cuts}"
    assert cuts[0] == pytest.approx(3.0, abs=0.4)
    assert cuts[1] == pytest.approx(6.0, abs=0.4)


# ── caption zone (numpy fallback, busy background) ────────────────────────

def test_caption_zone_busy_background(tmp_path):
    ref = make_ref(str(tmp_path / "ref.mp4"), caption=True)
    zone = sa._detect_caption_zone(ref, 9.0)
    assert zone["present"] is True, "caption missed on textured background"
    assert zone["zone"] == "bottom"


def test_caption_zone_negative(tmp_path):
    ref = make_ref(str(tmp_path / "nocap.mp4"), caption=False)
    zone = sa._detect_caption_zone(ref, 9.0)
    assert zone["present"] is False, f"false positive: {zone}"


# ── music bed without transcript ──────────────────────────────────────────

def test_music_bed_without_words(tmp_path):
    ref = make_ref(str(tmp_path / "ref.mp4"))
    assert sa._detect_music_bed(ref, [], duration=9.0) is True


# ── thumb path fallback ───────────────────────────────────────────────────

def test_thumb_paths_outside_output_dir(tmp_path):
    ref = make_ref(str(tmp_path / "ref.mp4"))
    work = str(tmp_path / "work")
    os.makedirs(work, exist_ok=True)
    thumbs = sa._style_thumbs(ref, [(0.0, 3.0)], work)
    assert len(thumbs) == 1
    assert os.path.isabs(thumbs[0]) or not thumbs[0].startswith("..")
    assert os.path.exists(thumbs[0])


# ── motion estimator ──────────────────────────────────────────────────────

def _pan_clip(path):
    # wider-than-9:16 source so a sliding crop is a true pan
    base = path.replace(".mp4", "_base.mp4")
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
          "-f", "lavfi", "-i", "testsrc2=s=1440x1920:r=30:d=3,hue=h=90",
          "-c:v", "libx264", "-pix_fmt", "yuv420p", base])
    # pan right: crop window slides right -> content moves left
    pan = path.replace(".mp4", "_pan.mp4")
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", base,
          "-vf", "crop=1080:1920:'360*n/90':0",
          "-c:v", "libx264", "-pix_fmt", "yuv420p", pan])
    return pan


def test_zoom_gate_no_phantom_on_pan(tmp_path):
    pan = _pan_clip(str(tmp_path / "base.mp4"))
    # flat zoom-score profile must not vote: no dolly-in/out invented
    import numpy as np
    f0 = rc._grab_frame(pan, 0.5)
    f1 = rc._grab_frame(pan, 0.83)
    s, score, s1 = rc._best_zoom(np.asarray(f0, dtype=np.float32), f1)
    assert not rc._zoom_trustworthy(score, s1), \
        f"phantom zoom accepted on pan content (s={s}, score={score:.2f})"
    assert rc.estimate_motion(pan, (0.0, 3.0)) == "pan-right"


def test_pan_sign_convention(tmp_path):
    pan = _pan_clip(str(tmp_path / "base2.mp4"))
    import numpy as np
    f0 = rc._grab_frame(pan, 0.5)
    f1 = rc._grab_frame(pan, 0.83)
    a = np.asarray(f0, dtype=np.float32)
    b = np.asarray(f1, dtype=np.float32)
    dx, _dy = rc._phase_shift(a, b)
    # crop window moves right -> content moves left -> dx negative
    assert dx < 0, f"sign wrong: content moves left, dx={dx}"


def test_aliasing_cap_zeroes_both_axes(tmp_path):
    # periodic grid: 2D phase aliases; the surviving axis must not
    # invent a phantom pan either.
    seg = str(tmp_path / "grid.mp4")
    vf = ("color=c=0x1a1a1a:s=640x360:r=25:d=2,"
          "drawgrid=w=iw/8:h=ih/8:t=4:c=0x707070,"
          "zoompan=z='1+0.6*on/50':x='iw/2-(iw/zoom/2)':"
          "y='ih/2-(ih/zoom/2)':d=1:s=640x360:fps=25")
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
          "-f", "lavfi", "-i", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p",
          seg])
    assert rc.estimate_motion(seg, (0.0, 2.0)) == "zoom-in"


def test_real_zoom_detected_via_peak_prominence(tmp_path):
    seg = str(tmp_path / "grid2.mp4")
    vf = ("color=c=0x1a1a1a:s=640x360:r=25:d=2,"
          "drawgrid=w=iw/8:h=ih/8:t=4:c=0x707070,"
          "zoompan=z='1+0.6*on/50':x='iw/2-(iw/zoom/2)':"
          "y='ih/2-(ih/zoom/2)':d=1:s=640x360:fps=25")
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
          "-f", "lavfi", "-i", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p",
          seg])
    assert sa._zoom_intensity(seg, (0.0, 2.0)) > 0.05


# ── captions ──────────────────────────────────────────────────────────────

def test_ass_hyphens_never_break(tmp_path):
    # "-ACTION" as a chunk-leading word (the transcriber case): it must be
    # reflowed, never rendered with a dangling hyphen at a line start.
    words = [
        {"word": "INTO", "start": 0.0, "end": 0.3},
        {"word": "LIVE-ACTION", "start": 0.3, "end": 0.6},
        {"word": "GOTHAM", "start": 0.6, "end": 0.9},
        {"word": "-ACTION", "start": 0.9, "end": 1.2},
        {"word": "HERO", "start": 1.2, "end": 1.5},
        {"word": "SAVES", "start": 1.5, "end": 1.8},
    ]
    ass = str(tmp_path / "t.ass")
    clipper._write_ass_karaoke(words, ass, max_words_per_line=3)
    text = open(ass, encoding="utf-8").read()
    assert "\u2011" in text  # U+2011 non-breaking hyphen present
    assert "-ACTION" not in text.replace("\u2011", "")  # no ASCII hyphen survives
    for line in text.splitlines():
        if line.startswith("Dialogue"):
            body = line.rsplit(",", 1)[-1]
            plain = re.sub(r"\{[^}]*\}", "", body)
            for chunk in plain.split(r"\N"):
                assert not chunk.startswith("-"), f"dangling hyphen: {chunk}"
                assert not chunk.startswith("\u2011"), f"dangling hyphen: {chunk}"
