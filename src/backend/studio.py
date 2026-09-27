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


def download_youtube(url: str, out_dir: str = STUDIO_DIR) -> dict:
    """Download best mp4 <=720p via yt-dlp. Returns {file, title, video_id, duration_sec}."""
    ok, msg = ensure_yt_dlp()
    if not ok:
        raise RuntimeError(f"yt-dlp unavailable: {msg}")
    os.makedirs(out_dir, exist_ok=True)
    out_tmpl = os.path.join(out_dir, "%(title).60s [%(id)s].%(ext)s")
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--no-playlist",
        "-f", "bv*[height<=720]+ba/b[height<=720]/b",
        "--merge-output-format", "mp4",
        "--no-warnings",
        "-o", out_tmpl,
        "--print", "%(title)s\t%(duration)s\t%(id)s",
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {(proc.stderr or proc.stdout or '')[-500:]}")
    # Last non-empty stdout line carries title/duration/id.
    meta_line = ""
    for line in reversed((proc.stdout or "").splitlines()):
        if line.strip():
            meta_line = line.strip()
            break
    title, duration_s, video_id = "YouTube video", "0", ""
    parts = meta_line.split("\t")
    if len(parts) >= 3:
        title, duration_s, video_id = parts[0], parts[1], parts[2]
    # Find the downloaded file: newest mp4 in out_dir matching the video id.
    candidates = []
    for fname in os.listdir(out_dir):
        if fname.lower().endswith(".mp4"):
            fpath = os.path.join(out_dir, fname)
            if video_id and video_id in fname:
                candidates.append((os.path.getmtime(fpath), fpath))
    if not candidates:
        for fname in os.listdir(out_dir):
            if fname.lower().endswith(".mp4"):
                fpath = os.path.join(out_dir, fname)
                candidates.append((os.path.getmtime(fpath), fpath))
    if not candidates:
        raise RuntimeError("yt-dlp finished but no mp4 file was produced")
    candidates.sort(reverse=True)
    fpath = candidates[0][1]
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
