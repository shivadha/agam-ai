"""
AGAM — Real word-level caption timings.

The old pipeline synthesized SRT subtitles with *estimated* timings (each
segment's duration was divided evenly across its words), so the karaoke
highlight drifted out of sync with the actual speech.

This module uses faster-whisper (already a project dependency) with
word_timestamps=True to get REAL per-word start/end times from the rendered
TTS audio, then groups words into display chunks. Results are cached next to
the audio file as <name>.words.json so repeat renders are instant.

Everything here is best-effort: if faster-whisper is missing or fails, the
caller falls back to the old estimated timings and the render continues.
"""

import json
import os

# Default model: tiny.en is ~75MB, fast on CPU (~5-15s for a 60s Short).
# Override with AGAM_WHISPER_MODEL=base.en for better accuracy.
DEFAULT_MODEL = os.environ.get("AGAM_WHISPER_MODEL", "tiny.en")


def transcribe_word_timings(audio_path, model_size=None):
    """Return [{'word', 'start', 'end'}, ...] for the audio, or [] on failure."""
    if not audio_path or not os.path.exists(audio_path):
        return []
    model_size = model_size or DEFAULT_MODEL
    cache_path = os.path.splitext(audio_path)[0] + ".words.json"

    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if cached:
                print(f"[captions] Loaded cached word timings ({len(cached)} words).")
                return cached
        except Exception:
            pass

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("[captions] faster-whisper not installed — skipping real word timings.")
        return []

    try:
        print(f"[captions] Transcribing word timings with faster-whisper ({model_size})...")
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(audio_path, word_timestamps=True, language="en")
        words = []
        for seg in segments:
            for w in (seg.words or []):
                text = (w.word or "").strip()
                if text:
                    words.append({
                        "word": text,
                        "start": round(float(w.start), 2),
                        "end": round(float(w.end), 2),
                    })
        if words:
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(words, f)
            except Exception:
                pass
            print(f"[captions] Got {len(words)} real word timings.")
        return words
    except Exception as e:
        print(f"[captions] Word transcription failed (will use estimated timings): {e}")
        return []


def chunk_words(words, max_words=4, max_gap=0.45):
    """Group word timings into caption display chunks.

    A new chunk starts after max_words words or a pause longer than max_gap.
    Returns [{'words': [...], 'start': s, 'end': e, 'timings': [(w,s,e)...]}].
    """
    chunks = []
    cur = []
    for w in words:
        if cur and (len(cur) >= max_words or (w["start"] - cur[-1]["end"]) > max_gap):
            chunks.append(cur)
            cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)

    out = []
    for c in chunks:
        out.append({
            "words": [w["word"] for w in c],
            "start": c[0]["start"],
            "end": c[-1]["end"],
            "timings": [(w["word"], w["start"], w["end"]) for w in c],
        })
    return out


def load_word_timings(word_timings_path):
    """Load cached timings; returns [] if missing/invalid."""
    if not word_timings_path or not os.path.exists(word_timings_path):
        return []
    try:
        with open(word_timings_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []
