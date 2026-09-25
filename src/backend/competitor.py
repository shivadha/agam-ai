"""
AGAM — Rival channel analysis (quota-light, no scraping hacks).

Pipeline:
  1. Resolve channel URL / handle / ID -> channel ID via channels.list
     (forHandle or id — 1 quota unit, never search.list).
  2. Uploads playlist -> playlistItems.list (1 unit per 50 videos).
  3. videos.list batched 50 IDs per call (1 unit each) for
     title / view_count / like_count / published_at.
  4. Stdlib-only keyword clustering of video titles -> topic clusters,
     then gap suggestions = high-view clusters with low keyword overlap
     vs the user's own topics.

Total quota for max_videos=30: ~3-4 units.

Everything returns JSON-serializable dicts. Missing YouTube OAuth
credentials -> RuntimeError (never a silent empty result).
"""

import re

NOT_CONNECTED_MSG = (
    "YouTube API not connected — connect your YouTube account first "
    "(check GET /api/youtube/status, authorize via /youtube/authorize)."
)

STOPWORDS = frozenset("""
a an and are as at be by for from has have in is it its of on or that the
this to was will with you your we our they their he she his her them then
than so such no not all any can just don do does did out up over under
into about after before between through during each other more most
video videos official new best top watch full episode ep part vs versus
2024 2025 2026 shorts short live stream streams hindi india
""".split())


def _service(user_id):
    """Build an authenticated YouTube Data API v3 client or raise."""
    from src.backend.youtube_auth import get_user_credentials
    from googleapiclient.discovery import build

    creds = get_user_credentials(user_id)
    if not creds:
        raise RuntimeError(NOT_CONNECTED_MSG)
    return build("youtube", "v3", credentials=creds)


def _resolve_channel_id(youtube, ref):
    """Accept a channel URL, @handle, or raw channel ID -> channel ID."""
    ref = (ref or "").strip().rstrip("/")
    if not ref:
        raise ValueError("channel_url_or_id is empty.")

    chan_id, handle = None, None
    m = re.search(r"youtube\.com/channel/(UC[\w-]{20,})", ref)
    if m:
        chan_id = m.group(1)
    elif re.fullmatch(r"UC[\w-]{20,}", ref):
        chan_id = ref
    else:
        m = re.search(r"youtube\.com/@([\w.\-]+)", ref)
        if m:
            handle = m.group(1)
        elif ref.startswith("@"):
            handle = ref[1:]
        else:
            # Last path segment as a probable handle (/c/Name, /user/Name, bare name)
            handle = ref.rsplit("/", 1)[-1].lstrip("@")

    try:
        if chan_id:
            resp = youtube.channels().list(
                part="snippet,statistics,contentDetails", id=chan_id).execute()
        else:
            resp = youtube.channels().list(
                part="snippet,statistics,contentDetails", forHandle=handle).execute()
    except Exception as e:
        raise RuntimeError(f"YouTube channel lookup failed for {ref!r}: {e}")

    items = resp.get("items") or []
    if not items:
        raise ValueError(f"Could not resolve a YouTube channel from {ref!r}.")
    return items[0]


def _fetch_videos(youtube, uploads_playlist_id, max_videos):
    """Return [(video_id, ...)] from the uploads playlist, then hydrate."""
    video_ids = []
    page_token = None
    while len(video_ids) < max_videos:
        resp = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=uploads_playlist_id,
            maxResults=min(50, max_videos - len(video_ids)),
            pageToken=page_token,
        ).execute()
        for item in resp.get("items") or []:
            vid = (item.get("contentDetails") or {}).get("videoId")
            if vid:
                video_ids.append(vid)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    videos = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i + 50]
        resp = youtube.videos().list(
            part="snippet,statistics", id=",".join(batch)).execute()
        for item in resp.get("items") or []:
            snippet = item.get("snippet") or {}
            stats = item.get("statistics") or {}
            videos.append({
                "id": item.get("id"),
                "title": snippet.get("title") or "",
                "views": int(stats.get("viewCount") or 0),
                "likes": int(stats.get("likeCount") or 0),
                "published_at": snippet.get("publishedAt") or "",
            })
    return videos


def title_keywords(text):
    """Public helper: significant keywords from a title (stdlib only)."""
    tokens = re.findall(r"[\w']+", (text or "").lower(), flags=re.UNICODE)
    out = []
    for tok in tokens:
        tok = tok.strip("'")
        if not tok or tok in STOPWORDS:
            continue
        # Keep non-latin tokens (Hindi etc.) even when short; latin needs len>=3.
        if len(tok) >= 3 or any(ord(c) > 127 for c in tok):
            out.append(tok)
    return out


def _cluster_videos(videos, top_n_tokens=15, max_clusters=8):
    """Group videos by shared significant title tokens.

    Returns [{label, keywords, avg_views, video_count}] sorted by avg_views.
    """
    from collections import Counter

    freq = Counter()
    per_video_kw = []
    for v in videos:
        kws = title_keywords(v["title"])
        per_video_kw.append(kws)
        freq.update(set(kws))

    top_tokens = [t for t, _ in freq.most_common(top_n_tokens) if freq[t] >= 2]
    if not top_tokens:  # every title is unique — fall back to single-token clusters
        top_tokens = [t for t, _ in freq.most_common(6)]

    clusters = []
    for token in top_tokens:
        members = [v for v, kws in zip(videos, per_video_kw) if token in kws]
        if len(members) < 2:
            continue
        co = Counter()
        for v, kws in zip(videos, per_video_kw):
            if token in kws:
                co.update(k for k in set(kws) if k != token)
        keywords = [token] + [k for k, _ in co.most_common(4)]
        label = " ".join(keywords[:2]).title()
        avg_views = sum(v["views"] for v in members) // len(members)
        clusters.append({
            "label": label,
            "keywords": keywords,
            "avg_views": avg_views,
            "video_count": len(members),
        })

    clusters.sort(key=lambda c: c["avg_views"], reverse=True)
    return clusters[:max_clusters]


_TITLE_TEMPLATES = [
    "{label}: The Untold Story",
    "Why {label} Is Blowing Up Right Now",
    "{label} — 5 Things You Missed",
    "The Truth About {label}",
    "How {label} Actually Works",
]


def _suggest_gaps(clusters, user_topics, max_gaps=5):
    """High-view clusters with low keyword overlap vs the user's topics."""
    user_kw = set()
    for t in user_topics or []:
        user_kw.update(title_keywords(t))

    gaps = []
    for i, c in enumerate(clusters):
        ckw = set(c["keywords"])
        overlap = len(ckw & user_kw) / max(len(ckw), 1)
        if overlap >= 0.5:
            continue
        template = _TITLE_TEMPLATES[i % len(_TITLE_TEMPLATES)]
        gaps.append({
            "topic": c["label"],
            "rationale": (
                f"Rival cluster '{c['label']}' averages {c['avg_views']:,} views "
                f"across {c['video_count']} videos with low overlap vs your "
                f"topics — an underserved angle."
            ),
            "suggested_title": template.format(label=c["label"]),
        })
        if len(gaps) >= max_gaps:
            break
    return gaps


def analyze_channel(channel_url_or_id, user_topics=None, max_videos=30, user_id=1):
    """Analyze a rival channel's recent videos and surface topic gaps.

    Args:
        channel_url_or_id: full URL, @handle, or raw UC... channel ID.
        user_topics: list of the user's own topic strings (for gap detection).
        max_videos: how many recent uploads to analyze (quota-light).
        user_id: app user whose YouTube OAuth credentials to use.

    Returns JSON-serializable dict with channel info, videos, top_clusters
    and gaps. Raises RuntimeError if YouTube is not connected.
    """
    youtube = _service(user_id)
    channel = _resolve_channel_id(youtube, channel_url_or_id)

    snippet = channel.get("snippet") or {}
    stats = channel.get("statistics") or {}
    content = channel.get("contentDetails") or {}
    uploads_playlist = (content.get("relatedPlaylists") or {}).get("uploads")
    if not uploads_playlist:
        raise ValueError("Channel has no public uploads playlist.")

    videos = _fetch_videos(youtube, uploads_playlist, max(1, min(int(max_videos), 50)))
    clusters = _cluster_videos(videos)
    gaps = _suggest_gaps(clusters, user_topics)

    print(f"[competitor] Analyzed {len(videos)} videos from "
          f"'{snippet.get('title')}' -> {len(clusters)} clusters, {len(gaps)} gaps.")
    return {
        "channel_id": channel.get("id"),
        "channel_title": snippet.get("title") or "",
        "subscriber_count": int(stats.get("subscriberCount") or 0),
        "video_count_analyzed": len(videos),
        "videos": videos,
        "top_clusters": clusters,
        "gaps": gaps,
    }
