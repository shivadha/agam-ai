"""
AGAM — Long video -> viral Shorts auto-cutter.

Pipeline:
  1. Transcribe the video's audio with faster-whisper *through*
     src.backend.captions (real word timestamps, cached as
     <video>.words.json — never reimplemented here).
  2. find_viral_moments(): sliding windows over the word timeline, scored by
     hook patterns (questions, numbers, "you", secrets, mistakes, "free",
     superlatives, "how to", ...). Windows prefer sentence boundaries and
     never overlap.
  3. cut_shorts(): ffmpeg trims each winning window, center-crops to 9:16,
     scales to 1080x1920 and burns word-synced captions (SRT generated from
     the same word timings, timestamps rebased to the trimmed clip).

Everything is best-effort: no speech detected -> returns [] instead of
crashing. Only deps beyond stdlib: faster-whisper (via captions.py) and
ffmpeg (resolved like dubbing.py: imageio-ffmpeg first, PATH fallback).
"""

import os
import re
import subprocess

from .captions import transcribe_word_timings, chunk_words
from .dubbing import _ffmpeg_exe

# (pattern, points) — a window's text gets points for each pattern it matches.
HOOK_PATTERNS = [
    (re.compile(r"\?"), 2.0),                                   # question hook
    (re.compile(r"\bhow to\b", re.IGNORECASE), 2.0),
    (re.compile(r"\bsecret(s)?\b", re.IGNORECASE), 2.0),
    (re.compile(r"\bmistake(s)?\b", re.IGNORECASE), 2.0),
    (re.compile(r"\b\d+(\.\d+)?\b"), 1.5),                      # numbers / stats
    (re.compile(r"\bfree\b", re.IGNORECASE), 1.5),
    (re.compile(r"\bstop\b", re.IGNORECASE), 1.5),
    (re.compile(r"\b(you|your|yours)\b", re.IGNORECASE), 1.0),  # direct address
    (re.compile(r"\b(best|biggest|worst|fastest|easiest|most|never|always|"
                r"ultimate|insane|crazy|shocking|unbelievable|warning)\b",
                re.IGNORECASE), 1.0),                           # superlatives
    (re.compile(r"!"), 0.5),
]

_SENTENCE_END = re.compile(r"[.!?…]+$")


def _sentence_start_indices(words):
    """Indices where a new sentence (hence a clean cut point) begins."""
    starts = [0]
    for i, w in enumerate(words[:-1]):
        if _SENTENCE_END.search(w["word"].strip()):
            starts.append(i + 1)
    return sorted(set(starts))


def _choose_end(words, s_idx, s_time, min_sec, max_sec):
    """Pick the end word index: nearest sentence end inside [min,max].

    Falls back to the max duration, or the last word when the video tail is
    shorter than min_sec.
    """
    target_min = s_time + min_sec
    target_max = s_time + max_sec
    last_ok = None
    for i in range(s_idx, len(words)):
        end_t = words[i]["end"]
        if end_t < target_min:
            continue
        if end_t > target_max:
            break
        last_ok = i
        if _SENTENCE_END.search(words[i]["word"].strip()):
            return i  # clean sentence end inside the window
    if last_ok is not None:
        return last_ok
    # Tail shorter than min_sec: take everything to the end.
    return len(words) - 1


def _score_window(window_words, text):
    score = 1.0
    for pattern, points in HOOK_PATTERNS:
        if pattern.search(text):
            score += points
    dur = max(0.01, window_words[-1]["end"] - window_words[0]["start"])
    wps = len(window_words) / dur
    if wps < 1.0:
        score *= 0.5  # sparse speech — probably dead air
    if 25 <= dur <= 50:
        score += 1.0  # Shorts sweet spot
    return round(score, 2)


def find_viral_moments(words, num_shorts=3, min_sec=20, max_sec=58):
    """Score sliding windows over word timestamps; return the best non-overlapping.

    Returns [{'start_sec', 'end_sec', 'score', 'text'}] sorted by start time.
    """
    if not words:
        return []

    starts = _sentence_start_indices(words)
    # Sparse punctuation (e.g. unpunctuated transcripts): add fallback starts
    # so short videos still yield candidates.
    if len(starts) < 6 and len(words) > 12:
        step = max(1, len(words) // 10)
        starts = sorted(set(starts) | set(range(0, len(words), step)))

    candidates = []
    for s_idx in starts:
        s_time = words[s_idx]["start"]
        e_idx = _choose_end(words, s_idx, s_time, min_sec, max_sec)
        if e_idx <= s_idx:
            continue
        e_time = words[e_idx]["end"]
        if e_time - s_time > max_sec + 0.5:
            continue
        if e_time - s_time < min(10.0, min_sec):
            continue  # fragment too short to stand alone
        win_words = words[s_idx:e_idx + 1]
        text = " ".join(w["word"] for w in win_words).strip()
        if not text:
            continue
        candidates.append({
            "start_sec": round(s_time, 2),
            "end_sec": round(e_time, 2),
            "score": _score_window(win_words, text),
            "text": text,
        })

    # Greedy non-overlapping pick, best score first.
    candidates.sort(key=lambda c: c["score"], reverse=True)
    picked = []
    for c in candidates:
        overlaps = any(
            not (c["end_sec"] <= p["start_sec"] or c["start_sec"] >= p["end_sec"])
            for p in picked
        )
        if not overlaps:
            picked.append(c)
        if len(picked) >= max(1, num_shorts):
            break

    picked.sort(key=lambda c: c["start_sec"])
    return picked


def _write_srt(window_words, srt_path, offset=0.0):
    """Write an SRT from word timings, rebased so t=0 is the trimmed clip start."""
    def ts(t):
        t = max(0.0, t - offset)
        ms = int(round(t * 1000))
        h, rem = divmod(ms, 3600000)
        m, rem = divmod(rem, 60000)
        s, ms = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    chunks = chunk_words(window_words, max_words=4, max_gap=0.45)
    lines = []
    for i, ch in enumerate(chunks, 1):
        lines.append(str(i))
        lines.append(f"{ts(ch['start'])} --> {ts(ch['end'])}")
        lines.append(" ".join(ch["words"]))
        lines.append("")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return srt_path


def _escape_subtitles_path(path):
    """Escape a file path for ffmpeg's subtitles filter (filter-parser level).

    subprocess passes argv without a shell, so only ffmpeg's own filter
    parser needs handling: backslashes -> forward slashes, then escape
    ':', ''', ',', '[', ']' (Windows drive letters included).
    """
    p = os.path.abspath(path).replace("\\", "/")
    return (p.replace(":", "\\:")
             .replace("'", "\\'")
             .replace(",", "\\,")
             .replace("[", "\\[")
             .replace("]", "\\]"))


def _cut_one(video_path, moment, srt_path, out_path):
    dur = round(moment["end_sec"] - moment["start_sec"], 2)
    vf = (
        "crop=ih*9/16:ih,"                      # center-crop to 9:16
        "scale=1080:1920,"                      # Shorts canvas
        "subtitles='{}':".format(_escape_subtitles_path(srt_path)) +
        "force_style='FontSize=26,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H80000000,BorderStyle=1,Outline=2,Shadow=0,"
        "MarginV=200,Alignment=2'"
    )
    cmd = [
        _ffmpeg_exe(), "-y",
        "-i", video_path,
        "-ss", str(moment["start_sec"]),   # output seeking: frame-accurate
        "-t", str(dur),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        out_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if proc.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError(f"ffmpeg cut failed: {proc.stderr[-600:]}")
    return out_path


def _make_title(text, max_words=8, max_chars=100):
    """First ~8 words of the window, title-cased (apostrophe-safe), <=100 chars."""
    short = " ".join(text.strip().split()[:max_words]).strip().rstrip(".,!?;:")
    titled = re.sub(r"[A-Za-z]+(?:'[A-Za-z]+)?",
                    lambda m: m.group(0).capitalize(), short)
    return (titled[:max_chars].rstrip() or "Viral Short")


def cut_shorts(video_path, out_dir, num_shorts=3, min_sec=20, max_sec=58):
    """Cut the best viral moments out of a long video as vertical Shorts.

    Returns [{'path', 'title', 'start_sec', 'end_sec', 'score'}].
    Returns [] (never raises) when there is no speech to cut from.
    """
    if not video_path or not os.path.exists(video_path):
        print(f"[shorts_cutter] Video not found: {video_path}")
        return []
    os.makedirs(out_dir, exist_ok=True)

    # Reuses captions.py — real faster-whisper word timings, cached next
    # to the video as <name>.words.json.
    words = transcribe_word_timings(video_path)
    if not words:
        print("[shorts_cutter] No speech detected — nothing to cut.")
        return []

    moments = find_viral_moments(words, num_shorts=num_shorts,
                                 min_sec=min_sec, max_sec=max_sec)
    if not moments:
        print("[shorts_cutter] No cuttable moments found.")
        return []

    base = os.path.splitext(os.path.basename(video_path))[0]
    results = []
    for i, m in enumerate(moments, 1):
        try:
            win_words = [w for w in words
                         if w["start"] >= m["start_sec"] - 0.05
                         and w["end"] <= m["end_sec"] + 0.05]
            srt_path = os.path.join(out_dir, f"{base}_short{i}.srt")
            _write_srt(win_words, srt_path, offset=m["start_sec"])
            out_path = os.path.join(out_dir, f"{base}_short{i}.mp4")
            _cut_one(video_path, m, srt_path, out_path)
            if os.path.getsize(out_path) > 0:
                results.append({
                    "path": out_path,
                    "title": _make_title(m["text"]),
                    "start_sec": m["start_sec"],
                    "end_sec": m["end_sec"],
                    "score": m["score"],
                })
                print(f"[shorts_cutter] Short {i}/{len(moments)} -> {out_path} "
                      f"({m['start_sec']:.1f}s–{m['end_sec']:.1f}s, score {m['score']})")
        except Exception as e:
            print(f"[shorts_cutter] Short {i} failed (others continue): {e}")
    return results
