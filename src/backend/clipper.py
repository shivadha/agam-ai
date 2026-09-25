"""Viral clip maker: 9:16 YouTube Shorts with word-highlight (karaoke) subtitles.

Standards followed (YouTube Shorts, 2026):
  * Canvas: 1080x1920, 9:16, H.264 + AAC, MP4 with faststart.
  * Length: <= 3 minutes (Shorts limit since Oct 2024); default 20-58 s.
  * Captions: the viral "karaoke" style -- bold white words, the word being
    spoken highlighted in a bright colour, max ~3 words per line, centred in
    the lower third but ABOVE the bottom UI safe zone (like/comment/share
    buttons and the progress bar cover roughly the bottom 15%).
  * Reframe: face-tracked 9:16 crop keeps the speaker centred; falls back to a
    plain centre crop when OpenCV is unavailable or no face is found.
  * Hook-first: clip windows are picked by the viral-moment scorer
    (hook words, questions, numbers, emotion) and trimmed to start on the
    first spoken word so there is no dead air.

Everything is local and free: faster-whisper for word timings, ffmpeg/libass
for the burn-in, OpenCV Haar cascades (optional) for face tracking.
"""

import math
import os
import re
import shutil
import statistics
import subprocess

from src.backend.captions import transcribe_word_timings
from src.backend.shorts_cutter import find_viral_moments, _make_title

# ---------------------------------------------------------------------------
# Highlight colours (ASS &HAABBGGRR)
# ---------------------------------------------------------------------------

HIGHLIGHTS = {
    "yellow": "&H0000FFFF",
    "lime":   "&H0000FF00",
    "cyan":   "&H00FFFF00",
    "orange": "&H000080FF",
    "pink":   "&H00FF00FF",
    "white":  "&H00FFFFFF",
}

WHITE = "&H00FFFFFF"
BLACK_OUTLINE = "&H80000000"

# Caption geometry for a 1080x1920 canvas.
_FONT_SIZE = 76
_MARGIN_V = 320      # distance from bottom edge: clears the Shorts UI overlay
_MAX_WORDS_PER_LINE = 3


def _ffmpeg_exe():
    return shutil.which("ffmpeg") or "ffmpeg"


def _ffprobe_exe():
    return shutil.which("ffprobe") or "ffprobe"


def _ass_time(sec):
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _esc_ass(text):
    # Braces open override blocks in ASS; newlines become \N.
    text = text.replace("{", "(").replace("}", ")")
    return text.replace("\n", " ")


def _write_ass_karaoke(window_words, ass_path, offset=0.0,
                       highlight="yellow", max_words_per_line=_MAX_WORDS_PER_LINE):
    """Write an ASS file: full phrase shown, only the spoken word highlighted.

    One Dialogue event per word, spanning that word's time slot; the current
    word is wrapped in a colour override. This is the Hormozi/viral look and
    needs no karaoke-sweep ambiguity.
    """
    hl = HIGHLIGHTS.get(highlight, HIGHLIGHTS["yellow"])
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Clip,Arial,{_FONT_SIZE},{WHITE},{WHITE},"
        f"{BLACK_OUTLINE},&H00000000,-1,0,0,0,100,100,0,0,1,3,0,2,60,60,{_MARGIN_V},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )
    events = []
    words = [_esc_ass(w["word"]) for w in window_words]
    # Chunk into short lines so at most N words are on screen at once.
    chunks = [window_words[i:i + max_words_per_line]
              for i in range(0, len(window_words), max_words_per_line)]
    wi = 0
    for chunk in chunks:
        line_words = words[wi:wi + len(chunk)]
        for j, w in enumerate(chunk):
            start = w["start"] - offset
            if j + 1 < len(chunk):
                end = chunk[j + 1]["start"] - offset
            else:
                end = w["end"] - offset + 0.12  # hold the last word briefly
            if end <= start:
                end = start + 0.08
            parts = []
            for k, lw in enumerate(line_words):
                if k == j:
                    parts.append("{\\c%s&}%s{\\c%s&}" % (hl, lw, WHITE))
                else:
                    parts.append(lw)
            text = " ".join(parts)
            events.append(
                "Dialogue: 0,%s,%s,Clip,,0,0,0,,%s"
                % (_ass_time(start), _ass_time(end), text)
            )
        wi += len(chunk)
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(events) + "\n")
    return ass_path


def _write_srt_classic(window_words, ass_path, offset=0.0):
    """Classic whole-phrase captions as ASS (same style, no word highlight)."""
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Clip,Arial,{_FONT_SIZE},{WHITE},{WHITE},"
        f"{BLACK_OUTLINE},&H00000000,-1,0,0,0,100,100,0,0,1,3,0,2,60,60,{_MARGIN_V},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )
    events = []
    chunk = []
    for w in window_words:
        chunk.append(w)
        if len(chunk) >= _MAX_WORDS_PER_LINE:
            start = chunk[0]["start"] - offset
            end = chunk[-1]["end"] - offset + 0.12
            text = _esc_ass(" ".join(x["word"] for x in chunk))
            events.append("Dialogue: 0,%s,%s,Clip,,0,0,0,,%s"
                          % (_ass_time(start), _ass_time(end), text))
            chunk = []
    if chunk:
        start = chunk[0]["start"] - offset
        end = chunk[-1]["end"] - offset + 0.12
        text = _esc_ass(" ".join(x["word"] for x in chunk))
        events.append("Dialogue: 0,%s,%s,Clip,,0,0,0,,%s"
                      % (_ass_time(start), _ass_time(end), text))
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(events) + "\n")
    return ass_path


# ---------------------------------------------------------------------------
# Smart reframe
# ---------------------------------------------------------------------------

def _probe_dims(video_path):
    """Return (width, height) via ffprobe, or (None, None)."""
    try:
        proc = subprocess.run(
            [_ffprobe_exe(), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0",
             video_path],
            capture_output=True, text=True, timeout=30)
        w, h = proc.stdout.strip().split(",")[:2]
        return int(w), int(h)
    except Exception:
        return None, None


def _smart_crop(video_path, start_sec, end_sec):
    """Face-tracked 9:16 crop box, or None to use a plain centre crop.

    Samples frames through the clip, finds the largest face in each, and
    centres the vertical crop on the median face x. Needs opencv-python
    (`pip install opencv-python`); without it we gracefully fall back.
    """
    try:
        import cv2
    except ImportError:
        return None
    try:
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if cascade.empty():
            return None
        cap = cv2.VideoCapture(video_path)
        W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if not W or not H:
            cap.release()
            return None
        centers = []
        t = start_sec
        while t < end_sec:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if ok and frame is not None:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = cascade.detectMultiScale(gray, 1.2, 5, minSize=(80, 80))
                if len(faces):
                    x, _y, w, _h = max(faces, key=lambda f: f[2] * f[3])
                    centers.append(x + w / 2.0)
            t += 0.75
        cap.release()
        if not centers:
            return None
        crop_w = int(H * 9 / 16)
        med = statistics.median(centers)
        x = int(max(0, min(W - crop_w, med - crop_w / 2.0)))
        return {"x": x, "w": crop_w, "h": H}
    except Exception:
        return None


def _escape_ass_path(path):
    # Same escaping rules as the SRT path helper: backslashes doubled,
    # colons and quotes escaped for ffmpeg's filter parser.
    p = path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    return p


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def make_clip(video_path, start_sec, end_sec, out_path, style="karaoke",
              highlight="yellow", face_track=True):
    """Cut one 9:16 clip with burned subtitles.

    Returns the output path. Raises on failure.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"video not found: {video_path}")
    if end_sec <= start_sec:
        raise ValueError("end_sec must be after start_sec")
    if end_sec - start_sec > 180:
        raise ValueError("clips are capped at 3 minutes (YouTube Shorts limit)")

    # Word timings for the whole video; slice to our window.
    words = transcribe_word_timings(video_path)
    win_words = [w for w in words if w["end"] > start_sec and w["start"] < end_sec]
    if not win_words:
        raise ValueError("no speech found in that range -- can't caption it")

    # Trim dead air: start on the first spoken word.
    start_sec = max(0.0, win_words[0]["start"] - 0.25)
    offset = start_sec

    ass_path = os.path.splitext(out_path)[0] + ".ass"
    if style == "karaoke":
        _write_ass_karaoke(win_words, ass_path, offset=offset, highlight=highlight)
    else:
        _write_srt_classic(win_words, ass_path, offset=offset)

    crop = _smart_crop(video_path, start_sec, end_sec) if face_track else None
    if crop:
        crop_f = "crop={w}:{h}:{x}:0,".format(**crop)
    else:
        crop_f = "crop=ih*9/16:ih,"
    vf = (crop_f +
          "scale=1080:1920," +
          "subtitles='{}'".format(_escape_ass_path(ass_path)))
    dur = round(end_sec - start_sec, 2)
    cmd = [
        _ffmpeg_exe(), "-y",
        "-i", video_path,
        "-ss", str(round(start_sec, 2)),
        "-t", str(dur),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        out_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    try:
        os.remove(ass_path)
    except OSError:
        pass
    if proc.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError(f"ffmpeg clip failed: {proc.stderr[-600:]}")
    return out_path


def make_clips(video_path, out_dir, num_clips=3, min_sec=20, max_sec=58,
               style="karaoke", highlight="yellow", face_track=True):
    """Auto-pick the best viral moments and render them as captioned clips.

    Returns [{'path','title','start_sec','end_sec','score'}].
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"video not found: {video_path}")
    os.makedirs(out_dir, exist_ok=True)
    words = transcribe_word_timings(video_path)
    moments = find_viral_moments(words, num_shorts=num_clips,
                                 min_sec=min_sec, max_sec=max_sec)
    base = os.path.splitext(os.path.basename(video_path))[0]
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", base)[:40] or "video"
    clips = []
    for i, m in enumerate(moments, 1):
        out_path = os.path.join(out_dir, f"{safe}_clip{i}.mp4")
        make_clip(video_path, m["start_sec"], m["end_sec"], out_path,
                  style=style, highlight=highlight, face_track=face_track)
        clips.append({
            "path": out_path,
            "title": _make_title(m["text"]),
            "start_sec": m["start_sec"],
            "end_sec": m["end_sec"],
            "score": m["score"],
        })
    return clips
