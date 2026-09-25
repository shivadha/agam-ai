import os
import sqlite3
import logging
from contextlib import contextmanager
from typing import Generator

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_DB_PATH = os.environ.get(
    "PULSEFORGE_DB_PATH",
    r"C:\AI_project\data\pulseforge.db",
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

@contextmanager
def _get_conn(db_path: str = _DB_PATH) -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager that yields a sqlite3 connection with WAL mode enabled
    and row_factory set to sqlite3.Row for dict-like access.
    Commits on success, rolls back on any exception.
    """
    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")  # better concurrency
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Table DDL
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS video_analytics (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    topic               TEXT,
    hook                TEXT,
    emotion             TEXT,
    hook_type           TEXT,
    viral_angle         TEXT,
    shorts_length       INTEGER,
    output_path         TEXT,
    model_used          TEXT,
    youtube_video_id    TEXT,
    views               INTEGER  DEFAULT 0,
    likes               INTEGER  DEFAULT 0,
    comments            INTEGER  DEFAULT 0,
    avg_watch_duration  REAL     DEFAULT 0.0,
    ctr                 REAL     DEFAULT 0.0
);
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_analytics_table(db_path: str = _DB_PATH) -> None:
    """
    Creates the video_analytics table if it does not already exist.
    Safe to call multiple times (idempotent).

    Parameters
    ----------
    db_path : str
        Absolute path to the SQLite database file.
        Defaults to C:\\AI_project\\data\\pulseforge.db or
        the PULSEFORGE_DB_PATH environment variable.
    """
    # Ensure parent directory exists so sqlite3 can create the file
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

    with _get_conn(db_path) as conn:
        conn.execute(_CREATE_TABLE_SQL)
    logger.info("[analytics] video_analytics table initialised at '%s'.", db_path)
    print(f"[analytics] Table 'video_analytics' ready at: {db_path}")


def store_video_record(
    topic: str,
    hook: str,
    viral_angle: str,
    emotion: str,
    shorts_length: int,
    output_path: str,
    model_used: str,
    hook_type: str = "",
    db_path: str = _DB_PATH,
) -> int:
    """
    Inserts a new video generation record and returns its auto-generated ID.

    Parameters
    ----------
    topic         : str  – The topic/title of the video.
    hook          : str  – The opening hook line used.
    viral_angle   : str  – The viral angle description.
    emotion       : str  – Primary emotion (e.g. 'curiosity').
    shorts_length : int  – Video length in seconds (30 / 45 / 60).
    output_path   : str  – Absolute path to the rendered video file.
    model_used    : str  – LLM model display name used for generation.
    hook_type     : str  – Hook type (e.g. 'curiosity_gap'). Optional.
    db_path       : str  – Path to SQLite DB (uses default if omitted).

    Returns
    -------
    int
        The record_id (primary key) of the newly inserted row.
    """
    init_analytics_table(db_path)  # ensure table exists

    sql = """
        INSERT INTO video_analytics
            (topic, hook, emotion, hook_type, viral_angle, shorts_length, output_path, model_used)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    with _get_conn(db_path) as conn:
        cursor = conn.execute(
            sql,
            (topic, hook, emotion, hook_type, viral_angle, shorts_length, output_path, model_used),
        )
        record_id: int = cursor.lastrowid  # type: ignore[assignment]

    logger.info("[analytics] Stored record id=%d for topic='%s'.", record_id, topic)
    print(f"[analytics] Stored video record → id={record_id}, topic='{topic}'")
    return record_id


def update_youtube_stats(
    record_id: int,
    video_id: str,
    views: int,
    likes: int,
    comments: int,
    avg_watch_duration: float,
    ctr: float,
    db_path: str = _DB_PATH,
) -> None:
    """
    Updates YouTube performance metrics for an existing record.

    Parameters
    ----------
    record_id           : int   – Primary key of the record to update.
    video_id            : str   – YouTube video ID (e.g. 'dQw4w9WgXcQ').
    views               : int   – Total view count.
    likes               : int   – Total like count.
    comments            : int   – Total comment count.
    avg_watch_duration  : float – Average watch duration in seconds.
    ctr                 : float – Click-through rate as a decimal (e.g. 0.065 = 6.5%).
    db_path             : str   – Path to SQLite DB.
    """
    sql = """
        UPDATE video_analytics
        SET
            youtube_video_id   = ?,
            views              = ?,
            likes              = ?,
            comments           = ?,
            avg_watch_duration = ?,
            ctr                = ?
        WHERE id = ?
    """
    with _get_conn(db_path) as conn:
        conn.execute(sql, (video_id, views, likes, comments, avg_watch_duration, ctr, record_id))

    logger.info(
        "[analytics] Updated YouTube stats for record_id=%d (video_id=%s, views=%d, ctr=%.4f).",
        record_id, video_id, views, ctr,
    )
    print(
        f"[analytics] YouTube stats updated → record_id={record_id}, "
        f"video_id={video_id}, views={views:,}, ctr={ctr:.2%}"
    )


def get_top_performing_patterns(limit: int = 5, db_path: str = _DB_PATH) -> dict:
    """
    Analyses stored records and returns the top-performing content patterns.

    Returns
    -------
    dict with keys:
        best_emotion   – Emotion with the highest average CTR.
        best_hook_type – Hook type with the highest average CTR.
        best_length    – Shorts length (seconds) with the highest average CTR.
        avg_ctr        – Overall average CTR across all tracked records.
        top_records    – List of the top N records sorted by CTR (descending).
    """
    init_analytics_table(db_path)

    with _get_conn(db_path) as conn:
        # Best emotion by avg CTR
        best_emotion_row = conn.execute(
            """
            SELECT emotion, AVG(ctr) as avg_ctr
            FROM video_analytics
            WHERE emotion IS NOT NULL AND emotion != '' AND views > 0
            GROUP BY emotion
            ORDER BY avg_ctr DESC
            LIMIT 1
            """
        ).fetchone()

        # Best hook_type by avg CTR
        best_hook_row = conn.execute(
            """
            SELECT hook_type, AVG(ctr) as avg_ctr
            FROM video_analytics
            WHERE hook_type IS NOT NULL AND hook_type != '' AND views > 0
            GROUP BY hook_type
            ORDER BY avg_ctr DESC
            LIMIT 1
            """
        ).fetchone()

        # Best shorts length by avg CTR
        best_length_row = conn.execute(
            """
            SELECT shorts_length, AVG(ctr) as avg_ctr
            FROM video_analytics
            WHERE shorts_length IS NOT NULL AND views > 0
            GROUP BY shorts_length
            ORDER BY avg_ctr DESC
            LIMIT 1
            """
        ).fetchone()

        # Overall avg CTR
        overall_row = conn.execute(
            "SELECT AVG(ctr) as overall_avg FROM video_analytics WHERE views > 0"
        ).fetchone()

        # Top N records by CTR
        top_rows = conn.execute(
            """
            SELECT id, topic, hook, emotion, hook_type, shorts_length,
                   ctr, views, likes, avg_watch_duration, youtube_video_id
            FROM video_analytics
            WHERE views > 0
            ORDER BY ctr DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    result = {
        "best_emotion":   best_emotion_row["emotion"]      if best_emotion_row else None,
        "best_hook_type": best_hook_row["hook_type"]       if best_hook_row    else None,
        "best_length":    best_length_row["shorts_length"] if best_length_row  else None,
        "avg_ctr":        round(overall_row["overall_avg"] or 0.0, 6),
        "top_records":    [dict(row) for row in top_rows],
    }

    logger.info(
        "[analytics] Top patterns — emotion=%s, hook_type=%s, length=%s, avg_ctr=%.4f",
        result["best_emotion"], result["best_hook_type"],
        result["best_length"], result["avg_ctr"],
    )
    return result


def get_all_records(limit: int = 20, db_path: str = _DB_PATH) -> list:
    """
    Returns the most recent video records ordered by creation date (newest first).

    Parameters
    ----------
    limit   : int – Maximum number of records to return (default 20).
    db_path : str – Path to SQLite DB.

    Returns
    -------
    list[dict]
        Each dict contains all columns from the video_analytics table.
    """
    init_analytics_table(db_path)

    with _get_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM video_analytics
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    records = [dict(row) for row in rows]
    logger.info("[analytics] get_all_records returned %d rows (limit=%d).", len(records), limit)
    return records
