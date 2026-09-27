"""Style Lab + Clone as-is + Clip DB — sandbox-safe tests.

No flask / moviepy / faster-whisper / network needed: backend functions are
called directly, transcription is stubbed, and ffmpeg (present in the
sandbox) does the rendering.
"""
import json
import os
import subprocess
import sys
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

# database.py imports werkzeug at module level; the sandbox has no flask
# stack, so stub just the password helpers it needs.
import types as _types

_werkzeug = _types.ModuleType("werkzeug")
_werkzeug_security = _types.ModuleType("werkzeug.security")
_werkzeug_security.generate_password_hash = lambda pw: "stub:" + str(pw)
_werkzeug_security.check_password_hash = lambda h, pw: h == "stub:" + str(pw)
_werkzeug.security = _werkzeug_security
sys.modules.setdefault("werkzeug", _werkzeug)
sys.modules.setdefault("werkzeug.security", _werkzeug_security)

from src.backend import clipper, style_analyzer  # noqa: E402
from src import database  # noqa: E402


def _run(cmd, **kw):
    kw.setdefault("capture_output", True)
    kw.setdefault("timeout", 300)
    r = subprocess.run(cmd, **kw)
    assert r.returncode == 0, f"ffmpeg failed: {(r.stderr or b'')[-500:]}"
    return r


def make_synthetic_ref(path):
    """6s reference short: static grid (0-2s), zoom-in grid (2-4s),
    black + white bottom caption (4-6s). All with a sine audio track."""
    tmp = os.path.dirname(path)
    segs = []
    # NOTE: zoompan's `zoom` variable does not accumulate with d=1 on video
    # input -- drive the zoom with the output frame counter `on` instead.
    # seg1/seg2 differ strongly in LUMA (dark vs mid-gray) so the hard cut
    # fires at the production scene threshold (0.35); both stay under luma
    # 200 so the caption-zone fallback isn't fooled.
    zoom = ("zoompan=z='1+0.6*on/50':x='iw/2-(iw/zoom/2)':"
            "y='ih/2-(ih/zoom/2)':d=1:s=640x360:fps=25")
    vf1 = ("color=c=0x1a1a1a:s=640x360:r=25:d=2,"
           "drawgrid=w=iw/8:h=ih/8:t=4:c=0x707070," + zoom)
    vf2 = ("color=c=0x8a8a8a:s=640x360:r=25:d=2,"
           "drawgrid=w=iw/8:h=ih/8:t=4:c=0x303030," + zoom)
    vf3 = ("color=c=black:s=640x360:r=25:d=2,drawtext=fontfile="
           "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
           "text='HELLO WORLD TEST CAPTION':fontsize=52:fontcolor=white:"
           "x=(w-text_w)/2:y=h-90")  # clearly inside the bottom third
    for i, vf in enumerate([vf1, vf2, vf3], 1):
        seg = os.path.join(tmp, f"seg{i}.mp4")
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
              "-f", "lavfi", "-i", vf,
              "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
              "-c:v", "libx264", "-pix_fmt", "yuv420p",
              "-c:a", "aac", "-shortest", seg])
        segs.append(seg)
    lst = os.path.join(tmp, "list.txt")
    with open(lst, "w") as f:
        for s in segs:
            f.write(f"file '{s}'\n")
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
          "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", path])
    return path


def fake_words(n=12, dur=6.0):
    """Evenly spaced fake word timings."""
    return [{"word": f"w{i}", "start": i * dur / n,
             "end": (i + 1) * dur / n} for i in range(n)]


# ── analyzer ────────────────────────────────────────────────────────────────

def test_analyze_short_synthetic(tmp_path):
    ref = make_synthetic_ref(str(tmp_path / "ref.mp4"))
    work = str(tmp_path / "work")
    profile = style_analyzer.analyze_short(ref, work_dir=work)

    assert profile["duration_s"] == pytest.approx(6.0, abs=0.3)
    # 2 hard cuts in 6s -> 20 cuts/min
    assert profile["pacing"]["cuts_per_min"] == pytest.approx(20.0, abs=5.0)
    assert len(profile["pacing"]["cut_timestamps"]) == 2
    assert profile["pacing"]["avg_shot_len_s"] == pytest.approx(2.0, abs=0.5)
    # 2 of 3 shots zoom in -> dominant zoom_in
    assert profile["motion"]["dominant"] == "zoom_in"
    zooms = [s["zoom_intensity"] for s in profile["motion"]["per_shot"]]
    assert any(z > 0.05 for z in zooms), f"no zoom measured: {zooms}"
    # white caption on black, bottom third (cv2 missing -> numpy fallback)
    assert profile["captions"]["present"] is True
    assert profile["captions"]["zone"] == "bottom"
    assert profile["captions"]["rel_height"] > 0
    # EDL has one entry per shot
    assert len(profile["edl"]) == len(profile["motion"]["per_shot"]) >= 3
    # thumbnails for the style card
    assert 1 <= len(profile["thumb_paths"]) <= 4
    for t in profile["thumb_paths"]:
        assert os.path.exists(os.path.join(
            style_analyzer.OUTPUT_DIR, t))


def test_map_edl_to_duration():
    edl = [
        {"start": 0.0, "end": 2.0, "duration": 2.0, "motion": "zoom_in",
         "zoom_intensity": 0.2, "word_count": 4},
        {"start": 2.0, "end": 6.0, "duration": 4.0, "motion": "static",
         "zoom_intensity": 0.0, "word_count": 8},
    ]
    mapped = style_analyzer.map_edl_to_duration(edl, 6.0, 12.0)
    assert len(mapped) == 2
    assert (mapped[0]["start"], mapped[0]["end"]) == (0.0, 4.0)
    assert (mapped[1]["start"], mapped[1]["end"]) == (4.0, 12.0)
    assert mapped[0]["motion"] == "zoom_in"  # motion preserved
    assert mapped[1]["duration"] == 8.0
    # degenerate inputs -> []
    assert style_analyzer.map_edl_to_duration([], 6.0, 12.0) == []
    assert style_analyzer.map_edl_to_duration(edl, 0.0, 12.0) == []


# ── clip DB ─────────────────────────────────────────────────────────────────

def test_clip_db_roundtrip(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database.init_db()

    profile = {"duration_s": 6.0, "pacing": {"cuts_per_min": 20.0}}
    sid = database.save_clip_style("Hormozi fast", "https://youtu.be/x",
                                   profile, thumb_path="studio/x.jpg")
    assert sid > 0
    styles = database.list_clip_styles()
    assert len(styles) == 1 and styles[0]["name"] == "Hormozi fast"
    assert json.loads(styles[0]["profile_json"])["pacing"]["cuts_per_min"] == 20.0
    assert database.get_clip_style(sid)["source_url"] == "https://youtu.be/x"

    cid = database.record_clip(
        source_video="studio/v.mp4", source_url="https://youtu.be/x",
        start_s=1.0, end_s=5.0, style_id=sid,
        output_path="studio/clips/c.mp4", thumb_path="studio/clips/c_thumb.jpg",
        kind="random", meta={"note": "hi"})
    clips = database.list_clips()
    assert len(clips) == 1
    assert clips[0]["style_name"] == "Hormozi fast"
    assert clips[0]["kind"] == "random"
    assert json.loads(database.get_clip(cid)["meta_json"])["note"] == "hi"

    # deleting the style NULLs the reference but keeps the clip row
    assert database.delete_clip_style(sid) is True
    assert database.list_clip_styles() == []
    clips = database.list_clips()
    assert len(clips) == 1 and clips[0]["style_id"] is None

    row = database.delete_clip(cid)
    assert row["output_path"] == "studio/clips/c.mp4"
    assert database.list_clips() == []
    assert database.delete_clip(99999) is None


# ── clipper style application ───────────────────────────────────────────────

def test_style_caption_params_defaults():
    p = clipper.style_caption_params(None)
    assert p == {"font_size": 76, "alignment": 2, "margin_v": 320,
                 "max_words_per_line": clipper._MAX_WORDS_PER_LINE}


def test_style_caption_params_top_zone():
    p = clipper.style_caption_params(
        {"captions": {"present": True, "zone": "top", "rel_height": 0.06},
         "words_per_caption": 2})
    assert p["alignment"] == 8      # ASS top-center
    assert p["margin_v"] == 80
    assert p["max_words_per_line"] == 2
    assert p["font_size"] > 76      # bigger than default: taller reference caps


def test_build_motion_filter_punchins():
    mf = clipper.build_motion_filter(
        {"pacing": {"cuts_per_min": 30, "avg_shot_len_s": 2.0},
         "zoom_intensity": 0.18}, 20.0, 25.0)
    assert "zoompan" in mf and "abs(sin" in mf
    # slow-cut reference -> no punch-ins
    assert clipper.build_motion_filter(
        {"pacing": {"cuts_per_min": 5}}, 20.0, 25.0) == ""
    assert clipper.build_motion_filter(None, 20.0, 25.0) == ""


def test_build_motion_filter_directed():
    mf = clipper.build_motion_filter(
        {"motion": "zoom_in", "zoom_intensity": 0.2}, 10.0, 25.0)
    assert "zoompan" in mf and "on/250" in mf  # zoom grows over the shot
    out = clipper.build_motion_filter(
        {"motion": "zoom_out", "zoom_intensity": 0.2}, 10.0, 25.0)
    assert "1-on/250" in out
    pan = clipper.build_motion_filter({"motion": "pan"}, 8.0, 25.0)
    assert "zoompan" in pan and "on/200" in pan
    assert clipper.build_motion_filter({"motion": "static"}, 10.0, 25.0) == ""


def _stub_transcribe(monkeypatch, words):
    monkeypatch.setattr(clipper, "transcribe_word_timings",
                        lambda _p: words)


def test_write_ass_karaoke_style_override(tmp_path):
    words = fake_words(6, 6.0)
    params = clipper.style_caption_params(
        {"captions": {"present": True, "zone": "top", "rel_height": 0.06},
         "words_per_caption": 2})
    ass = str(tmp_path / "styled.ass")
    clipper._write_ass_karaoke(words, ass, offset=0.0, **params)
    text = open(ass, encoding="utf-8").read()
    # Style line: ...,Alignment=8,...,MarginV=80 with scaled font
    assert f",{params['font_size']}," in text
    assert f",8,60,60,80,1" in text
    # 2 words per caption line -> 3 caption chunks -> 6 dialogue events
    assert text.count("Dialogue:") == 6


def test_make_clip_unchanged_without_profile(tmp_path, monkeypatch):
    """style_profile=None must build the exact historical -vf string."""
    _stub_transcribe(monkeypatch, fake_words())
    captured = {}

    import subprocess as _sp

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        out = cmd[-1]
        open(out, "wb").write(b"fake")
        return _sp.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(_sp, "run", fake_run)
    src = make_synthetic_ref(str(tmp_path / "src.mp4"))
    out = str(tmp_path / "out.mp4")
    clipper.make_clip(src, 0.5, 5.5, out, face_track=False,
                      style_profile=None)
    vf = captured["cmd"][captured["cmd"].index("-vf") + 1]
    assert vf.startswith("crop=ih*9/16:ih,scale=1080:1920,subtitles='")
    assert "sin(" not in vf  # no motion filter
    assert os.path.exists(out)


def test_make_clip_style_profile_renders(tmp_path, monkeypatch):
    """End-to-end ffmpeg render with punch-ins + top-zone captions."""
    _stub_transcribe(monkeypatch, fake_words(24, 6.0))
    src = make_synthetic_ref(str(tmp_path / "src.mp4"))
    out = str(tmp_path / "styled.mp4")
    profile = {
        "captions": {"present": True, "zone": "top", "rel_height": 0.06},
        "words_per_caption": 2,
        "pacing": {"cuts_per_min": 30, "avg_shot_len_s": 2.0},
        "zoom_intensity": 0.18,
    }
    clipper.make_clip(src, 0.0, 6.0, out, face_track=False,
                      style_profile=profile)
    assert os.path.exists(out) and os.path.getsize(out) > 1000
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,duration",
         "-of", "csv=p=0", out], capture_output=True, text=True)
    w, h, d = r.stdout.strip().split(",")
    assert (w, h) == ("1080", "1920")
    assert abs(float(d) - 6.0) < 0.6


def test_make_clip_music_bed_mix(tmp_path, monkeypatch):
    """music_bed + music_path duck-mixes the track under the clip."""
    _stub_transcribe(monkeypatch, fake_words(12, 6.0))
    src = make_synthetic_ref(str(tmp_path / "src.mp4"))
    music = str(tmp_path / "track.mp3")
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
          "-f", "lavfi", "-i", "sine=frequency=220:duration=6",
          "-c:a", "libmp3lame", music])
    out = str(tmp_path / "musical.mp4")
    clipper.make_clip(src, 0.0, 6.0, out, face_track=False,
                      style_profile={"music_bed": True,
                                     "music_path": music,
                                     "music_volume": 0.25})
    assert os.path.exists(out) and os.path.getsize(out) > 1000


def test_make_clip_no_speech_require_speech(tmp_path, monkeypatch):
    _stub_transcribe(monkeypatch, [])  # silence everywhere
    src = make_synthetic_ref(str(tmp_path / "src.mp4"))
    out = str(tmp_path / "silent.mp4")
    with pytest.raises(ValueError, match="no speech"):
        clipper.make_clip(src, 0.0, 6.0, out, face_track=False,
                          require_speech=True)
    # require_speech=False renders a clean 9:16 segment, no subtitles
    captured = {}
    import subprocess as _sp

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        open(cmd[-1], "wb").write(b"fake")
        return _sp.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(_sp, "run", fake_run)
    clipper.make_clip(src, 0.0, 6.0, out, face_track=False,
                      require_speech=False)
    vf = captured["cmd"][captured["cmd"].index("-vf") + 1]
    assert "subtitles=" not in vf
    assert vf == "crop=ih*9/16:ih,scale=1080:1920"
