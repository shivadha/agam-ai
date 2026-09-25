"""
database.py — PulseForge Embedded SQLite Persistence Layer
============================================================
Single-file database, lives at data/pulseforge.db inside the project.

Future migration: swap sqlite3 for psycopg2 + SQLAlchemy for PostgreSQL/Supabase.
WAL journal mode is enabled for safe concurrent Flask multi-thread access.
"""

import sqlite3
import os
import datetime
import threading
from werkzeug.security import generate_password_hash, check_password_hash

# ── Path ───────────────────────────────────────────────────────────────────
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH   = os.path.join(_BASE_DIR, 'data', 'pulseforge.db')
_db_lock  = threading.Lock()

# ── Role Permissions ───────────────────────────────────────────────────────
ROLES = {
    'admin':    {'can_save': True,  'can_refresh': True,  'can_manage_users': True},
    'editor':   {'can_save': True,  'can_refresh': True,  'can_manage_users': False},
    'viewer':   {'can_save': True,  'can_refresh': False, 'can_manage_users': False},
    'readonly': {'can_save': False, 'can_refresh': False, 'can_manage_users': False},
}

# ── Connection ─────────────────────────────────────────────────────────────
def get_db():
    """Returns a new SQLite connection with row_factory and WAL mode."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

# ── Schema Init ────────────────────────────────────────────────────────────
def init_db():
    """Create all tables and seed the admin user on first run."""
    with _db_lock:
        conn = get_db()
        c = conn.cursor()

        c.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                email         TEXT    UNIQUE NOT NULL,
                password_hash TEXT    NOT NULL,
                display_name  TEXT,
                role          TEXT    DEFAULT 'viewer',
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login    TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS articles (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                title          TEXT    NOT NULL,
                link           TEXT    UNIQUE NOT NULL,
                source         TEXT,
                topic          TEXT,
                score          INTEGER DEFAULT 0,
                video_score    INTEGER DEFAULT 0,
                description    TEXT,
                image_url      TEXT,
                processed_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_articles_topic ON articles(topic);
            CREATE INDEX IF NOT EXISTS idx_articles_score ON articles(score DESC);
            CREATE INDEX IF NOT EXISTS idx_articles_date  ON articles(processed_date DESC);

            CREATE TABLE IF NOT EXISTS saved_articles (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
                saved_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notes      TEXT,
                UNIQUE(user_id, article_id)
            );

            CREATE TABLE IF NOT EXISTS user_youtube_tokens (
                user_id       INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                credentials   TEXT
            );
        ''')

        # Auto-migration: ensure image_url exists on legacy tables
        try:
            c.execute("SELECT image_url FROM articles LIMIT 1")
        except sqlite3.OperationalError:
            try:
                c.execute("ALTER TABLE articles ADD COLUMN image_url TEXT")
                print("[DB] Added 'image_url' column to articles table.")
            except Exception as e:
                print(f"[DB] Migration note: {e}")

        # Seed admin user
        existing = c.execute(
            "SELECT id FROM users WHERE email = ?", ('shivamdhagat1@gmail.com',)
        ).fetchone()
        if not existing:
            c.execute(
                "INSERT INTO users (email, password_hash, display_name, role) VALUES (?,?,?,?)",
                ('shivamdhagat1@gmail.com',
                 generate_password_hash('Shivam@9806'),
                 'Shivam',
                 'admin')
            )
            admin_id = c.lastrowid
        else:
            admin_id = existing[0]

        # Seed initial saved articles if user has none
        saved_count = c.execute(
            "SELECT COUNT(*) FROM saved_articles WHERE user_id = ?", (admin_id,)
        ).fetchone()[0]
        if saved_count == 0:
            top_articles = c.execute(
                "SELECT id FROM articles ORDER BY score DESC, video_score DESC LIMIT 6"
            ).fetchall()
            for art in top_articles:
                c.execute(
                    "INSERT OR IGNORE INTO saved_articles (user_id, article_id) VALUES (?, ?)",
                    (admin_id, art[0])
                )
            print(f"[DB] Seeded {len(top_articles)} top saved articles for admin (user_id={admin_id}).")

        conn.commit()
        conn.close()
    print(f"[DB] Initialized => {DB_PATH}")

# ── User Operations ────────────────────────────────────────────────────────
def get_user_by_email(email: str):
    with _db_lock:
        conn = get_db()
        row  = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()
        conn.close()
    return dict(row) if row else None

def get_user_by_id(user_id: int):
    with _db_lock:
        conn = get_db()
        row  = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()
    return dict(row) if row else None

def verify_password(email: str, password: str):
    """Verify credentials and update last_login. Returns user dict or None."""
    user = get_user_by_email(email)
    if user and check_password_hash(user['password_hash'], password):
        with _db_lock:
            conn = get_db()
            conn.execute(
                "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?",
                (user['id'],)
            )
            conn.commit()
            conn.close()
        return user
    return None

# ── Article Operations ─────────────────────────────────────────────────────
def article_exists(link: str) -> bool:
    with _db_lock:
        conn   = get_db()
        exists = conn.execute("SELECT 1 FROM articles WHERE link = ?", (link,)).fetchone()
        conn.close()
    return bool(exists)

def upsert_article(title, link, source, topic, score, video_score, description, image_url=None):
    """Insert new article; on duplicate link update scores, image and refresh date."""
    with _db_lock:
        conn = get_db()
        try:
            conn.execute('''
                INSERT INTO articles (title, link, source, topic, score, video_score, description, image_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(link) DO UPDATE SET
                    score          = MAX(score, excluded.score),
                    video_score    = MAX(video_score, excluded.video_score),
                    image_url      = COALESCE(excluded.image_url, articles.image_url),
                    processed_date = CURRENT_TIMESTAMP
            ''', (title, link, source, topic, score, video_score, description, image_url))
            conn.commit()
        except Exception as e:
            print(f"[DB] upsert_article error: {e}")
        finally:
            conn.close()

def get_articles_paginated(topic='All Topics', page=1, per_page=12, sort_by='score'):
    """Return paginated + filtered article dict with is_new flag and normalized topic matching."""
    norm_topic = (topic or 'All Topics').strip()
    is_all = norm_topic.lower() in ('all topics', 'all', '')

    where         = "" if is_all else "WHERE LOWER(TRIM(topic)) = LOWER(TRIM(?))"
    params_filter = [] if is_all else [norm_topic]
    order         = ("score DESC, processed_date DESC"
                     if sort_by == 'score'
                     else "processed_date DESC, score DESC")

    with _db_lock:
        conn  = get_db()
        total = conn.execute(
            f"SELECT COUNT(*) FROM articles {where}", params_filter
        ).fetchone()[0]

        total_pages = max(1, (total + per_page - 1) // per_page)
        page        = max(1, min(page, total_pages))
        offset      = (page - 1) * per_page

        rows = conn.execute(
            f"SELECT * FROM articles {where} ORDER BY {order} LIMIT ? OFFSET ?",
            params_filter + [per_page, offset]
        ).fetchall()
        conn.close()

    now      = datetime.datetime.utcnow()
    articles = []
    for row in rows:
        a = dict(row)
        try:
            dt        = datetime.datetime.fromisoformat(a['processed_date'])
            a['is_new'] = (now - dt).total_seconds() < 7200   # 2-hour window
        except Exception:
            a['is_new'] = False
        articles.append(a)

    return {
        "articles":    articles,
        "total":       total,
        "page":        page,
        "total_pages": total_pages,
        "topic":       norm_topic,
    }

def get_all_topics():
    """Return list of topic objects with counts: [{'topic': 'All Topics', 'count': total}, ...]"""
    with _db_lock:
        conn = get_db()
        total_count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        rows = conn.execute(
            "SELECT TRIM(topic) as t, COUNT(*) as c FROM articles WHERE topic IS NOT NULL AND TRIM(topic) != '' GROUP BY TRIM(topic) ORDER BY c DESC"
        ).fetchall()
        conn.close()

    results = [{"topic": "All Topics", "count": total_count}]
    for r in rows:
        results.append({"topic": r[0], "count": r[1]})
    return results

def get_article_by_id(article_id: int):
    with _db_lock:
        conn = get_db()
        row  = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        conn.close()
    return dict(row) if row else None

def get_article_count() -> int:
    with _db_lock:
        conn  = get_db()
        count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        conn.close()
    return count

# ── Saved Articles ─────────────────────────────────────────────────────────
def save_article(user_id: int, article_id: int, notes: str = None) -> bool:
    with _db_lock:
        conn = get_db()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO saved_articles (user_id, article_id, notes) VALUES (?,?,?)",
                (user_id, article_id, notes)
            )
            conn.commit()
            return True
        except Exception as e:
            print(f"[DB] save_article error: {e}")
            return False
        finally:
            conn.close()

def unsave_article(user_id: int, article_id: int):
    with _db_lock:
        conn = get_db()
        conn.execute(
            "DELETE FROM saved_articles WHERE user_id = ? AND article_id = ?",
            (user_id, article_id)
        )
        conn.commit()
        conn.close()

def get_saved_articles(user_id: int):
    """Return articles bookmarked by a user, newest bookmark first."""
    with _db_lock:
        conn = get_db()
        rows = conn.execute('''
            SELECT a.*, sa.saved_at, sa.notes
            FROM articles a
            JOIN saved_articles sa ON a.id = sa.article_id
            WHERE sa.user_id = ?
            ORDER BY sa.saved_at DESC
        ''', (user_id,)).fetchall()
        conn.close()

    now      = datetime.datetime.utcnow()
    articles = []
    for row in rows:
        a = dict(row)
        try:
            dt        = datetime.datetime.fromisoformat(a['processed_date'])
            a['is_new'] = (now - dt).total_seconds() < 7200
        except Exception:
            a['is_new'] = False
        a['is_saved'] = True
        articles.append(a)
    return articles

def get_saved_article_ids(user_id: int) -> set:
    """Return the set of article IDs bookmarked by a user (for flag injection)."""
    with _db_lock:
        conn = get_db()
        rows = conn.execute(
            "SELECT article_id FROM saved_articles WHERE user_id = ?", (user_id,)
        ).fetchall()
        conn.close()
    return {r[0] for r in rows}

# ── YouTube Credentials ────────────────────────────────────────────────────
def store_youtube_credentials(user_id: int, credentials_json: str) -> bool:
    with _db_lock:
        conn = get_db()
        try:
            conn.execute('''
                INSERT INTO user_youtube_tokens (user_id, credentials)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    credentials = excluded.credentials
            ''', (user_id, credentials_json))
            conn.commit()
            return True
        except Exception as e:
            print(f"[DB] store_youtube_credentials error: {e}")
            return False
        finally:
            conn.close()

def get_youtube_credentials(user_id: int) -> str:
    with _db_lock:
        conn = get_db()
        row = conn.execute(
            "SELECT credentials FROM user_youtube_tokens WHERE user_id = ?", (user_id,)
        ).fetchone()
        conn.close()
    return row['credentials'] if row else None

