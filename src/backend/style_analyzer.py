"""Style Lab: learn a viral short's editing style into a reusable profile.

analyze_short(url_or_path) -> dict with:
  pacing:   cuts_per_min, avg_shot_len_s, cut_timestamps
  motion:   dominant (static/zoom_in/zoom_out/pan), zoom_intensity per shot
  captions: present, zone (top/middle/bottom), rel_height
  audio:    wpm, music_bed (energy in non-speech segments)
  duration_s, transcript (word-timed = the "script"), edl (per-shot edit list),
  thumb_paths (sample thumbnails for the style card)

Everything is free/local: ffmpeg + numpy + PIL. OpenCV is optional (used for
MSER caption detection when present; a numpy bright-band fallback covers the
rest). faster-whisper is optional (transcript/wpm/music_bed degrade to
unknown when it is missing). Every sub-analysis fails soft -- a broken piece
never crashes the whole analysis.
"""

import os
import re
import shutil
import statistics
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
STYLE_WORK_DIR = os.path.join(OUTPUT_DIR, "studio", "style_refs")


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


def _ffmpeg():
    return shutil.which("ffmpeg") or "ffmpeg"


def analyze_short(url_or_path, work_dir=None, progress_cb=None):
    """Analyze a YouTube Short URL or a local video file.

    Returns a JSON-serializable style profile dict. Never raises for
    analysis failures (returns partial profile); raises only when the
    video itself cannot be obtained.
    """
    from src.backend import studio as studio_mod

    def _prog(msg):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    work_dir = work_dir or os.path.join(STYLE_WORK_DIR, "adhoc")
    os.makedirs(work_dir, exist_ok=True)

    source_url = ""
    local_path = url_or_path
    if studio_mod.is_youtube_url(url_or_path):
        _prog("downloading reference short")
        source_url = url_or_path.strip()
        info = studio_mod.download_youtube(source_url, out_dir=work_dir)
        local_path = os.path.join(OUTPUT_DIR, info["file"])
    if not local_path or not os.path.exists(local_path):
        raise FileNotFoundError(f"reference video not found: {url_or_path}")

    duration = _safe(lambda: studio_mod.probe_duration(local_path), 0.0) or 0.0

    profile = {
        "source_url": source_url,
        "local_path": local_path,
        "duration_s": round(duration, 2),
        "pacing": {"cuts_per_min": 0.0, "avg_shot_len_s": 0.0, "cut_timestamps": []},
        "motion": {"dominant": "static", "per_shot": []},
        "captions": {"present": False, "zone": None, "rel_height": 0.0},
        "audio": {"wpm": 0.0, "music_bed": False, "speech_ratio": 0.0},
        "transcript": [],
        "edl": [],
        "thumb_paths": [],
        "words_per_caption": 3,
    }

    # -- pacing: ffmpeg scene detection -------------------------------------
    _prog("detecting cuts")
    shots = _safe(lambda: _detect_shots(local_path, duration), [])
    if shots:
        cuts = [s for s, _ in shots[1:]]
        lens = [b - a for a, b in shots]
        mins = max(duration / 60.0, 1e-6)
        profile["pacing"] = {
            "cuts_per_min": round((len(shots) - 1) / mins, 1),
            "avg_shot_len_s": round(statistics.mean(lens), 2),
            "cut_timestamps": [round(c, 2) for c in cuts],
        }

    # -- motion: reuse clone-short estimator --------------------------------
    _prog("estimating camera motion")
    per_shot, motions = _safe(lambda: _shot_motions(local_path, shots), ([], []))
    if motions:
        try:
            dom = statistics.mode(motions)
        except statistics.StatisticsError:
            dom = motions[0]
        profile["motion"] = {
            "dominant": _simplify_motion(dom),
            "per_shot": per_shot,
        }

    # -- captions: burned-in text detection ----------------------------------
    _prog("detecting burned-in captions")
    profile["captions"] = _safe(
        lambda: _detect_caption_zone(local_path, duration),
        {"present": False, "zone": None, "rel_height": 0.0})

    # -- audio: transcript, wpm, music bed ----------------------------------
    _prog("transcribing audio")
    words = _safe(lambda: _transcribe(local_path), [])
    profile["transcript"] = [
        {"word": w.get("word", ""), "start": round(float(w.get("start", 0)), 2),
         "end": round(float(w.get("end", 0)), 2)} for w in words
    ]
    if words:
        span = max(0.1, words[-1].get("end", 0) - words[0].get("start", 0))
        profile["audio"]["wpm"] = round(len(words) / span * 60.0, 1)
        speech = sum(max(0.0, w.get("end", 0) - w.get("start", 0)) for w in words)
        profile["audio"]["speech_ratio"] = round(
            min(1.0, speech / max(duration, 0.1)), 3)
    profile["audio"]["music_bed"] = _safe(
        lambda: _detect_music_bed(local_path, words, duration=duration), False)

    # -- edit decision list: map transcript words onto shots -----------------
    _prog("building edit decision list")
    profile["edl"] = _build_edl(shots, per_shot, words)
    wpc = [e["word_count"] for e in profile["edl"] if e["word_count"] > 0]
    if wpc:
        profile["words_per_caption"] = int(
            max(1, min(6, round(statistics.median(wpc)))))

    # -- thumbnails for the style card ---------------------------------------
    _prog("grabbing thumbnails")
    profile["thumb_paths"] = _safe(
        lambda: _style_thumbs(local_path, shots, work_dir), [])

    _prog("done")
    return profile


# ---------------------------------------------------------------------------
# pacing
# ---------------------------------------------------------------------------

def _detect_shots(path, duration):
    """Shot boundaries via ffmpeg scene detection (like reference_clone)."""
    cuts = []
    proc = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-i", path, "-vf",
         "select='gt(scene\\,0.15)',showinfo",
         "-vsync", "0", "-f", "null", "-"],
        capture_output=True, text=True, timeout=300)
    for m in re.finditer(r"pts_time:([0-9.]+)", proc.stderr or ""):
        cuts.append(float(m.group(1)))
    bounds = [0.0] + sorted(cuts) + [max(duration, 0.01)]
    shots = []
    for a, b in zip(bounds, bounds[1:]):
        if b - a >= 0.4:
            shots.append((round(a, 2), round(b, 2)))
    if not shots:
        t = 0.0
        while t < duration:
            shots.append((round(t, 2), round(min(duration, t + 3.0), 2)))
            t += 3.0
    if len(shots) > 1 and shots[-1][1] - shots[-1][0] < 0.8:
        shots[-2] = (shots[-2][0], shots[-1][1])
        shots.pop()
    return shots


# ---------------------------------------------------------------------------
# motion
# ---------------------------------------------------------------------------

def _simplify_motion(cls):
    """zoom-in/dolly-in -> zoom_in etc. for the style profile."""
    cls = (cls or "static").lower().replace("-", "_")
    if cls.startswith("zoom") or cls.startswith("dolly"):
        return "zoom_in" if "in" in cls else "zoom_out"
    if cls.startswith("pan"):
        return "pan"
    return "static"


def _zoom_intensity(path, shot):
    """Signed fractional zoom across a shot: +0.18 = 18% push-in.

    Reuses reference_clone's phase-correlation zoom search. _best_zoom only
    searches scales 0.85-1.18, so measure over a short 0.33s window (where
    real zooms land inside the range) and extrapolate the per-second rate
    across the shot. 0.0 when unmeasurable.
    """
    try:
        from src.backend import reference_clone as rc
        a, b = shot
        if b - a < 0.6:
            return 0.0
        f0 = rc._grab_frame(path, a + 0.1)
        f1 = rc._grab_frame(path, a + 0.43)
        if f0 is None or f1 is None:
            return 0.0
        import numpy as np
        arr0 = np.asarray(f0, dtype=np.float32)
        s, _score, _s1 = rc._best_zoom(arr0, f1)
        if not rc._zoom_trustworthy(_score, _s1):
            return 0.0  # flat profile: would invent a phantom zoom
        per_sec = (1.0 / s - 1.0) / 0.33
        if abs(per_sec) < 0.06:  # deadband: not a real zoom
            return 0.0
        return round(per_sec * (b - a), 3)
    except Exception:
        return 0.0


def _shot_motions(path, shots):
    """[(start, end, motion, zoom_intensity)], [motion classes]."""
    from src.backend import reference_clone as rc
    per_shot, motions = [], []
    for shot in shots[:40]:  # cap cost on very cutty videos
        cls = _safe(lambda s=shot: rc.estimate_motion(path, s), "static")
        zi = _safe(lambda s=shot: _zoom_intensity(path, s), 0.0)
        per_shot.append({"start": shot[0], "end": shot[1],
                         "motion": _simplify_motion(cls),
                         "zoom_intensity": zi})
        motions.append(_simplify_motion(cls))
    return per_shot, motions


# ---------------------------------------------------------------------------
# captions: burned-in text detection
# ---------------------------------------------------------------------------

def _sample_frames_cv2(path, n=6, width=320):
    """Yield (frame_bgr, W, H) sampled evenly through the video."""
    import cv2
    cap = cv2.VideoCapture(path)
    try:
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30)
        dur = count / fps if fps else 0
        for i in range(n):
            t = dur * (i + 0.5) / n if dur else i
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            h, w = frame.shape[:2]
            if w > width:
                frame = cv2.resize(frame, (width, int(h * width / w)))
            yield frame
    finally:
        cap.release()


def _caption_zone_mser(path):
    """MSER text-region detection. Returns (present, zone, rel_height)."""
    import cv2
    boxes = []
    frame_h = 0
    for frame in _sample_frames_cv2(path):
        h, w = frame.shape[:2]
        frame_h = h
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        mser = cv2.MSER_create()
        regions, _ = mser.detectRegions(gray)
        for pts in regions:
            x, y, bw, bh = cv2.boundingRect(pts)
            area = bw * bh
            if area < 0.0008 * w * h or area > 0.12 * w * h:
                continue
            if bw / max(bh, 1) < 1.6:  # text lines are wide
                continue
            boxes.append((x, y, bw, bh))
    return _boxes_to_zone(boxes, frame_h)


def _caption_zone_numpy(path, n=6, width=320):
    """cv2-free fallback: text rows = bright pixels AND dense edges.

    Bold white captions are bright *and* edgy (glyph outlines); plain
    bright backgrounds (sky, test patterns) are bright but smooth, so
    requiring both kills false positives on busy footage.
    """
    import numpy as np
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        return False, None, 0.0
    zone_run = {"top": 0.0, "middle": 0.0, "bottom": 0.0}
    rel_heights = []
    H = 0
    for i in range(n):
        frame = _grab_pil_frame(path, i, n, width)
        if frame is None:
            continue
        arr = np.asarray(frame.convert("L"), dtype=np.float32)
        H = arr.shape[0]
        bright = arr > 200
        edge = np.abs(np.diff(arr, axis=1)) > 40
        edge = np.pad(edge, ((0, 0), (0, 1)), mode="constant")
        score = bright.mean(axis=1) * edge.mean(axis=1)
        idx = np.where(score > 0.03)[0]
        if len(idx) == 0:
            continue
        for run in np.split(idx, np.where(np.diff(idx) > 2)[0] + 1):
            if len(run) < 6:
                continue
            center = float(run.mean()) / H
            zone = "top" if center < 1 / 3 else (
                "bottom" if center > 2 / 3 else "middle")
            zone_run[zone] += len(run)
            rel_heights.append(len(run) / H)
    if not H:
        return False, None, 0.0
    best = max(zone_run, key=zone_run.get)
    present = zone_run[best] >= 10
    rel_h = float(statistics.median(rel_heights)) if rel_heights and present else 0.0
    return present, (best if present else None), round(min(rel_h, 0.5), 3)


def _grab_pil_frame(path, i, n, width=320):
    """Grab frame i of n as PIL image (no cv2 needed)."""
    from PIL import Image
    import tempfile
    dur = _safe(lambda: float(subprocess.run(
        [shutil.which("ffprobe") or "ffprobe", "-v", "error",
         "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, stdin=subprocess.DEVNULL, timeout=30
        ).stdout.strip()), 0.0)
    t = dur * (i + 0.5) / n if dur else i * 2.0
    # Plain path (not a pre-created file): ffmpeg must not hit an
    # "overwrite?" prompt, which would block on stdin.
    tmp_path = os.path.join(
        tempfile.gettempdir(), f"stylelab_{os.getpid()}_{i}.png")
    try:
        r = subprocess.run(
            [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
             "-ss", str(t), "-i", path, "-frames:v", "1",
             "-vf", f"scale={width}:-1", tmp_path],
            capture_output=True, stdin=subprocess.DEVNULL, timeout=60)
        if r.returncode != 0 or not os.path.exists(tmp_path):
            return None
        try:
            with Image.open(tmp_path) as im:
                return im.convert("RGB")
        except Exception:
            return None
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _boxes_to_zone(boxes, frame_h):
    if not boxes or not frame_h:
        return False, None, 0.0
    ys = [(y + bh / 2.0) / frame_h for _x, y, _bw, bh in boxes]
    med = statistics.median(ys)
    zone = "top" if med < 1 / 3 else ("bottom" if med > 2 / 3 else "middle")
    rel_h = statistics.median([bh / frame_h for _x, _y, _bw, bh in boxes])
    return True, zone, round(min(rel_h, 0.5), 3)


def _detect_caption_zone(path, duration):
    """Burned-in caption detection -> {present, zone, rel_height}."""
    try:
        import cv2  # noqa: F401
        present, zone, rel_h = _caption_zone_mser(path)
        return {"present": bool(present), "zone": zone,
                "rel_height": float(rel_h)}
    except ImportError:
        pass
    except Exception:
        pass
    present, zone, rel_h = _caption_zone_numpy(path)
    return {"present": bool(present), "zone": zone, "rel_height": float(rel_h)}


# ---------------------------------------------------------------------------
# audio
# ---------------------------------------------------------------------------

def _transcribe(path):
    from src.backend.captions import transcribe_word_timings
    words = transcribe_word_timings(path)
    return words or []


def _audio_rms(path, start, end):
    """RMS amplitude of a mono 8kHz slice. 0.0 on failure."""
    import numpy as np
    dur = max(0.1, end - start)
    try:
        proc = subprocess.run(
            [_ffmpeg(), "-hide_banner", "-loglevel", "error",
             "-ss", str(start), "-t", str(dur), "-i", path,
             "-vn", "-ac", "1", "-ar", "8000", "-f", "f32le", "-"],
            capture_output=True, timeout=120)
        raw = proc.stdout or b""
        if len(raw) < 8:
            return 0.0
        arr = np.frombuffer(raw, dtype=np.float32)
        return float(np.sqrt((arr ** 2).mean()))
    except Exception:
        return 0.0


def _detect_music_bed(path, words, min_gap=1.0, duration=0.0):
    """True when non-speech segments still carry audible energy (music bed).

    With no transcript (no words), the whole track is treated as one gap,
    so a music-only short still reports its bed.
    """
    gaps = []
    prev_end = 0.0
    for w in words:
        s = float(w.get("start", 0))
        if s - prev_end >= min_gap:
            gaps.append((prev_end, s))
        prev_end = max(prev_end, float(w.get("end", s)))
    if not gaps and duration > min_gap:
        gaps.append((0.0, duration))
    if not gaps:
        return False
    rms_vals = [_audio_rms(path, a, min(b, a + 4.0)) for a, b in gaps[:4]]
    rms_vals = [v for v in rms_vals if v > 0]
    if not rms_vals:
        return False
    # speech gaps in a dry talking-head are near-silent (< -40 dBFS ~= 0.01)
    return statistics.median(rms_vals) > 0.012


# ---------------------------------------------------------------------------
# edit decision list + thumbnails
# ---------------------------------------------------------------------------

def _build_edl(shots, per_shot, words):
    """Per-shot edit list: timing + motion + caption word budget."""
    edl = []
    for i, (a, b) in enumerate(shots):
        ps = per_shot[i] if i < len(per_shot) else {}
        win = [w for w in words
               if float(w.get("end", 0)) > a and float(w.get("start", 0)) < b]
        edl.append({
            "shot": i + 1,
            "start": a, "end": b,
            "duration": round(b - a, 2),
            "motion": ps.get("motion", "static"),
            "zoom_intensity": ps.get("zoom_intensity", 0.0),
            "word_count": len(win),
            "text": " ".join(w.get("word", "") for w in win)[:220],
        })
    return edl


def _style_thumbs(path, shots, work_dir, max_thumbs=4):
    """Mid-shot JPEG thumbnails (relative to OUTPUT_DIR) for the style card."""
    from src.backend import reference_clone as rc
    thumbs = []
    if not shots:
        return thumbs
    picks = shots[:max_thumbs]
    for i, (a, b) in enumerate(picks):
        out = os.path.join(work_dir, f"style_thumb_{i:02d}.jpg")
        try:
            proc = subprocess.run(
                [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
                 "-ss", str((a + b) / 2.0), "-i", path, "-frames:v", "1",
                 "-vf", "scale=320:-1", "-q:v", "5", out],
                capture_output=True, stdin=subprocess.DEVNULL, timeout=60)
            if proc.returncode == 0 and os.path.exists(out):
                rel = os.path.relpath(out, OUTPUT_DIR).replace("\\", "/")
                # work_dir may live outside OUTPUT_DIR (adhoc analysis):
                # a "../../.." path is useless to the frontend, so fall back
                # to the absolute path instead of garbage.
                thumbs.append(out if rel.startswith("..") else rel)
        except Exception:
            continue
    return thumbs


def map_edl_to_duration(edl, ref_duration, user_duration):
    """Proportionally map a reference edit decision list onto new footage.

    Pure math (no I/O) — easy to unit test. Returns a new EDL with
    start/end/duration rescaled; motion, zoom_intensity, word_count kept.
    """
    if not edl or not ref_duration or not user_duration:
        return []
    scale = user_duration / ref_duration
    mapped = []
    for e in edl:
        a = round(e["start"] * scale, 2)
        b = round(min(e["end"] * scale, user_duration), 2)
        if b <= a:
            continue
        m = dict(e)
        m["start"], m["end"] = a, b
        m["duration"] = round(b - a, 2)
        mapped.append(m)
    return mapped
