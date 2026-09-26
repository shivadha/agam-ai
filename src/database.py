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

            -- Free-web background agent: provider ledger ---------------------
            CREATE TABLE IF NOT EXISTS free_providers (
                id             TEXT PRIMARY KEY,
                name           TEXT NOT NULL,
                url            TEXT NOT NULL,
                kinds          TEXT NOT NULL DEFAULT '["image"]',
                quota_total    INTEGER,
                balance        INTEGER,
                used_count     INTEGER NOT NULL DEFAULT 0,
                balance_recipe TEXT NOT NULL DEFAULT '{}',
                status         TEXT NOT NULL DEFAULT 'active',
                enabled        INTEGER NOT NULL DEFAULT 1,
                priority       INTEGER NOT NULL DEFAULT 10,
                notes          TEXT,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_checked   TIMESTAMP
            );

            -- Scout-discovered candidates awaiting approval ------------------
            CREATE TABLE IF NOT EXISTS free_candidates (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                url         TEXT NOT NULL,
                kinds       TEXT NOT NULL DEFAULT '["image"]',
                quota_hint  TEXT,
                source      TEXT,
                source_url  TEXT,
                status      TEXT NOT NULL DEFAULT 'pending',
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(url)
            );

            -- Background agent job queue --------------------------------------
            CREATE TABLE IF NOT EXISTS agent_jobs (
                id            TEXT PRIMARY KEY,
                provider_id   TEXT NOT NULL,
                kind          TEXT NOT NULL,
                prompt        TEXT,
                input_path    TEXT,
                status        TEXT NOT NULL DEFAULT 'queued',
                result_path   TEXT,
                result_text   TEXT,
                error         TEXT,
                balance_after INTEGER,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at    TIMESTAMP,
                finished_at   TIMESTAMP,
                strategy      TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_agent_jobs_status ON agent_jobs(status, created_at);
            CREATE INDEX IF NOT EXISTS idx_free_providers_status ON free_providers(status, enabled, priority);

            -- Background agent long-term memory --------------------------------
            -- facts: stable truths ("veo_web generate button = 'Create'").
            -- lessons: learned from failures ("chatgpt_go logged out 2026-09-20").
            -- preferences: what worked best ("strategy video_chip wins on gemini_web").
            CREATE TABLE IF NOT EXISTS agent_memory (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                scope       TEXT NOT NULL DEFAULT 'global',
                kind        TEXT NOT NULL DEFAULT 'fact',
                content     TEXT NOT NULL,
                norm        TEXT NOT NULL,
                confidence  REAL NOT NULL DEFAULT 0.5,
                occurrences INTEGER NOT NULL DEFAULT 1,
                successes   INTEGER NOT NULL DEFAULT 0,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(scope, kind, norm)
            );
            CREATE INDEX IF NOT EXISTS idx_agent_memory_scope ON agent_memory(scope, kind, confidence);

            -- Workflow run persistence ---------------------------------------
            -- workflow_runs: one row per pipeline execution.
            -- node_results: every node execution (incl. retries/regenerations).
            -- node_logs: console log lines per run/node — powers the Errors tab.
            CREATE TABLE IF NOT EXISTS workflow_runs (
                run_id      TEXT PRIMARY KEY,
                name        TEXT,
                status      TEXT NOT NULL DEFAULT 'running',
                error       TEXT,
                started_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS node_results (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id      TEXT NOT NULL,
                node_id     TEXT NOT NULL,
                node_type   TEXT,
                status      TEXT,
                result_json TEXT,
                inputs_json TEXT,
                error       TEXT,
                recovered_via TEXT,
                attempt     INTEGER NOT NULL DEFAULT 1,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(run_id, node_id, attempt)
            );
            CREATE INDEX IF NOT EXISTS idx_node_results_run ON node_results(run_id, node_id);
            CREATE TABLE IF NOT EXISTS node_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id      TEXT NOT NULL,
                node_id     TEXT,
                level       TEXT NOT NULL DEFAULT 'info',
                message     TEXT,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_node_logs_run ON node_logs(run_id, created_at);
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

        # Auto-migration: strategy column on agent_jobs (which path the rotator took)
        try:
            c.execute("SELECT strategy FROM agent_jobs LIMIT 1")
        except sqlite3.OperationalError:
            try:
                c.execute("ALTER TABLE agent_jobs ADD COLUMN strategy TEXT DEFAULT ''")
                print("[DB] Added 'strategy' column to agent_jobs table.")
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


# ── Workflow run persistence (resume-from-failure + Errors tab) ────────────
def record_workflow_run(run_id: str, name: str = "") -> None:
    with _db_lock:
        conn = get_db()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO workflow_runs (run_id, name, status) VALUES (?, ?, 'running')",
                (run_id, name or ""),
            )
            conn.commit()
        finally:
            conn.close()


def finish_workflow_run(run_id: str, status: str, error: str = "") -> None:
    with _db_lock:
        conn = get_db()
        try:
            conn.execute(
                "UPDATE workflow_runs SET status = ?, error = ?, finished_at = CURRENT_TIMESTAMP WHERE run_id = ?",
                (status, error or "", run_id),
            )
            conn.commit()
        finally:
            conn.close()


def save_node_result(run_id: str, node_id: str, node_type: str, status: str,
                     result_json: str = "", inputs_json: str = "",
                     error: str = "", recovered_via: str = "") -> int:
    """Insert a node execution row; returns the attempt number."""
    with _db_lock:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT COALESCE(MAX(attempt), 0) FROM node_results WHERE run_id = ? AND node_id = ?",
                (run_id, node_id),
            ).fetchone()
            attempt = int(row[0] or 0) + 1
            conn.execute(
                """INSERT INTO node_results
                   (run_id, node_id, node_type, status, result_json, inputs_json,
                    error, recovered_via, attempt)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, node_id, node_type, status, result_json, inputs_json,
                 error or "", recovered_via or "", attempt),
            )
            conn.commit()
            return attempt
        finally:
            conn.close()


def save_node_log(run_id: str, node_id: str, level: str, message: str) -> None:
    with _db_lock:
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO node_logs (run_id, node_id, level, message) VALUES (?, ?, ?, ?)",
                (run_id, node_id, level, (message or "")[:4000]),
            )
            conn.commit()
        finally:
            conn.close()


def get_node_results(run_id: str) -> list:
    """Latest attempt per node for a run (dicts)."""
    with _db_lock:
        conn = get_db()
        try:
            rows = conn.execute(
                """SELECT node_id, node_type, status, result_json, inputs_json,
                          error, recovered_via, attempt, created_at
                   FROM node_results
                   WHERE run_id = ?
                     AND id IN (SELECT MAX(id) FROM node_results
                                WHERE run_id = ? GROUP BY node_id)
                   ORDER BY id""",
                (run_id, run_id),
            ).fetchall()
        finally:
            conn.close()
    return [dict(r) for r in rows]


def get_node_result_history(run_id: str, node_id: str) -> list:
    with _db_lock:
        conn = get_db()
        try:
            rows = conn.execute(
                """SELECT attempt, status, result_json, inputs_json, error,
                          recovered_via, created_at
                   FROM node_results WHERE run_id = ? AND node_id = ?
                   ORDER BY attempt""",
                (run_id, node_id),
            ).fetchall()
        finally:
            conn.close()
    return [dict(r) for r in rows]


def get_node_logs(run_id: str, level: str = None, limit: int = 500) -> list:
    with _db_lock:
        conn = get_db()
        try:
            if level:
                rows = conn.execute(
                    "SELECT node_id, level, message, created_at FROM node_logs"
                    " WHERE run_id = ? AND level = ? ORDER BY id DESC LIMIT ?",
                    (run_id, level, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT node_id, level, message, created_at FROM node_logs"
                    " WHERE run_id = ? ORDER BY id DESC LIMIT ?",
                    (run_id, limit),
                ).fetchall()
        finally:
            conn.close()
    return [dict(r) for r in rows]


def get_workflow_runs(limit: int = 30) -> list:
    with _db_lock:
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT run_id, name, status, error, started_at, finished_at"
                " FROM workflow_runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        finally:
            conn.close()
    return [dict(r) for r in rows]
