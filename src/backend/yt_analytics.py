"""
AGAM — YouTube Analytics API (channel performance + topic affinity).

NOTE on naming: `src/backend/analytics.py` already exists in this repo as a
*local SQLite* analytics store (video_analytics table). This module is the
*live YouTube Analytics API* reader, so it lives here as `yt_analytics`
to avoid clobbering that file.

Pipeline:
  channel_performance(user_id, days)
    -> youtubeAnalytics.reports.query (channel==MINE): views, watch time,
       subscribers gained + per-video views & avg view duration
    -> youtube Data API videos.list (1 quota unit) for titles + durations
    -> avg_retention_pct per video = avgViewDuration / duration
  topic_affinity(user_id, topics)
    -> matches top_videos titles against topic keywords (reuses the
       stdlib tokenizer from src.backend.competitor) and ranks topics by
       views + retention.

The repo's OAuth SCOPES already include
https://www.googleapis.com/auth/youtube which the Analytics API accepts.

Everything returns JSON-serializable dicts. Not authorized / API disabled
-> RuntimeError with a clear message (never a silent empty result).
"""

import re
from datetime import date, timedelta

NOT_AUTHORIZED_MSG = (
    "YouTube Analytics not authorized — connect YouTube with analytics "
    "access first (GET /api/youtube/status, authorize via /youtube/authorize). "
    "If connected, enable the YouTube Analytics API in Google Cloud Console."
)


def _analytics_service(user_id):
    from src.backend.youtube_auth import get_user_credentials
    from googleapiclient.discovery import build

    creds = get_user_credentials(user_id)
    if not creds:
        raise RuntimeError(NOT_AUTHORIZED_MSG)
    return build("youtubeAnalytics", "v2", credentials=creds)


def _data_service(user_id):
    from src.backend.youtube_auth import get_user_credentials
    from googleapiclient.discovery import build

    creds = get_user_credentials(user_id)
    if not creds:
        raise RuntimeError(NOT_AUTHORIZED_MSG)
    return build("youtube", "v3", credentials=creds)


def _iso8601_to_seconds(iso):
    """Parse PT1H2M3S -> seconds (stdlib)."""
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", iso or "")
    if not m:
        return 0
    h, mi, s = m.groups()
    return int(h or 0) * 3600 + int(mi or 0) * 60 + float(s or 0)


def _query(svc, **kwargs):
    from googleapiclient.errors import HttpError

    try:
        return svc.reports().query(**kwargs).execute()
    except HttpError as e:
        status = getattr(e.resp, "status", None)
        if status in (401, 403):
            raise RuntimeError(NOT_AUTHORIZED_MSG + f" (API said: {e})")
        raise RuntimeError(f"YouTube Analytics query failed: {e}")


def _video_meta(user_id, video_ids):
    """Map video_id -> {title, duration_sec} via Data API (1 quota unit)."""
    if not video_ids:
        return {}
    youtube = _data_service(user_id)
    meta = {}
    for i in range(0, len(video_ids), 50):
        resp = youtube.videos().list(
            part="snippet,contentDetails", id=",".join(video_ids[i:i + 50])).execute()
        for item in resp.get("items") or []:
            snippet = item.get("snippet") or {}
            content = item.get("contentDetails") or {}
            meta[item.get("id")] = {
                "title": snippet.get("title") or "",
                "duration_sec": _iso8601_to_seconds(content.get("duration")),
            }
    return meta


def channel_performance(user_id=1, days=28):
    """Channel totals + top videos with retention for the last N days.

    Returns {days, views, watch_time_hours, subscribers_gained,
             top_videos: [{id, title, views, avg_view_duration_sec,
                           duration_sec, avg_retention_pct}]}.
    """
    days = max(1, min(int(days), 365))
    end = date.today()
    start = end - timedelta(days=days)
    start_s, end_s = start.isoformat(), end.isoformat()

    svc = _analytics_service(user_id)

    totals = _query(
        svc, ids="channel==MINE", startDate=start_s, endDate=end_s,
        metrics="views,estimatedMinutesWatched,subscribersGained",
    )
    rows = totals.get("rows") or [[0, 0, 0]]
    views = int(rows[0][0] or 0)
    watch_hours = round(float(rows[0][1] or 0) / 60, 1)
    subs = int(rows[0][2] or 0)

    per_video = _query(
        svc, ids="channel==MINE", startDate=start_s, endDate=end_s,
        metrics="views,averageViewDuration", dimensions="video",
        sort="-views", maxResults=10,
    )
    rows = per_video.get("rows") or []
    meta = _video_meta(user_id, [r[0] for r in rows])

    top_videos = []
    for r in rows:
        vid, v_views, avg_dur = r[0], int(r[1] or 0), float(r[2] or 0)
        m = meta.get(vid, {})
        dur = m.get("duration_sec") or 0
        retention = round(avg_dur / dur * 100, 1) if dur > 0 else 0.0
        top_videos.append({
            "id": vid,
            "title": m.get("title") or vid,
            "views": v_views,
            "avg_view_duration_sec": round(avg_dur, 1),
            "duration_sec": round(dur, 1),
            "avg_retention_pct": retention,
        })

    print(f"[yt_analytics] {days}d: {views:,} views, {watch_hours}h watch, "
          f"+{subs} subs, {len(top_videos)} top videos.")
    return {
        "days": days,
        "views": views,
        "watch_time_hours": watch_hours,
        "subscribers_gained": subs,
        "top_videos": top_videos,
    }


def topic_affinity(user_id=1, topics=None, days=28):
    """Rank your topics by how your own top videos performed on them.

    Returns [{topic, video_count, avg_views, avg_retention_pct}] sorted by
    avg_views desc. Topics with no matching videos are included with zeros
    so the frontend can show "no data yet".
    """
    from src.backend.competitor import title_keywords

    topics = [t for t in (topics or []) if t and str(t).strip()]
    perf = channel_performance(user_id=user_id, days=days)
    top_videos = perf.get("top_videos") or []

    ranked = []
    for topic in topics:
        tkw = set(title_keywords(topic))
        matched = [v for v in top_videos
                   if tkw and tkw & set(title_keywords(v["title"]))]
        if matched:
            avg_views = sum(v["views"] for v in matched) // len(matched)
            avg_ret = round(sum(v["avg_retention_pct"] for v in matched) / len(matched), 1)
        else:
            avg_views, avg_ret = 0, 0.0
        ranked.append({
            "topic": topic,
            "video_count": len(matched),
            "avg_views": avg_views,
            "avg_retention_pct": avg_ret,
        })
    ranked.sort(key=lambda r: r["avg_views"], reverse=True)
    return {"days": perf["days"], "topics": ranked}
