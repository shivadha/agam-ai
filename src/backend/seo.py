"""
AGAM — SEO pack builder (pure local, no credentials, no LLM).

  build_seo_pack(title, scenes, keywords=None)
    scenes: list of dicts with 'title'/'text' plus 'start_sec' (preferred)
    or 'duration_sec' (cumulative timings are derived). Missing timing info
    falls back to a documented 10s-per-scene estimate.
    Returns {title, chapters_text, description, tags, hindi_title,
             hindi_description} — all JSON-serializable.

  suggest_title_variants(title, n=5)
    Deterministic pattern rewrites (number-led, question, how-to,
    curiosity gap, bold claim). No LLM, no network.

Hindi fields reuse translate_text from src.backend.dubbing (the same free
Google endpoint the dubbing pipeline uses). If translation is unavailable,
the English text is kept and the render continues.
"""

import re

try:
    from src.backend.dubbing import translate_text
except ImportError:  # pragma: no cover - package imported under another root
    from .dubbing import translate_text

TAG_STOPWORDS = frozenset(
    "the a an and or of to in on for with is are was were be by at from "
    "this that these those it its as so such no not you your we our they "
    "their he she his her them then than just don does did out up over "
    "into about after before".split()
)

_FALLBACK_SCENE_SEC = 10  # used only when a scene has no timing info at all
_MAX_TAG_CHARS = 500      # YouTube tag field limit (total characters)


def _fmt_ts(seconds):
    """Format seconds as MM:SS or H:MM:SS (YouTube chapter format)."""
    s = max(0, int(round(seconds)))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _scene_starts(scenes):
    """Derive [(start_sec, label)] from scenes.

    Uses 'start_sec' when present, else accumulates 'duration_sec'.
    Scenes with neither get the documented 10s fallback estimate.
    """
    out, cursor = [], 0.0
    for i, sc in enumerate(scenes or []):
        sc = sc or {}
        if sc.get("start_sec") is not None:
            try:
                cursor = float(sc["start_sec"])
            except (TypeError, ValueError):
                pass
        start = cursor
        try:
            dur = float(sc.get("duration_sec") or _FALLBACK_SCENE_SEC)
        except (TypeError, ValueError):
            dur = _FALLBACK_SCENE_SEC
        label = (sc.get("title") or "").strip()
        if not label:
            text = (sc.get("text") or sc.get("narration") or "").strip()
            label = " ".join(text.split()[:6]).rstrip(".,!?") or f"Part {i + 1}"
        out.append((start, label))
        cursor = start + max(dur, 0.1)
    if out:
        # YouTube requires the first chapter at exactly 00:00.
        out[0] = (0.0, out[0][1])
    return out


def _keywords_from_title(title, keywords):
    kws = []
    for k in (keywords or []):
        k = str(k).strip()
        if k and k.lower() not in (x.lower() for x in kws):
            kws.append(k)
    for tok in re.findall(r"[\w']+", (title or "").lower(), flags=re.UNICODE):
        tok = tok.strip("'")
        if len(tok) >= 4 and tok not in TAG_STOPWORDS and tok not in kws:
            kws.append(tok)
    return kws


def _build_tags(title, keywords):
    """Tag list whose total character count stays within YouTube's 500 limit."""
    seen, tags = set(), []
    for kw in _keywords_from_title(title, keywords):
        tag = kw.strip()
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            tags.append(tag)
    # Trim from the end until the joined length fits the limit.
    while tags and sum(len(t) for t in tags) + max(len(tags) - 1, 0) > _MAX_TAG_CHARS:
        tags.pop()
    return tags


def _hashtags(keywords, limit=4):
    tags = []
    for kw in (keywords or [])[:limit]:
        h = re.sub(r"\W+", "", str(kw), flags=re.UNICODE)
        if h:
            tags.append("#" + h)
    return tags


def build_seo_pack(title, scenes, keywords=None):
    """Build a full YouTube SEO pack for a video.

    Returns:
        {title, chapters_text, description, tags, hindi_title,
         hindi_description}
    """
    title = (title or "").strip() or "Untitled Video"
    keywords = [str(k).strip() for k in (keywords or []) if str(k).strip()]

    chapters = _scene_starts(scenes)
    chapters_text = "\n".join(f"{_fmt_ts(s)} {label}" for s, label in chapters)

    hook = (
        f"{title} — everything you need to know, explained fast. "
        "Watch till the end for the part most people miss."
    )
    cta = (
        "If this helped, hit LIKE 👍, SUBSCRIBE 🔔 for daily breakdowns, "
        "and drop your take in the COMMENTS 💬 — I read every one."
    )
    hashtags = " ".join(_hashtags(keywords))
    description_parts = [title, "", hook, ""]
    if chapters_text:
        description_parts += ["CHAPTERS:", chapters_text, ""]
    description_parts.append(cta)
    if hashtags:
        description_parts += ["", hashtags]
    description = "\n".join(description_parts).strip()

    tags = _build_tags(title, keywords)

    try:
        hindi_title = translate_text(title, target="hi")
    except Exception as e:
        print(f"[seo] Hindi title translation note: {e}")
        hindi_title = title
    try:
        hindi_description = translate_text(description, target="hi")
    except Exception as e:
        print(f"[seo] Hindi description translation note: {e}")
        hindi_description = description

    print(f"[seo] Built SEO pack for '{title[:50]}' "
          f"({len(chapters)} chapters, {len(tags)} tags).")
    return {
        "title": title,
        "titles": [v["title"] for v in suggest_title_variants(title)],
        "chapters_text": chapters_text,
        "description": description,
        "tags": tags,
        "hindi_title": hindi_title,
        "hindi_description": hindi_description,
    }


_TITLE_PATTERNS = [
    ("number-led",     "{core}: 7 Things You Need to Know"),
    ("question",       "Is {core} Actually Worth It?"),
    ("how-to",         "How {core} Works (Explained Simply)"),
    ("curiosity-gap",  "The {core} Secret Nobody Talks About"),
    ("bold-claim",     "{core} Will Change Everything"),
]


def suggest_title_variants(title, n=5):
    """Deterministic title rewrites across proven patterns. No LLM.

    Returns [{pattern, title}] for the first n patterns.
    """
    core = (title or "").strip().rstrip(".!?") or "This Story"
    # Avoid stutter when the title already starts with a number-led pattern.
    core = re.sub(r"^\d+\s+", "", core)
    out = []
    for pattern, template in _TITLE_PATTERNS[:max(1, min(int(n), len(_TITLE_PATTERNS)))]:
        out.append({"pattern": pattern, "title": template.format(core=core)})
    return out
