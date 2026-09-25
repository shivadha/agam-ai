"""
AGAM — Scheduled uploads queue (JSON-backed).

A finished video can be scheduled now and published later. The Flask
scheduler (every 5 min, under __main__ in app.py) picks up due items and
publishes them via src.backend.youtube_upload.upload_video — the actual
publish call stays in app.py, this module only owns the queue.

Storage: <repo>/data/upload_schedule.json — the same data/ dir the app
already uses for JSON state (NOT /tmp, so schedules survive restarts).

Item shape:
  {id, video_path, title, description, tags, publish_at (ISO),
   privacy, user_id, status: scheduled|published|failed,
   youtube_id, error, created_at, published_at}

Thread-safe (scheduler thread + Flask threads share the file).
Only stdlib deps.
"""

import json
import os
import threading
import uuid
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
QUEUE_PATH = os.path.join(BASE_DIR, "data", "upload_schedule.json")

_lock = threading.Lock()


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value):
    """Parse an ISO timestamp; naive values are assumed UTC."""
    dt = datetime.fromisoformat((value or "").strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _load():
    if not os.path.exists(QUEUE_PATH):
        return []
    try:
        with open(QUEUE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[publish_schedule] Queue read note ({e}) — treating as empty.")
        return []


def _save(items):
    os.makedirs(os.path.dirname(QUEUE_PATH), exist_ok=True)
    tmp = QUEUE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)
    os.replace(tmp, QUEUE_PATH)  # atomic


def schedule_upload(video_path, title, description="", tags=None,
                    publish_at_iso=None, privacy="private", user_id=1):
    """Queue a video for later publishing. Returns the stored item dict."""
    if not video_path or not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")
    if not (title or "").strip():
        raise ValueError("A title is required to schedule an upload.")
    publish_at = publish_at_iso or _now_iso()
    _parse_iso(publish_at)  # validate early — fail fast on bad timestamps
    privacy = (privacy or "private").lower()
    if privacy not in ("private", "unlisted", "public"):
        privacy = "private"

    item = {
        "id": uuid.uuid4().hex[:8],
        "video_path": os.path.abspath(video_path),
        "title": title.strip(),
        "description": description or "",
        "tags": list(tags or []),
        "publish_at": publish_at,
        "privacy": privacy,
        "user_id": user_id,
        "status": "scheduled",
        "youtube_id": None,
        "error": None,
        "created_at": _now_iso(),
        "published_at": None,
    }
    with _lock:
        items = _load()
        items.append(item)
        _save(items)
    print(f"[publish_schedule] Scheduled '{item['title']}' for {publish_at} (id {item['id']}).")
    return dict(item)


def due_uploads(now_iso=None):
    """Items with status 'scheduled' whose publish_at has passed, oldest first."""
    now = _parse_iso(now_iso) if now_iso else datetime.now(timezone.utc)
    with _lock:
        items = _load()
    due = [i for i in items
           if i.get("status") == "scheduled" and _parse_iso(i.get("publish_at") or "") <= now]
    due.sort(key=lambda i: i.get("publish_at") or "")
    return due


def _set_status(item_id, status, youtube_id=None, error=None):
    with _lock:
        items = _load()
        for i in items:
            if i.get("id") == item_id:
                i["status"] = status
                if youtube_id is not None:
                    i["youtube_id"] = youtube_id
                    i["published_at"] = _now_iso()
                if error is not None:
                    i["error"] = error
                _save(items)
                return dict(i)
    return None


def mark_published(item_id, youtube_id):
    """Mark a queue item published. Returns the updated item (None if unknown id)."""
    return _set_status(item_id, "published", youtube_id=youtube_id)


def mark_failed(item_id, error):
    """Mark a queue item failed with the error message. Returns updated item or None."""
    return _set_status(item_id, "failed", error=str(error))


def list_queue():
    """All queue items, oldest publish_at first."""
    with _lock:
        items = _load()
    return sorted(items, key=lambda i: i.get("publish_at") or "")


def remove(item_id):
    """Delete a queue item. Returns True when something was removed."""
    with _lock:
        items = _load()
        kept = [i for i in items if i.get("id") != item_id]
        if len(kept) == len(items):
            return False
        _save(kept)
        return True
