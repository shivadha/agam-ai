"""Clip Studio backend: YouTube import, random clip windows, music mixing.

All free/local: yt-dlp + ffmpeg only. No new dependencies.
"""

import json
import os
import random
import re
import shutil
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
STUDIO_DIR = os.path.join(OUTPUT_DIR, "studio")

# youtube.com/watch, /shorts/, /live/, /embed/, youtu.be/ — reject everything else.
YOUTUBE_RE = re.compile(
    r"^(https?://)?(www\.|m\.)?(youtube\.com/(watch|shorts|live|embed)|youtu\.be/)"
)


def is_youtube_url(url: str) -> bool:
    """True only for real YouTube watch/shorts/live/embed/youtu.be links."""
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    if len(url) > 500:
        return False
    return bool(YOUTUBE_RE.match(url))


def _ffmpeg_exe() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def _ffprobe_exe() -> str:
    return shutil.which("ffprobe") or "ffprobe"


def ensure_yt_dlp() -> tuple:
    """Make sure yt-dlp is importable, pip-installing it on the fly if needed."""
    try:
        import yt_dlp  # noqa: F401
        return True, "yt-dlp available"
    except ImportError:
        pass
    try:
        from src.backend.auto_bootstrap import _pip_install
        ok, msg = _pip_install("yt-dlp")
        return ok, msg
    except Exception as e:
        return False, f"could not install yt-dlp: {e}"


def safe_filename(name: str, max_len: int = 80) -> str:
    name = re.sub(r"[^\w\-. ]+", "_", name or "video").strip()
    name = re.sub(r"\s+", " ", name)
    return (name[:max_len] or "video").strip()


def _remux_to_mp4(src_path: str) -> str:
    """Remux a non-mp4 download (e.g. webm) into an mp4 container.

    yt-dlp's --merge-output-format only applies when it actually merges
    streams; a single-file download keeps its native extension, which is
    what produced the old "finished but no mp4 file was produced" error.
    Stream-copy first (fast, lossless); fall back to a light re-encode.
    Returns the mp4 path on success, else the original path.
    """
    if src_path.lower().endswith(".mp4"):
        return src_path
    dst_path = os.path.splitext(src_path)[0] + ".mp4"
    ffmpeg = _ffmpeg_exe()
    for extra in (["-c", "copy"], ["-c:v", "libx264", "-preset", "veryfast",
                                   "-crf", "21", "-c:a", "aac"]):
        try:
            proc = subprocess.run(
                [ffmpeg, "-y", "-i", src_path] + extra + [dst_path],
                capture_output=True, text=True, timeout=900)
            if proc.returncode == 0 and os.path.exists(dst_path) \
                    and os.path.getsize(dst_path) > 500:
                try:
                    os.remove(src_path)
                except OSError:
                    pass
                return dst_path
        except Exception:
            pass
    return src_path


def _newest_media_file(out_dir: str, exts=(".mp4", ".webm", ".mkv", ".mov")) -> str | None:
    """Newest media file in a directory (fallback when yt-dlp's reported
    path can't be used)."""
    best = None
    try:
        for fname in os.listdir(out_dir):
            if fname.lower().endswith(exts):
                fpath = os.path.join(out_dir, fname)
                try:
                    mtime = os.path.getmtime(fpath)
                except OSError:
                    continue
                if best is None or mtime > best[0]:
                    best = (mtime, fpath)
    except OSError:
        pass
    return best[1] if best else None


def download_youtube(url: str, out_dir: str = STUDIO_DIR) -> dict:
    """Download best <=720p via yt-dlp. Returns {file, title, video_id, duration_sec}.

    Robust file resolution: the final on-disk path is captured with
    ``--print after_move:filepath`` so we never depend on extension
    guessing or filename globs. If yt-dlp produced a non-mp4 container
    (e.g. webm — a single-file download keeps its native extension even
    with --merge-output-format mp4), it is remuxed to mp4 with ffmpeg.
    """
    ok, msg = ensure_yt_dlp()
    if not ok:
        raise RuntimeError(f"yt-dlp unavailable: {msg}")
    os.makedirs(out_dir, exist_ok=True)
    out_tmpl = os.path.join(out_dir, "%(title).60s [%(id)s].%(ext)s")
    # Marker-delimited prints: one line carries the FINAL filepath (after
    # any merge/move), the other carries title/duration/id. after_move
    # prints only once the file is fully written.
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--no-playlist",
        "-f", "bv*[height<=720]+ba/b[height<=720]/b",
        "--merge-output-format", "mp4",
        "--no-warnings",
        "-o", out_tmpl,
        "--print", "after_move:STUDIOFILE\t%(filepath)s",
        "--print", "after_move:STUDIOMETA\t%(title)s\t%(duration)s\t%(id)s",
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {(proc.stderr or proc.stdout or '')[-500:]}")
    # Parse the marker lines (last occurrence wins).
    fpath = None
    title, duration_s, video_id = "YouTube video", "0", ""
    for line in (proc.stdout or "").splitlines():
        if line.startswith("STUDIOFILE\t"):
            cand = line.split("\t", 1)[1].strip()
            if cand:
                fpath = cand
        elif line.startswith("STUDIOMETA\t"):
            parts = line.split("\t")
            if len(parts) >= 4:
                title, duration_s, video_id = parts[1], parts[2], parts[3]
    # Fallbacks: the exact path missing (old yt-dlp without after_move
    # support) -> newest media file in the job dir.
    if not fpath or not os.path.exists(fpath):
        fpath = _newest_media_file(out_dir)
    if not fpath or not os.path.exists(fpath):
        raise RuntimeError(
            "yt-dlp finished but no video file was produced "
            f"(stdout tail: {((proc.stdout or '')[-200:]).strip()!r})")
    # Normalize to mp4 so every downstream step (clipper, DB, UI) can
    # rely on the container.
    fpath = _remux_to_mp4(fpath)
    try:
        duration = float(duration_s) if duration_s not in ("NA", "None", "") else 0.0
    except (TypeError, ValueError):
        duration = 0.0
    if not duration:
        duration = probe_duration(fpath)
    return {
        "file": os.path.relpath(fpath, OUTPUT_DIR).replace("\\", "/"),
        "title": title,
        "video_id": video_id,
        "duration_sec": round(duration, 1),
    }


def probe_duration(path: str) -> float:
    """Media duration in seconds via ffprobe (0.0 on failure)."""
    try:
        proc = subprocess.run(
            [_ffprobe_exe(), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=60,
        )
        return float((proc.stdout or "").strip())
    except Exception:
        return 0.0


def has_audio_stream(path: str) -> bool:
    """True if the file has at least one audio stream."""
    try:
        proc = subprocess.run(
            [_ffprobe_exe(), "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=60,
        )
        return bool((proc.stdout or "").strip())
    except Exception:
        return False


def pick_random_windows(duration: float, num_clips: int = 3,
                        min_sec: float = 15.0, max_sec: float = 45.0,
                        seed=None) -> list:
    """Pick N random non-overlapping (start, end) windows inside [0, duration].

    Raises ValueError when the request is impossible (e.g. video too short).
    """
    if duration <= 0:
        raise ValueError("video has no measurable duration")
    if num_clips < 1:
        raise ValueError("num_clips must be >= 1")
    if min_sec < 3:
        min_sec = 3.0
    if max_sec < min_sec:
        max_sec = min_sec
    if duration < min_sec:
        raise ValueError(
            f"video is only {duration:.1f}s — shorter than min clip length {min_sec:.0f}s")
    rng = random.Random(seed)
    windows = []
    # Try random placements; keep them non-overlapping.
    for _ in range(2000):
        if len(windows) >= num_clips:
            break
        length = rng.uniform(min_sec, min(max_sec, duration))
        if length > duration:
            continue
        start = rng.uniform(0, duration - length)
        end = start + length
        if all(end <= s or start >= e for s, e in windows):
            windows.append((round(start, 2), round(end, 2)))
    if len(windows) < num_clips:
        # Fall back: tile the video evenly (still "random-ish" via shuffle).
        tile = duration / num_clips
        if tile < min_sec:
            raise ValueError(
                f"could only place {len(windows)}/{num_clips} non-overlapping clips")
        windows = []
        for i in range(num_clips):
            s = round(i * tile, 2)
            e = round(min(duration, s + min(max_sec, tile)), 2)
            if e - s >= min_sec * 0.7:
                windows.append((s, e))
    windows.sort()
    return windows[:num_clips]


def render_random_clips(video_path: str, duration: float, num_clips: int,
                        min_sec: float, max_sec: float, out_dir: str,
                        seed=None, clip_fn=None) -> dict:
    """Render N random clips with karaoke captions.

    Windows with no speech are skipped and repicked (up to 3 tries per clip).
    clip_fn(video_path, start, end, out_path) defaults to clipper.make_clip;
    injectable for tests.
    Returns {"clips": [...], "skipped": int}.
    """
    if clip_fn is None:
        from src.backend.clipper import make_clip as clip_fn
    os.makedirs(out_dir, exist_ok=True)
    rng_seed = seed if seed is not None else random.randint(0, 2 ** 31 - 1)
    clips, skipped = [], 0
    attempts = 0
    max_attempts = num_clips * 4 + 5
    tried = set()
    while len(clips) < num_clips and attempts < max_attempts:
        attempts += 1
        (start, end) = pick_random_windows(
            duration, 1, min_sec, max_sec,
            seed=(rng_seed + attempts * 7919))[0]
        key = (start, end)
        if key in tried:
            continue
        tried.add(key)
        out_path = os.path.join(out_dir, f"clip_{len(clips) + 1:02d}_{int(start)}s-{int(end)}s.mp4")
        try:
            clip_fn(video_path, start, end, out_path)
        except ValueError as e:
            if "no speech" in str(e).lower():
                skipped += 1
                continue
            raise
        clips.append({
            "file": os.path.relpath(out_path, OUTPUT_DIR).replace("\\", "/"),
            "start_sec": start,
            "end_sec": end,
        })
    return {"clips": clips, "skipped": skipped}


def render_single_clip(video_path: str, start_sec: float, end_sec: float,
                       out_dir: str, clip_fn=None) -> dict:
    """Render one clip at an exact window. Returns {"file","start_sec","end_sec"}."""
    if clip_fn is None:
        from src.backend.clipper import make_clip as clip_fn
    if end_sec <= start_sec:
        raise ValueError("end must be after start")
    if end_sec - start_sec > 180:
        raise ValueError("clips are capped at 3 minutes")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(
        out_dir, f"trim_{int(start_sec)}s-{int(end_sec)}s.mp4")
    clip_fn(video_path, round(start_sec, 2), round(end_sec, 2), out_path)
    return {
        "file": os.path.relpath(out_path, OUTPUT_DIR).replace("\\", "/"),
        "start_sec": round(start_sec, 2),
        "end_sec": round(end_sec, 2),
    }


def resolve_sound_path(sound_id: int) -> dict:
    """Resolve a library sound id to its downloaded local audio file.

    Downloads it on the fly if needed. Returns {"path", "name"}.
    """
    from src.backend.audio_agent import library as libmod
    row = None
    with libmod._db() as conn:
        row = conn.execute(
            "SELECT id, name, local_path, is_downloaded FROM sound_library WHERE id = ?",
            (sound_id,)).fetchone()
    if not row:
        raise ValueError(f"unknown sound id {sound_id}")
    lp = row["local_path"]
    if not row["is_downloaded"] or not lp or not os.path.exists(lp):
        from src.backend.audio_agent.library import AudioLibrary
        res = AudioLibrary().save_locally(int(sound_id))
        if not res.get("success"):
            raise RuntimeError(f"could not fetch sound: {res.get('error', 'download failed')}")
        lp = res.get("local_path")
    if not lp or not os.path.exists(lp):
        raise RuntimeError("sound file is not available locally")
    return {"path": os.path.abspath(lp), "name": row["name"]}


def list_music_tracks(per_page: int = 60) -> list:
    """Music tracks for the Clip Studio music card, backed by the real
    sound library (not hardcoded).

    Returns library music sounds — downloaded ones first — each as
    {id, name, duration_sec, has_local_file, play_url, source, emotion,
    viral_score}. play_url streams the local file when downloaded, else
    the remote source_url so tracks can be previewed before download.
    Mixing a non-downloaded track fetches it on demand (see
    resolve_sound_path). Never raises; returns [] on failure.

    Kicks off a background library sync when the collection is thin so
    the card keeps filling itself with free viral tracks.
    """
    try:
        from src.backend.audio_agent.sync import ensure_fresh
        try:
            ensure_fresh("music", min_downloaded=5, max_downloads=40)
        except Exception:
            pass
        from src.backend.audio_agent.library import AudioLibrary
        lib = AudioLibrary()
        data = lib.browse(category="music", downloaded_only=False,
                          per_page=max(1, min(per_page, 200)))
        tracks = []
        for s in data.get("sounds", []):
            lp = s.get("local_path") or ""
            has_file = bool(lp) and os.path.exists(lp)
            play_url = None
            if has_file:
                # Same URL scheme as /api/audio-library enrichment.
                fname = os.path.basename(lp)
                play_url = f"/api/audio/file/{fname}"
            elif s.get("source_url"):
                play_url = s.get("source_url")
            tracks.append({
                "id": s.get("id"),
                "name": s.get("name") or f"Track {s.get('id')}",
                "duration_sec": s.get("duration_sec"),
                "has_local_file": has_file,
                "play_url": play_url,
                "source": s.get("source"),
                "emotion": s.get("emotion"),
                "energy_level": s.get("energy_level"),
                "viral_score": s.get("viral_score"),
            })
        # Downloaded first, then by viral score.
        tracks.sort(key=lambda t: (not t["has_local_file"],
                                   -(t["viral_score"] or 0)))
        return tracks
    except Exception as e:
        print(f"[studio] list_music_tracks note: {e}")
        return []


VIRAL_MUSIC_QUERIES = ["viral", "trending", "phonk", "upbeat", "cinematic",
                       "lofi hip hop", "energetic", "epic trailer"]


def fetch_viral_music(max_downloads: int = 25) -> dict:
    """Download more FREE viral background tracks into the sound library.

    Sources (all free, no API keys): the curated music catalog, Pixabay
    music searches, and the trending scout's music finds. Best-effort and
    never raises — returns a stats dict.
    """
    stats = {"curated": {"downloaded": 0, "failed": 0},
             "pixabay_music": {"downloaded": 0, "failed": 0},
             "total_downloaded": 0}
    try:
        from src.backend.audio_agent.library import AudioLibrary
        from src.backend.audio_agent.scraper import AudioScraper
        from src.backend.audio_agent import sound_scout
        lib = AudioLibrary()
        scraper = AudioScraper(library=lib)
        try:
            stats["curated"] = scraper._sync_curated_music()
        except Exception as e:
            stats["curated"] = {"downloaded": 0, "failed": 0, "error": str(e)}
        downloaded = int(stats["curated"].get("downloaded", 0) or 0)
        pix_dl = pix_fail = 0
        for q in VIRAL_MUSIC_QUERIES:
            if downloaded >= max_downloads:
                break
            try:
                recs = sound_scout.scrape_pixabay_music(q, limit=6)
            except Exception:
                continue
            for rec in recs:
                if downloaded >= max_downloads:
                    break
                try:
                    outcome = scraper._index_record(rec)
                except Exception:
                    outcome = "failed"
                if outcome == "downloaded":
                    downloaded += 1
                    pix_dl += 1
                elif outcome == "failed":
                    pix_fail += 1
        stats["pixabay_music"] = {"downloaded": pix_dl, "failed": pix_fail}
        stats["total_downloaded"] = downloaded
        try:
            lib.log("studio_fetch_viral_music", f"downloaded={downloaded}")
        except Exception:
            pass
    except Exception as e:
        stats["error"] = str(e)
    return stats


def build_music_mix_cmd(video_path: str, music_path: str, out_path: str,
                        volume: float = 0.25, has_audio: bool = True) -> list:
    """ffmpeg command that mixes looped background music under the video.

    Original audio (if any) stays at full volume; music is ducked to `volume`.
    Video stream is copied untouched; output is cut to the video length.
    """
    vol = max(0.0, min(1.0, float(volume)))
    cmd = [_ffmpeg_exe(), "-y",
           "-i", video_path,
           "-stream_loop", "-1", "-i", music_path]
    if has_audio:
        fc = (f"[1:a]volume={vol},aresample=44100[m];"
              f"[0:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]")
        cmd += ["-filter_complex", fc,
                "-map", "0:v", "-map", "[a]"]
    else:
        fc = f"[1:a]volume={vol},aresample=44100[a]"
        cmd += ["-filter_complex", fc,
                "-map", "0:v", "-map", "[a]"]
    cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
            "-movflags", "+faststart", "-shortest", out_path]
    return cmd


def mix_music(video_path: str, music_path: str, out_path: str,
              volume: float = 0.25) -> str:
    """Mix music into a video file. Returns out_path. Raises on failure."""
    cmd = build_music_mix_cmd(video_path, music_path, out_path,
                              volume=volume, has_audio=has_audio_stream(video_path))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError(f"music mix failed: {(proc.stderr or '')[-600:]}")
    return out_path


def make_thumb(video_path: str, out_path: str, t: float = None) -> str:
    """Grab a 320px-wide JPEG thumbnail (mid-frame by default)."""
    dur = probe_duration(video_path)
    if t is None:
        t = max(0.0, dur / 2.0)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    proc = subprocess.run(
        [_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
         "-ss", str(t), "-i", video_path, "-frames:v", "1",
         "-vf", "scale=320:-1", "-q:v", "5", out_path],
        capture_output=True, timeout=60)
    if proc.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError(f"thumbnail failed: {(proc.stderr or '')[-300:]}")
    return out_path


def clone_short_as_is(reference_url: str, video_path: str,
                      progress_cb=None) -> dict:
    """Clone a reference Short's SCRIPT + TEMPLATE + EDITING STYLE.

    Pipeline:
      1. download the reference short
      2. analyze_short() -> pacing (cuts/min), per-shot camera motion,
         caption zone/size, WPM, word-timed transcript (the "script")
      3. proportionally map the reference EDL onto the user's footage
         (shot durations, per-shot motion, caption cadence)
      4. render each mapped shot with clipper.make_clip(style_profile=...)
         -- captions come from the USER's own transcription, timed to the
         reference's caption cadence
      5. concat the shots, save the style + clip rows

    NOTE: the reference's music track can't be lifted (it's baked into the
    download), so a music bed is NOT copied -- only structure, motion,
    pacing, and caption style.

    video_path may be absolute or relative to OUTPUT_DIR. Returns a dict
    with file/style_id/clip_id/profile. Raises on failure.
    """
    from src.backend import style_analyzer, clipper
    from src import database as db

    def _prog(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    if not is_youtube_url(reference_url):
        raise ValueError("not a YouTube URL")
    if not os.path.isabs(video_path):
        video_path = os.path.join(OUTPUT_DIR, video_path)
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"video not found: {video_path}")

    stamp = __import__("time").strftime("%Y%m%d_%H%M%S")
    work_dir = os.path.join(STUDIO_DIR, "clones", stamp)
    os.makedirs(work_dir, exist_ok=True)

    _prog("downloading reference short")
    ref_info = download_youtube(reference_url.strip(), out_dir=work_dir)
    ref_path = os.path.join(OUTPUT_DIR, ref_info["file"])
    ref_title = ref_info.get("title") or "reference short"

    _prog("analyzing reference style")
    profile = style_analyzer.analyze_short(
        ref_path, work_dir=work_dir, progress_cb=_prog)

    ref_dur = float(profile.get("duration_s") or probe_duration(ref_path))
    user_dur = probe_duration(video_path)
    if user_dur <= 0:
        raise ValueError("user video has no measurable duration")
    if ref_dur <= 0:
        raise ValueError("reference video has no measurable duration")

    _prog("transcribing your footage")
    try:
        from src.backend.captions import transcribe_word_timings
        user_words = transcribe_word_timings(video_path) or []
    except Exception:
        user_words = []

    _prog("mapping reference edit plan onto your footage")
    edl = style_analyzer.map_edl_to_duration(
        profile.get("edl") or [], ref_dur, user_dur)
    if not edl:  # analysis failed: fall back to one full-length segment
        edl = [{"shot": 1, "start": 0.0, "end": user_dur,
                "duration": user_dur, "motion": "static",
                "zoom_intensity": 0.0, "word_count": 0, "text": ""}]

    segments = []
    try:
        for i, shot in enumerate(edl):
            _prog(f"rendering shot {i + 1}/{len(edl)}")
            a, b = shot["start"], shot["end"]
            if b - a < 0.4:
                continue
            sp = {
                "captions": profile.get("captions") or {},
                "words_per_caption": max(
                    1, min(6, int(shot.get("word_count")
                                   or profile.get("words_per_caption") or 3))),
                "motion": shot.get("motion") or "static",
                "zoom_intensity": shot.get("zoom_intensity") or 0.0,
            }
            seg_path = os.path.join(work_dir, f"seg_{i:03d}.mp4")
            clipper.make_clip(video_path, a, b, seg_path,
                              style_profile=sp, require_speech=False)
            segments.append(seg_path)

        if not segments:
            raise RuntimeError("no clone segments could be rendered")

        _prog("assembling final clone")
        list_path = os.path.join(work_dir, "concat.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            for s in segments:
                f.write("file '%s'\n" % s.replace("'", "'\\''"))
        out_name = "clone_%s.mp4" % stamp
        out_abs = os.path.join(work_dir, out_name)
        proc = subprocess.run(
            [_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
             "-f", "concat", "-safe", "0", "-i", list_path,
             "-c", "copy", "-movflags", "+faststart", out_abs],
            capture_output=True, timeout=1800)
        if proc.returncode != 0 or not os.path.exists(out_abs):
            raise RuntimeError(
                f"clone concat failed: {(proc.stderr or '')[-600:]}")
    finally:
        for s in segments:
            try:
                os.remove(s)
            except OSError:
                pass

    rel_out = os.path.relpath(out_abs, OUTPUT_DIR).replace("\\", "/")
    thumb_rel = ""
    try:
        thumb_abs = os.path.join(work_dir, "clone_thumb.jpg")
        make_thumb(out_abs, thumb_abs)
        thumb_rel = os.path.relpath(thumb_abs, OUTPUT_DIR).replace("\\", "/")
    except Exception:
        pass

    _prog("saving to your library")
    db.init_db()
    style_thumb = (profile.get("thumb_paths") or [""])[0]
    style_id = db.save_clip_style(
        name=f"Clone of {ref_title[:60]}",
        source_url=reference_url.strip(),
        profile=profile,
        thumb_path=style_thumb)
    clip_id = db.record_clip(
        source_video=os.path.relpath(video_path, OUTPUT_DIR).replace("\\", "/"),
        source_url=reference_url.strip(),
        start_s=0.0, end_s=round(user_dur, 2),
        style_id=style_id, output_path=rel_out, thumb_path=thumb_rel,
        kind="clone",
        meta={"ref_title": ref_title,
              "ref_duration_s": round(ref_dur, 2),
              "shots": len(edl),
              "user_words": len(user_words)})

    _prog("done")
    return {
        "file": rel_out,
        "thumb": thumb_rel,
        "title": f"Clone of {ref_title[:60]}",
        "style_id": style_id,
        "clip_id": clip_id,
        "shots": len(edl),
        "ref_duration_s": round(ref_dur, 2),
        "user_duration_s": round(user_dur, 2),
        "cuts_per_min": (profile.get("pacing") or {}).get("cuts_per_min", 0),
        "caption_zone": (profile.get("captions") or {}).get("zone"),
    }
