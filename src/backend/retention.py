"""
AGAM — Deterministic script retention scoring (no LLM, no API calls).

Scores a script the way a retention editor would, before any GPU time is
spent rendering it:

  score_script(scenes, format="shorts") -> {
      "score": 0-100,
      "breakdown": {"hook": x/30, "pacing": x/30, "cta": x/20, "open_loops": x/20},
      "suggestions": [...],   # actionable, reference 1-based scene numbers
      "verdict": "...",
  }

scenes may be [{"text": ...}, ...] (also accepts "narration"/"script" keys
or plain strings) or a single {"text": full_script} dict.
format is "shorts" (target 25-60 words/scene) or "longform" (80-150).
"""

import re
import statistics

BOLD_CLAIM_WORDS = {
    "secret", "secrets", "shocking", "insane", "never", "nobody", "truth",
    "exposed", "expose", "free", "stop", "warning", "crazy", "unbelievable",
    "hidden", "mistake", "mistakes", "hack", "hacks", "lie", "lies",
    "banned", "destroyed", "million", "billion",
}

CURIOSITY_GAP_PHRASES = [
    "you won't believe", "here's why", "what happened next",
    "the reason", "nobody talks about", "they don't want",
    "nobody tells you", "what nobody",
]

OPEN_LOOP_PHRASES = [
    "but first", "stay tuned", "later in this video", "here's why",
    "the truth is", "keep watching", "wait until", "coming up",
    "don't go anywhere", "in a moment", "stick around", "by the end",
]

CTA_PATTERNS = [
    r"subscrib\w*", r"\bbell\b", r"comment\w*", r"\blike\b", r"share\w*",
    r"follow\w*", r"hit\s+that",
]

QUESTION_WORDS = {"who", "what", "when", "where", "why", "how", "which", "can", "do", "does", "did", "is", "are", "have"}


def _normalize_scenes(scenes):
    if isinstance(scenes, dict):
        scenes = [scenes]
    norm = []
    for sc in scenes or []:
        if isinstance(sc, str):
            text = sc
        elif isinstance(sc, dict):
            text = sc.get("text") or sc.get("narration") or sc.get("script") or ""
        else:
            continue
        text = (text or "").strip()
        if text:
            norm.append({"text": text})
    return norm


def _word_count(text):
    return len(text.split())


def _score_hook(full_text, suggestions):
    """0-30: first ~15 words — question? number? bold claim? curiosity? you?"""
    words = full_text.split()[:15]
    hook = " ".join(words)
    low = hook.lower()
    score, notes = 0, []
    if "?" in hook or (words and words[0].lower().rstrip(",") in QUESTION_WORDS):
        score += 10
    else:
        notes.append("Scene 1: open with a question — hooks phrased as questions hold attention better.")
    if re.search(r"\d", hook):
        score += 7
    else:
        notes.append("Scene 1: put a number in the hook (\"3 reasons\", \"in 2026\") — numbers lift click-through.")
    if any(w in low for w in BOLD_CLAIM_WORDS):
        score += 7
    else:
        notes.append("Scene 1: add one bold-claim word (secret, shocking, truth, never) to raise the stakes.")
    if any(p in low for p in CURIOSITY_GAP_PHRASES):
        score += 6
    if any(w in ("you", "your", "you're") for w in low.split()):
        score += 5
    else:
        notes.append("Scene 1: speak directly to the viewer (\"you\") — second person converts curiosity into watch time.")
    score = min(30, score)
    suggestions.extend(notes)
    return score


def _score_pacing(scenes, full_text, target_lo, target_hi, suggestions):
    """0-30: words-per-scene in target band, sentence-length variance, no mega-scenes."""
    score = 0
    counts = [_word_count(s["text"]) for s in scenes]

    in_band = sum(1 for c in counts if target_lo <= c <= target_hi)
    frac = (in_band / len(counts)) if counts else 0
    score += round(15 * frac)
    for i, c in enumerate(counts, start=1):
        if c < target_lo:
            suggestions.append(
                f"Scene {i}: only {c} words (aim {target_lo}-{target_hi}) — merge it with a neighbour or add a beat."
            )
        elif c > target_hi:
            suggestions.append(
                f"Scene {i}: {c} words is heavy for this format (aim {target_lo}-{target_hi}) — split it."
            )

    sentences = [s.strip() for s in re.split(r"[.!?]+", full_text) if s.strip()]
    if len(sentences) >= 3:
        lens = [_word_count(s) for s in sentences]
        mean = statistics.mean(lens)
        cv = (statistics.pstdev(lens) / mean) if mean else 0
        if 0.3 <= cv <= 0.9:
            score += 10
        elif 0.15 <= cv <= 1.2:
            score += 6
            suggestions.append("Vary sentence length more — mix short punchy lines with longer ones to keep rhythm.")
        else:
            score += 3
            suggestions.append("Sentence rhythm is monotonous — alternate short and long sentences for better pacing.")
    else:
        score += 5

    if all(c <= 200 for c in counts):
        score += 5
    else:
        for i, c in enumerate(counts, start=1):
            if c > 200:
                suggestions.append(f"Scene {i}: {c} words will drag — split into two scenes before rendering.")
    return min(30, score)


def _score_cta(full_text, suggestions):
    """0-20: subscribe/comment/like/share patterns in the final 20% of the script."""
    words = full_text.split()
    tail = " ".join(words[int(len(words) * 0.8):]).lower()
    found = {p for p in CTA_PATTERNS if re.search(p, tail)}
    if len(found) >= 2:
        return 20
    if len(found) == 1:
        suggestions.append("Final scene: you have one CTA — add a second (subscribe + comment) for the algorithm.")
        return 12
    suggestions.append("Final scene: no call-to-action detected — add subscribe/comment/like in the last 20%.")
    return 0


def _score_open_loops(full_text, suggestions):
    """0-20: curiosity phrases that pull viewers through the video."""
    low = full_text.lower()
    found = [p for p in OPEN_LOOP_PHRASES if p in low]
    if not found:
        suggestions.append("Plant 1-2 open loops (\"but first…\", \"here's why…\", \"stay tuned\") to pull viewers through.")
    return min(20, 7 * len(found))


def score_script(scenes, format="shorts"):
    """Score a script 0-100 with breakdown, suggestions and a verdict."""
    scenes = _normalize_scenes(scenes)
    if not scenes:
        return {
            "score": 0,
            "breakdown": {"hook": 0, "pacing": 0, "cta": 0, "open_loops": 0},
            "suggestions": ["No script text found — nothing to score."],
            "verdict": "No script provided.",
        }

    fmt = (format or "shorts").lower()
    target_lo, target_hi = (80, 150) if fmt == "longform" else (25, 60)
    full_text = " ".join(s["text"] for s in scenes)

    suggestions = []
    hook = _score_hook(full_text, suggestions)
    pacing = _score_pacing(scenes, full_text, target_lo, target_hi, suggestions)
    cta = _score_cta(full_text, suggestions)
    loops = _score_open_loops(full_text, suggestions)

    total = hook + pacing + cta + loops
    if total >= 80:
        verdict = "Excellent — ready to render."
    elif total >= 60:
        verdict = "Good — apply the suggestions, then render."
    elif total >= 40:
        verdict = "Weak — fix the flagged issues before spending render time."
    else:
        verdict = "Needs a rewrite — start with a stronger hook and tighter pacing."

    return {
        "score": total,
        "breakdown": {"hook": hook, "pacing": pacing, "cta": cta, "open_loops": loops},
        "suggestions": suggestions,
        "verdict": verdict,
    }
