"""TTS script normalization — the #1 slop tell is machine-read tokens.

A TTS engine that reads "₹10L" as "rupee ten L" or speaks literal asterisks
sounds like AI slop no matter how good the voice model is. This pass runs
before synthesis and rewrites the script into spoken form:

  "₹10L"      -> "ten lakh rupees"
  "₹2.5Cr"    -> "two point five crore rupees"
  "45%"       -> "forty five percent"
  "MBA"       -> "M-B-A"            (common abbreviations are spelled out)
  "**bold**"  -> "bold"             (no spoken asterisks / markdown)
  "2026"      -> "twenty twenty six" (years stay year-like)

Punctuation-as-prosody is PRESERVED: commas, em-dashes and ellipses force
natural pauses in every TTS engine, so dramatic beats survive.

The NORMALIZED text is what the voice speaks. Callers must use the same
normalized text for caption reconciliation (the pipeline writes a
<output>.spoken.txt sidecar), or captions will disagree with the voice.
"""

import os
import re

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven",
         "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
         "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
         "eighty", "ninety"]


def _under_100(n: int) -> str:
    if n < 20:
        return _ONES[n]
    t, o = divmod(n, 10)
    return _TENS[t] + ("" if o == 0 else " " + _ONES[o])


def _under_1000(n: int) -> str:
    h, r = divmod(n, 100)
    out = ""
    if h:
        out = _ONES[h] + " hundred"
    if r:
        out += (" " if out else "") + _under_100(r)
    return out or "zero"


def number_to_words(value) -> str:
    """Indian-system number words: 100000 -> 'one lakh', 2500000 -> 'twenty
    five lakh', 10000000 -> 'one crore'. Decimals become 'point five'."""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if num != int(num):
        parts = str(value).strip().split(".", 1)
        whole = parts[0]
        frac = parts[1] if len(parts) > 1 else ""
        frac_words = " ".join(_ONES[int(d)] for d in frac if d.isdigit())
        head = number_to_words(whole) if whole else "zero"
        return f"{head} point {frac_words}".strip() if frac_words else head
    n = int(num)
    if n < 0:
        return "minus " + number_to_words(-n)
    if n < 1000:
        return _under_1000(n)
    if n < 100000:
        th, r = divmod(n, 1000)
        return (_under_1000(th) + " thousand" + (" " + _under_1000(r) if r else "")).strip()
    if n < 10000000:
        l, r = divmod(n, 100000)
        return (_under_1000(l) + " lakh" + (" " + number_to_words(r) if r else "")).strip()
    cr, r = divmod(n, 10000000)
    return (_under_1000(cr) + " crore" + (" " + number_to_words(r) if r else "")).strip()


# Abbreviations the TTS must spell out instead of guessing.
_ABBR = {
    "MBA": "M-B-A", "AI": "A-I", "CEO": "C-E-O", "CTO": "C-T-O",
    "USA": "U-S-A", "UK": "U-K", "UAE": "U-A-E", "IIT": "I-I-T",
    "CAT": "C-A-T", "GMAT": "G-M-A-T", "UPSC": "U-P-S-C", "GST": "G-S-T",
    "UPI": "U-P-I", "RBI": "R-B-I", "GDP": "G-D-P", "TV": "T-V",
    "PC": "P-C", "URL": "U-R-L", "API": "A-P-I", "SEO": "S-E-O",
    "HR": "H-R", "PR": "P-R", "DM": "D-M", "PM": "P-M", "AM": "A-M",
}
_ABBR_RE = re.compile(r"\b(" + "|".join(sorted(_ABBR)) + r")\b")


def normalize_script_for_tts(text: str) -> str:
    """Rewrite a narration script into spoken form for TTS. Idempotent."""
    t = (text or "").strip()
    if not t:
        return t

    # Strip markdown the LLM sometimes leaves behind (spoken asterisks =
    # instant slop).
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"(?m)^\s*#{1,6}\s+", "", t)
    t = t.replace("#", "")  # stray hashtags read as "hash" — never spoken
    t = t.replace("*", "").replace("`", "")

    # Rupee amounts: ₹10L / ₹2.5Cr / ₹500 (Indian system).
    def _inr(m):
        amt, unit = m.group(1), (m.group(2) or "").lower()
        words = number_to_words(amt)
        if unit.startswith("cr"):
            words = number_to_words(float(amt) * 10000000)
            return f"{words} rupees"
        if unit.startswith("l"):
            words = number_to_words(float(amt) * 100000)
            return f"{words} rupees"
        return f"{words} rupees"
    t = re.sub(r"₹\s*([\d,]+(?:\.\d+)?)\s*(crore|cr|lakh|l)\b", _inr, t,
               flags=re.IGNORECASE)
    t = re.sub(r"₹\s*([\d,]+(?:\.\d+)?)\b",
               lambda m: f"{number_to_words(m.group(1).replace(',', ''))} rupees", t)

    # Percentages: 45% -> "forty five percent".
    t = re.sub(r"(\d+(?:\.\d+)?)\s*%",
               lambda m: f"{number_to_words(m.group(1))} percent", t)

    # Abbreviations: MBA -> M-B-A.
    t = _ABBR_RE.sub(lambda m: _ABBR[m.group(1)], t)

    # Years stay year-like: 2026 -> "twenty twenty six" (not "two thousand
    # twenty six", which no Shorts narrator says).
    def _year(m):
        y = int(m.group(1))
        return f"{_under_100(y // 100)} {_under_100(y % 100)}"
    t = re.sub(r"\b(19\d{2}|20[0-3]\d)\b", _year, t)

    # Dramatic beats: runs of dots become a real ellipsis (pause); em-dashes
    # are kept — punctuation is prosody.
    t = re.sub(r"\.{2,}", "…", t)

    # Tidy up.
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def spoken_sidecar_path(audio_path: str) -> str:
    """Path of the <audio>.spoken.txt sidecar holding the normalized text."""
    base, _ext = os.path.splitext(audio_path or "")
    return base + ".spoken.txt"
