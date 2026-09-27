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


def timed_words_from_edge_boundaries(boundaries):
    """Convert edge-tts boundary chunks to [{'word','start','end'}] (seconds).

    edge-tts reports the EXACT words it spoke with 100ns-tick offsets, so
    these timings need no transcription and can never mistranscribe.
    Falls back to interpolating words inside SentenceBoundary chunks when
    the service only returns sentence boundaries.
    """
    words = []
    wbs = [b for b in (boundaries or []) if b.get("type") == "WordBoundary"]
    if wbs:
        for b in wbs:
            text = (b.get("text") or "").strip()
            if not text:
                continue
            try:
                start = float(b.get("offset", 0)) / 10_000_000
                end = (float(b.get("offset", 0)) + float(b.get("duration", 0))) / 10_000_000
            except (TypeError, ValueError):
                continue
            words.append({"word": text, "start": round(start, 2), "end": round(end, 2)})
        return words
    # SentenceBoundary interpolation (same math voice_gen used for its SRT).
    for sb in [b for b in (boundaries or []) if b.get("type") == "SentenceBoundary"]:
        try:
            offset = float(sb.get("offset", 0)) / 10_000_000
            duration = float(sb.get("duration", 0)) / 10_000_000
        except (TypeError, ValueError):
            continue
        sentence_words = (sb.get("text") or "").split()
        if not sentence_words or duration <= 0:
            continue
        total_chars = sum(len(w) for w in sentence_words) or 1
        cur = offset
        for w in sentence_words:
            w_dur = duration * len(w) / total_chars
            words.append({"word": w, "start": round(cur, 2),
                          "end": round(cur + w_dur, 2)})
            cur += w_dur
    return words


def _norm_word(w):
    import re as _re
    return _re.sub(r"[^\w']", "", (w or "").lower())


def reconcile_words(script_words, timed_words):
    """Return timed words whose WORDS are the script's (what was spoken).

    faster-whisper (tiny.en) mistranscribes accented TTS, which used to put
    wrong words in the captions while the voice said the script. This aligns
    the known script words to the timed words with difflib and re-emits the
    SCRIPT words on the timed words' timestamps, so captions can never
    disagree with the voice. Unmatched script words interpolate between
    neighbouring timings; stray timed words are dropped. Output timings are
    monotonic with end >= start.
    """
    import difflib
    script_words = [w for w in (script_words or []) if (w or "").strip()]
    timed_words = [t for t in (timed_words or [])
                   if t and (t.get("word") or "").strip()]
    if not script_words or not timed_words:
        return []
    norm_script = [_norm_word(w) for w in script_words]
    norm_timed = [_norm_word(t["word"]) for t in timed_words]
    sm = difflib.SequenceMatcher(None, norm_script, norm_timed, autojunk=False)
    out = []

    def _span(a, b):
        s = float(timed_words[a]["start"])
        e = float(timed_words[b]["end"])
        return s, max(e, s + 0.01)

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for si, tj in zip(range(i1, i2), range(j1, j2)):
                s, e = _span(tj, tj)
                out.append({"word": script_words[si], "start": round(s, 2),
                            "end": round(e, 2)})
        elif tag == "replace":
            n_s, n_t = i2 - i1, j2 - j1
            if n_t <= 0:
                continue
            t0, t1 = float(timed_words[j1]["start"]), float(timed_words[j2 - 1]["end"])
            t1 = max(t1, t0 + 0.01 * n_s)
            if n_s == n_t:
                pairs = zip(range(i1, i2), range(j1, j2))
                for si, tj in pairs:
                    s, e = _span(tj, tj)
                    out.append({"word": script_words[si], "start": round(s, 2),
                                "end": round(e, 2)})
            else:
                # Spread the timed span evenly across the script words.
                step = (t1 - t0) / n_s
                for k, si in enumerate(range(i1, i2)):
                    s = t0 + k * step
                    out.append({"word": script_words[si], "start": round(s, 2),
                                "end": round(s + step, 2)})
        elif tag == "delete":
            # Script words the transcription missed: interpolate between the
            # nearest timed neighbours.
            prev_end = float(out[-1]["end"]) if out else 0.0
            nxt_start = (float(timed_words[j1]["start"]) if j1 < len(timed_words)
                         else prev_end + 0.3 * (i2 - i1))
            n = i2 - i1
            span = max(0.0, nxt_start - prev_end)
            step = span / n if n else 0
            for k, si in enumerate(range(i1, i2)):
                s = prev_end + k * step
                out.append({"word": script_words[si], "start": round(s, 2),
                            "end": round(s + max(step, 0.05), 2)})
        # 'insert': stray timed words not in the script — dropped.

    # Monotonicity repair: timings must never run backwards.
    for k in range(1, len(out)):
        if out[k]["start"] < out[k - 1]["start"]:
            out[k]["start"] = out[k - 1]["start"]
        if out[k]["end"] < out[k]["start"]:
            out[k]["end"] = round(out[k]["start"] + 0.05, 2)
    return out
