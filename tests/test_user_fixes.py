"""User-reported bug fixes (2026-09-27) — sandbox-safe tests.

Covers: yt-dlp output-file resolution, music library listing/fetch,
7s image-to-video minimum, caption hyphen-dangle hardening, and the
script coherence prompt rules. No flask / moviepy / network needed.
"""
import inspect
import os
import re
import subprocess
import sys
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from src.backend import studio  # noqa: E402
from src.backend import clipper  # noqa: E402
from src.backend import video_assembler  # noqa: E402
from src.backend import video_gen_ai  # noqa: E402

HYPHENS = ("-", "\u2010", "\u2011", "\u2012", "\u2013", "\u2212")


def _dialogue_texts(ass_path):
    """Visible text of every Dialogue line, ASS override tags stripped."""
    texts = []
    for line in open(ass_path, encoding="utf-8"):
        if line.startswith("Dialogue"):
            text = line.rsplit(",,", 1)[1]
            texts.append(re.sub(r"{[^}]*}", "", text).strip())
    return texts


def _assert_no_leading_hyphen(texts):
    for t in texts:
        words = t.split(" ")
        assert words, "empty caption line"
        assert words[0][0] not in HYPHENS, f"dangling hyphen at line start: {t!r}"


# ── Bug 1: yt-dlp output resolution ──────────────────────────────────────────

def test_newest_media_file_finds_webm(tmp_path):
    webm = tmp_path / "Short [abc123].webm"
    webm.write_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 100)
    found = studio._newest_media_file(str(tmp_path))
    assert found == str(webm)


def test_newest_media_file_empty_dir(tmp_path):
    assert studio._newest_media_file(str(tmp_path)) is None


def test_remux_webm_to_mp4(tmp_path):
    """A real webm remuxes to mp4 via stream copy (ffmpeg in sandbox)."""
    webm = str(tmp_path / "clip.webm")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "testsrc=duration=1:size=128x128:rate=10",
                    "-c:v", "libvpx", webm],
                   check=True, timeout=60)
    out = studio._remux_to_mp4(webm)
    assert out.endswith(".mp4")
    assert os.path.exists(out) and os.path.getsize(out) > 1000
    assert not os.path.exists(webm)  # source cleaned up


def test_remux_mp4_passthrough(tmp_path):
    mp4 = str(tmp_path / "clip.mp4")
    open(mp4, "wb").write(b"fake")
    assert studio._remux_to_mp4(mp4) == mp4


def test_download_youtube_uses_reported_filepath(tmp_path, monkeypatch):
    """after_move:filepath is trusted over extension globs; a webm result
    is normalized to mp4 without raising 'no mp4 file was produced'."""
    webm = tmp_path / "My Short [vid999].webm"
    webm.write_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 100)

    class FakeProc:
        returncode = 0
        stdout = ("STUDIOFILE\t%s\n"
                  "STUDIOMETA\tMy Short\t12.5\tvid999\n" % webm)
        stderr = ""

    monkeypatch.setattr(studio, "ensure_yt_dlp", lambda: (True, "ok"))
    monkeypatch.setattr(studio.subprocess, "run", lambda *a, **k: FakeProc())
    monkeypatch.setattr(studio, "_remux_to_mp4",
                        lambda p: os.path.splitext(p)[0] + ".mp4")

    info = studio.download_youtube("https://www.youtube.com/shorts/vid999",
                                   out_dir=str(tmp_path))
    assert info["file"].endswith(".mp4")
    assert info["title"] == "My Short"
    assert info["video_id"] == "vid999"
    assert info["duration_sec"] == 12.5


def test_download_youtube_no_file_raises_helpful(tmp_path, monkeypatch):
    class FakeProc:
        returncode = 0
        stdout = "nothing printed\n"
        stderr = ""

    monkeypatch.setattr(studio, "ensure_yt_dlp", lambda: (True, "ok"))
    monkeypatch.setattr(studio.subprocess, "run", lambda *a, **k: FakeProc())
    with pytest.raises(RuntimeError, match="no video file was produced"):
        studio.download_youtube("https://www.youtube.com/shorts/vid999",
                                out_dir=str(tmp_path))


def test_shorts_url_accepted():
    assert studio.is_youtube_url(
        "https://www.youtube.com/shorts/0L6VwhoVGk8?feature=share")
    assert studio.is_youtube_url("https://youtu.be/0L6VwhoVGk8")
    assert not studio.is_youtube_url("https://vimeo.com/123")


# ── Bug 2: music library ─────────────────────────────────────────────────────

def _fake_library(rows):
    class FakeLib:
        def browse(self, **kwargs):
            return {"total": len(rows), "sounds": rows}
        def log(self, *a, **k):
            pass
    return FakeLib()


def test_list_music_tracks(monkeypatch):
    import src.backend.audio_agent.library as libmod
    import src.backend.audio_agent.sync as syncmod
    rows = [
        {"id": 1, "name": "Viral Phonk", "duration_sec": 30,
         "local_path": "/tmp/x.mp3", "source_url": "http://cdn/a.mp3",
         "source": "pixabay", "emotion": "energetic", "energy_level": 8,
         "viral_score": 90},
        {"id": 2, "name": "LoFi Chill", "duration_sec": 60,
         "local_path": "", "source_url": "http://cdn/b.mp3",
         "source": "pixabay", "emotion": "calm", "energy_level": 3,
         "viral_score": 95},
    ]
    monkeypatch.setattr(libmod, "AudioLibrary", lambda: _fake_library(rows))
    monkeypatch.setattr(syncmod, "ensure_fresh", lambda *a, **k: True)
    monkeypatch.setattr(os.path, "exists", lambda p: p == "/tmp/x.mp3")

    tracks = studio.list_music_tracks()
    assert len(tracks) == 2
    # Downloaded first even though the remote-only track scores higher.
    assert tracks[0]["id"] == 1 and tracks[0]["has_local_file"] is True
    assert tracks[0]["play_url"] == "/api/audio/file/x.mp3"
    assert tracks[1]["id"] == 2 and tracks[1]["has_local_file"] is False
    assert tracks[1]["play_url"] == "http://cdn/b.mp3"  # remote preview


def test_list_music_tracks_never_raises(monkeypatch):
    import src.backend.audio_agent.library as libmod
    import src.backend.audio_agent.sync as syncmod
    monkeypatch.setattr(syncmod, "ensure_fresh",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    monkeypatch.setattr(libmod, "AudioLibrary",
                        lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    assert studio.list_music_tracks() == []


def test_fetch_viral_music(monkeypatch):
    import src.backend.audio_agent.library as libmod
    from src.backend.audio_agent import scraper as scrmod
    from src.backend.audio_agent import sound_scout
    monkeypatch.setattr(libmod, "AudioLibrary", lambda: _fake_library([]))
    monkeypatch.setattr(scrmod.AudioScraper, "_sync_curated_music",
                        lambda self: {"downloaded": 2, "failed": 0})
    monkeypatch.setattr(scrmod.AudioScraper, "_index_record",
                        lambda self, rec: "downloaded")
    monkeypatch.setattr(sound_scout, "scrape_pixabay_music",
                        lambda q, limit=6: [{"name": f"{q} hit",
                                             "category": "music"}])
    stats = studio.fetch_viral_music(max_downloads=5)
    assert stats["total_downloaded"] == 5
    assert stats["curated"]["downloaded"] == 2
    assert stats["pixabay_music"]["downloaded"] == 3
    assert "error" not in stats


# ── Bug 3: 9s image-to-video (user: "more than 8 seconds") ────────────────────

def test_min_shot_seconds_is_9():
    assert video_gen_ai.MIN_SHOT_SECONDS == 9.0


def test_generate_video_from_image_clamps_to_9():
    src = inspect.getsource(video_gen_ai.generate_video_from_image)
    assert "duration: float = 9.0" in src
    assert "max(MIN_SHOT_SECONDS, duration)" in src


# ── Bug 5: caption hyphen dangle ─────────────────────────────────────────────

def _live_action_words():
    return [
        (["STUART", "BLOOM", "STUMBLES", "INTO", "LIVE-ACTION", "GOTHAM"], 0,
         0.0, 2.4),
        (["STUART", "BLOOM", "STUMBLES", "INTO", "-ACTION", "GOTHAM"], 4,
         2.4, 4.8),
    ]


def test_assembler_no_leading_hyphen(tmp_path):
    events = []
    t = 0.0
    for words, idx, s, e in _live_action_words():
        events.append((words, idx, s, e))
        t = e
    ass = str(tmp_path / "cap.ass")
    video_assembler.build_caption_ass(events, ass)
    texts = _dialogue_texts(ass)
    assert texts, "no dialogue lines produced"
    _assert_no_leading_hyphen(texts)
    assert not any("-ACTION" in t for t in texts), texts


def test_assembler_hyphen_variants_glued():
    for variant in ("LIVE‐ACTION", "LIVE–ACTION", "WELL—KNOWN".replace("—", "–")):
        out = video_assembler._sanitize_caption_word(variant)
        assert "-" not in out, f"ASCII hyphen survived in {variant!r} -> {out!r}"
        assert "\u2011" in out


def test_clipper_karaoke_no_leading_hyphen(tmp_path):
    words = [{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.35}
             for i, w in enumerate(
                 ["STUART", "BLOOM", "STUMBLES", "INTO",
                  "LIVE-ACTION", "GOTHAM", "CITY", "TONIGHT",
                  "-ACTION", "AGAIN"])]
    ass = str(tmp_path / "k.ass")
    clipper._write_ass_karaoke(words, ass, max_words_per_line=4)
    texts = _dialogue_texts(ass)
    assert texts
    _assert_no_leading_hyphen(texts)
    # The stray "-ACTION" token was reflowed onto the previous line.
    assert any("ACTION" in t and "GOTHAM" in t for t in texts), texts


def test_clipper_srt_no_leading_hyphen(tmp_path):
    words = [{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.35}
             for i, w in enumerate(["INTO", "LIVE-ACTION", "GOTHAM"])]
    ass = str(tmp_path / "s.ass")
    clipper._write_srt_classic(words, ass, max_words_per_line=2)
    texts = _dialogue_texts(ass)
    assert texts
    _assert_no_leading_hyphen(texts)
    assert all("-" not in t for t in texts), texts


# ── Bug 4: script coherence prompt rules ─────────────────────────────────────

def test_script_prompt_coherence_rules():
    src = open(os.path.join(REPO, "src", "backend", "script_gen.py"),
               encoding="utf-8").read()
    assert "HARD COHERENCE RULES" in src
    assert "ONE single topic per short" in src
    assert "never name-drop celebrities" in src
    assert "8-12 words per scene" in src
    assert "SAME story" in src
    assert "Concrete visuals" in src or "concrete" in src.lower()
