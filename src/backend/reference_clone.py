"""
Reference-clone engine: copy a YouTube Short's structure frame-by-frame,
then rebuild it with a NEW script.

Pipeline:
    analyze_reference(url, work_dir)
        -> downloads the short (yt-dlp)
        -> detects shot boundaries (ffmpeg scene detection)
        -> estimates per-shot camera motion (numpy phase correlation)
        -> extracts palette + lighting mood per shot (PIL)
        -> returns a JSON-serializable shot plan

The orchestrator's `clone-short` node then:
    1. generates the NEW reel script with exactly len(shots) scenes,
       each scene timed to its reference shot's duration,
    2. grounds each image prompt in the script + the reference shot's
       composition/palette hint,
    3. copies each reference shot's camera move literally as the
       image-to-video motion script.

Everything is local and free (yt-dlp + ffmpeg + numpy + PIL).
"""

import base64
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=kw.pop("timeout", 300), **kw)


def _have(cmd):
    return shutil.which(cmd) is not None


def _ffmpeg():
    """Resolved ffmpeg binary — system PATH first, else auto-installed bundle."""
    p = shutil.which("ffmpeg")
    if p:
        return p
    try:
        from src.backend.auto_bootstrap import ffmpeg_bin
        return ffmpeg_bin()
    except Exception:
        return None


def _ffprobe():
    """Resolved ffprobe binary, or None when unavailable (callers fall back)."""
    p = shutil.which("ffprobe")
    if p:
        return p
    try:
        from src.backend.auto_bootstrap import ffprobe_bin
        return ffprobe_bin()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 1. download
# ---------------------------------------------------------------------------

def download_reference(url, work_dir):
    """Download a YouTube Short (or any video URL) to work_dir. Returns path."""
    try:
        import yt_dlp  # noqa
    except ImportError:
        # Last-resort self-heal: try installing right here (the run gate
        # normally handles this via auto_bootstrap before we get here).
        try:
            from src.backend.auto_bootstrap import ensure_pip
            ok, msg, _ = ensure_pip("yt_dlp", "yt-dlp")
            if not ok:
                raise RuntimeError(msg)
            import yt_dlp  # noqa
        except ImportError:
            raise RuntimeError(
                "yt-dlp is not installed. Install it with: pip install yt-dlp "
                "(or re-run setup_agent.bat)")
    os.makedirs(work_dir, exist_ok=True)
    out_tpl = os.path.join(work_dir, "reference.%(ext)s")
    cmd = [sys.executable, "-m", "yt_dlp",
           "--no-playlist",
           "-f", "bv*[height<=720]+ba/b[height<=720]/b",
           "--merge-output-format", "mp4",
           "-o", out_tpl,
           "--no-warnings",
           url]
    r = _run(cmd, timeout=600)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "")[-600:]
        raise RuntimeError(f"Could not download reference video: {err}")
    for ext in ("mp4", "webm", "mkv"):
        p = os.path.join(work_dir, f"reference.{ext}")
        if os.path.exists(p):
            print(f"[reference_clone] downloaded -> {p}")
            return p
    # fallback: whatever got written
    cands = [f for f in os.listdir(work_dir) if f.startswith("reference.")]
    if cands:
        return os.path.join(work_dir, cands[0])
    raise RuntimeError("yt-dlp finished but no video file was produced.")


# ---------------------------------------------------------------------------
# 2. probe
# ---------------------------------------------------------------------------

def probe(path):
    """Return (duration_s, fps, width, height) via ffprobe, or ffmpeg -i fallback."""
    fp = _ffprobe()
    if fp:
        r = _run([fp, "-v", "quiet", "-print_format", "json",
                  "-show_format", "-show_streams", path])
        try:
            info = json.loads(r.stdout)
        except Exception:
            raise RuntimeError("ffprobe could not read the reference video.")
        duration = float(info["format"].get("duration") or 0)
        vstream = next((s for s in info.get("streams", [])
                        if s.get("codec_type") == "video"), {})
        fps_s = vstream.get("avg_frame_rate") or vstream.get("r_frame_rate") or "30/1"
        try:
            num, den = fps_s.split("/")
            fps = float(num) / float(den or 1)
        except Exception:
            fps = 30.0
        return duration, fps, int(vstream.get("width") or 0), int(vstream.get("height") or 0)
    # No ffprobe (e.g. imageio-ffmpeg bundle): parse `ffmpeg -i` stderr.
    ff = _ffmpeg()
    if not ff:
        raise RuntimeError("no ffmpeg/ffprobe found — auto-install failed; install ffmpeg manually.")
    r = _run([ff, "-hide_banner", "-i", path], timeout=60)
    log = r.stderr or ""
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", log)
    duration = float(m.group(1)) * 3600 + float(m.group(2)) * 60 + float(m.group(3)) if m else 0.0
    m = re.search(r"Video:.*?\s(\d+)x(\d+)[,\s]", log)
    w, h = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    m = re.search(r"(\d+(?:\.\d+)?)\s*fps", log)
    fps = float(m.group(1)) if m else 30.0
    return duration, fps, w, h


# ---------------------------------------------------------------------------
# 3. shot detection
# ---------------------------------------------------------------------------

def detect_shots(path, duration, threshold=0.35, min_shot=0.4):
    """Split the video into shots via ffmpeg scene detection.

    Returns [(start_s, end_s), ...]. Falls back to fixed 3s chunks when
    detection yields nothing usable.
    """
    cuts = []
    if _ffmpeg():
        # select frames where a scene change scores above threshold
        vf = f"select='gt(scene\\,{threshold})',showinfo"
        ff = _ffmpeg()
        r = _run([ff, "-hide_banner", "-i", path, "-vf", vf,
                  "-vsync", "0", "-f", "null", "-"], timeout=300)
        log = r.stderr or ""
        for m in re.finditer(r"pts_time:([0-9.]+)", log):
            cuts.append(float(m.group(1)))
    # build shot list from cut points
    bounds = [0.0] + sorted(cuts) + [duration]
    shots = []
    for a, b in zip(bounds, bounds[1:]):
        if b - a >= min_shot:
            shots.append((round(a, 2), round(b, 2)))
    if not shots:
        # total fallback: fixed 3s chunks
        t = 0.0
        while t < duration:
            shots.append((round(t, 2), round(min(duration, t + 3.0), 2)))
            t += 3.0
    # merge a trailing sliver into the previous shot
    if len(shots) > 1 and shots[-1][1] - shots[-1][0] < 0.8:
        shots[-2] = (shots[-2][0], shots[-1][1])
        shots.pop()
    print(f"[reference_clone] {len(shots)} shots detected "
          f"(cuts at {[round(c,1) for c in cuts][:12]})")
    return shots


# ---------------------------------------------------------------------------
# 4. frame extraction (PIL thumbnails for analysis)
# ---------------------------------------------------------------------------

def _grab_frame(path, t, width=192):
    """Extract one frame at t seconds as a PIL grayscale thumbnail."""
    from PIL import Image
    tmp = os.path.join(os.path.dirname(path) or ".", "_rc_frame.png")
    ff = _ffmpeg()
    r = _run([ff, "-hide_banner", "-loglevel", "error",
              "-ss", str(max(0, t)), "-i", path,
              "-frames:v", "1", "-vf", f"scale={width}:-1", tmp])
    if r.returncode != 0 or not os.path.exists(tmp):
        return None
    try:
        img = Image.open(tmp).convert("L")
        return img
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def extract_keyframes(path, shots, out_dir, thumb_w=320):
    """Save a mid-shot JPEG keyframe per shot. Returns [paths]."""
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    kf_paths = []
    for i, (a, b) in enumerate(shots):
        mid = (a + b) / 2.0
        tmp = os.path.join(out_dir, f"keyframe_{i:02d}.jpg")
        ff = _ffmpeg()
        r = _run([ff, "-hide_banner", "-loglevel", "error",
                  "-ss", str(mid), "-i", path, "-frames:v", "1",
                  "-vf", f"scale={thumb_w}:-1", "-q:v", "4", tmp])
        if r.returncode == 0 and os.path.exists(tmp):
            kf_paths.append(tmp)
        else:
            kf_paths.append(None)
    return kf_paths


def _thumb_b64(pil_img, width=160):
    from PIL import Image
    img = pil_img.copy()
    img.thumbnail((width, width), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=60)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------------------
# 5. camera-motion estimation (numpy phase correlation + zoom search)
# ---------------------------------------------------------------------------

def _phase_shift(a, b):
    """Content displacement of b relative to a, in pixels (numpy only).

    Positive dx = content moved right, positive dy = content moved down.
    (Raw phase correlation peaks at the negated shift, hence the flip.)
    """
    import numpy as np
    fa = np.fft.fft2(a)
    fb = np.fft.fft2(b)
    cross = fa * np.conj(fb)
    cross /= (np.abs(cross) + 1e-8)
    corr = np.abs(np.fft.ifft2(cross))
    peak = np.unravel_index(np.argmax(corr), corr.shape)
    dy, dx = peak[0], peak[1]
    h, w = a.shape
    if dy > h // 2:
        dy -= h
    if dx > w // 2:
        dx -= w
    return float(-dx), float(-dy)


def _best_zoom(a, b_pil):
    """Find which uniform scale of b best matches a. Returns (scale, score)."""
    import numpy as np
    from PIL import Image
    best = (1.0, -1.0)
    for s in (0.85, 0.92, 0.97, 1.0, 1.03, 1.08, 1.18):
        w, h = b_pil.size
        zb = b_pil.resize((max(8, int(w * s)), max(8, int(h * s))), Image.BILINEAR)
        # Compare fully-overlapping patches (no padded borders: they would
        # tank the score for s < 1 and bias the search toward zoom-out).
        zw, zh = zb.size
        aw, ah = a.shape[1], a.shape[0]
        a_patch = a
        if zw >= aw and zh >= ah:
            x0, y0 = (zw - aw) // 2, (zh - ah) // 2
            zb = zb.crop((x0, y0, x0 + aw, y0 + ah))
        else:
            ax0, ay0 = (aw - zw) // 2, (ah - zh) // 2
            a_patch = a[ay0:ay0 + zh, ax0:ax0 + zw]
        zb = np.asarray(zb, dtype=np.float32)
        an = (a_patch - a_patch.mean()) / (a_patch.std() + 1e-8)
        bn = (zb - zb.mean()) / (zb.std() + 1e-8)
        score = float((an * bn).mean())
        if score > best[1]:
            best = (s, score)
    return best


def estimate_motion(path, shot):
    """Classify the dominant camera move of one shot.

    Measures motion across short (~0.33s) frame pairs at a few probe
    positions, then aggregates to per-second rates. Small intervals keep
    phase correlation reliable (large zoom between distant frames breaks
    it); per-second rates classify the move.

    Returns one of: static, zoom-in, zoom-out, pan-left, pan-right,
    pan-up, pan-down, dolly-in, dolly-out.
    """
    import numpy as np
    a, b = shot
    dur = b - a
    if dur <= 0.2:
        return "static"

    # probe positions spread through the shot; each pair spans GAP seconds
    GAP = 0.33
    if dur >= 1.6:
        n_probes = 3
    elif dur >= 0.9:
        n_probes = 2
    else:
        n_probes = 1
    if n_probes == 1:
        starts = [a + 0.1]
    else:
        starts = [a + 0.1 + i * (dur - 0.1 - GAP) / (n_probes - 1)
                  for i in range(n_probes)]

    w = None
    zoom_prod, total_dt = 1.0, 0.0
    shift_x, shift_y = 0.0, 0.0
    flat = False
    for t0 in starts:
        t1 = min(b - 0.05, t0 + GAP)
        if t1 - t0 < 0.12:
            continue
        f0, f1 = _grab_frame(path, t0), _grab_frame(path, t1)
        if f0 is None or f1 is None:
            continue
        if w is None:
            w = f0.size[0]
            # Flat field (fade-to-black, solid sky...): correlation is
            # meaningless noise — nothing measurable is moving.
            if float(np.asarray(f0, dtype=np.float32).std()) < 3.0:
                flat = True
                break
        arr0 = np.asarray(f0, dtype=np.float32)
        dx, dy = _phase_shift(arr0, np.asarray(f1, dtype=np.float32))
        s, _ = _best_zoom(arr0, f1)
        # s shrinks/grows b to match a: content grew (zoom-IN) when s < 1
        zoom_prod *= 1.0 / s
        shift_x += dx
        shift_y += dy
        total_dt += (t1 - t0)

    if total_dt <= 0 or w is None or flat:
        return "static"

    # per-second rates
    zoom_rate = zoom_prod ** (1.0 / total_dt)
    sx_rate = (shift_x / total_dt) / w   # fraction of frame width per sec
    sy_rate = (shift_y / total_dt) / w
    pan_mag = math.hypot(sx_rate, sy_rate)

    zoom_in = zoom_rate > 1.015   # >1.5%/s sustained push-in
    zoom_out = zoom_rate < 1 / 1.015
    panning = pan_mag > 0.04      # >4% of frame width per second

    if zoom_in and panning:
        return "dolly-in"
    if zoom_out and panning:
        return "dolly-out"
    if zoom_in:
        return "zoom-in"
    if zoom_out:
        return "zoom-out"
    if panning:
        # content shift is opposite the camera move
        if abs(sx_rate) >= abs(sy_rate):
            return "pan-left" if sx_rate > 0 else "pan-right"
        return "pan-down" if sy_rate > 0 else "pan-up"
    return "static"


MOTION_TO_PROMPT = {
    "static":    "subtle slow parallax drift on a near-static tripod shot, gentle floating dust, cinematic",
    "zoom-in":   "slow cinematic push-in toward the subject, volumetric light, 4k smooth motion",
    "zoom-out":  "slow cinematic pull-back reveal, expanding frame, 4k smooth motion",
    "pan-left":  "smooth slow pan to the left across the scene, cinematic glide",
    "pan-right": "smooth slow pan to the right across the scene, cinematic glide",
    "pan-up":    "slow tilt-up reveal, rising camera, cinematic",
    "pan-down":  "slow tilt-down, descending camera reveal, cinematic",
    "dolly-in":  "dolly push-in with slight lateral drift, dynamic depth, cinematic",
    "dolly-out": "dolly pull-back with lateral drift, expanding depth, cinematic",
}


# ---------------------------------------------------------------------------
# 6. palette + mood
# ---------------------------------------------------------------------------

def palette_and_mood(keyframe_path):
    """Return ([hex colors], mood_word, brightness_word)."""
    from PIL import Image
    try:
        img = Image.open(keyframe_path).convert("RGB")
    except Exception:
        return [], "neutral", "balanced"
    small = img.resize((96, 96), Image.BILINEAR)
    q = small.quantize(colors=8, method=2)
    pal = q.getpalette()[:8 * 3]
    counts = sorted(q.getcolors(), reverse=True)
    hexes = []
    for cnt, idx in counts:
        r, g, b = pal[idx * 3:idx * 3 + 3]
        # skip near-gray / near-black / near-white swatches
        if max(r, g, b) - min(r, g, b) < 24:
            continue
        hexes.append(f"#{r:02x}{g:02x}{b:02x}")
        if len(hexes) == 3:
            break
    gray = small.convert("L")
    import numpy as np
    lum = float(np.asarray(gray).mean())
    if lum < 60:
        mood, bright = "dark and moody", "low-key"
    elif lum < 110:
        mood, bright = "moody cinematic", "dramatic"
    elif lum < 170:
        mood, bright = "balanced", "natural"
    else:
        mood, bright = "bright and airy", "high-key"
    return hexes, mood, bright


def composition_hint(hexes, mood, bright):
    bits = []
    if hexes:
        bits.append(f"color grade leaning on {', '.join(hexes)}")
    bits.append(f"{mood} {bright} lighting")
    bits.append("vertical 9:16 cinematic framing like the reference")
    return "Match this reference look: " + ", ".join(bits) + "."


# ---------------------------------------------------------------------------
# 7. script splitting (custom-script mode)
# ---------------------------------------------------------------------------

def split_script_for_shots(script_text, shots):
    """Distribute a pasted script across shots, proportional to shot duration.

    Returns [narration_per_shot]."""
    import re as _re
    sents = [_re.sub(r"\s+", " ", s).strip()
             for s in _re.split(r"(?<=[.!?])\s+", script_text.strip())]
    sents = [s for s in sents if s]
    if not sents:
        return [""] * len(shots)
    total = sum(b - a for a, b in shots) or 1.0
    out, idx = [], 0
    for i, (a, b) in enumerate(shots):
        # share of sentences proportional to share of duration
        if i == len(shots) - 1:
            chunk = sents[idx:]
        else:
            want = max(1, round(len(sents) * (b - a) / total))
            chunk = sents[idx:idx + want]
            idx += len(chunk)
        out.append(" ".join(chunk))
    return out


# ---------------------------------------------------------------------------
# 8. main entry
# ---------------------------------------------------------------------------

def analyze_reference(url, work_dir="data/reference_clone"):
    """Full analysis. Returns a JSON-serializable shot plan dict."""
    os.makedirs(work_dir, exist_ok=True)
    video_path = download_reference(url, work_dir)
    duration, fps, w, h = probe(video_path)
    if duration <= 0:
        raise RuntimeError("Could not read the reference video's duration.")
    # keep the plan tight: cap at 24 shots for very cutty edits
    shots = detect_shots(video_path, duration)[:24]
    kf_dir = os.path.join(work_dir, "keyframes")
    kf_paths = extract_keyframes(video_path, shots, kf_dir)

    plan_shots = []
    for i, ((a, b), kf) in enumerate(zip(shots, kf_paths)):
        dur = round(b - a, 2)
        move = estimate_motion(video_path, (a, b))
        if kf:
            hexes, mood, bright = palette_and_mood(kf)
            hint = composition_hint(hexes, mood, bright)
            try:
                from PIL import Image
                thumb = _thumb_b64(Image.open(kf))
            except Exception:
                thumb = None
        else:
            hexes, mood, bright, hint, thumb = [], "neutral", "balanced", "", None
        plan_shots.append({
            "index": i,
            "start": a,
            "end": b,
            "duration": dur,
            "camera_move": move,
            "motion_prompt": MOTION_TO_PROMPT.get(move, MOTION_TO_PROMPT["static"]),
            "palette": hexes,
            "mood": mood,
            "lighting": bright,
            "composition_hint": hint,
            "keyframe_thumb": thumb,
        })
        print(f"[reference_clone] shot {i + 1}: {dur}s, move={move}, "
              f"palette={hexes or 'n/a'}")

    return {
        "url": url,
        "video_path": video_path,
        "duration": round(duration, 2),
        "fps": round(fps, 2),
        "resolution": [w, h],
        "shot_count": len(plan_shots),
        "shots": plan_shots,
    }
