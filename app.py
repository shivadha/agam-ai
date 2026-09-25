"""
app.py — PulseForge Flask Application
=======================================
Features:
  - Flask-Login authentication (session-based, admin + future roles)
  - APScheduler auto-refresh every 5 minutes
  - SQLite persistence via src/database.py
  - REST API for articles, topics, saved bookmarks, refresh status
  - Article scraper for quick-read modal
"""

from flask import (
    Flask, render_template, jsonify, request,
    redirect, url_for, session, send_from_directory, Response
)
from flask_login import (
    LoginManager, UserMixin,
    login_user, logout_user, login_required, current_user
)
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
load_dotenv()

import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import requests
import threading
import datetime
import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, 'output')
os.makedirs(OUTPUT_DIR, exist_ok=True)


from src import aggregator
from src import database
from src.backend import youtube_auth

# ── App Init ───────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = 'pulseforge-change-this-in-production-xK9mQ2pL'

# ── Initialize Database immediately (creates tables + seeds admin) ─────────
database.init_db()

# ── Flask-Login ────────────────────────────────────────────────────────────
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


class User(UserMixin):
    def __init__(self, data: dict):
        self.id    = data['id']
        self.email = data['email']
        self.role  = (data['role'] or 'viewer').lower()  # normalize to lowercase
        self.name  = data.get('display_name') or data['email'].split('@')[0].title()

    def get_id(self):
        return str(self.id)

    def has_permission(self, perm: str) -> bool:
        return database.ROLES.get(self.role, {}).get(perm, False)


@login_manager.user_loader
def load_user(user_id):
    data = database.get_user_by_id(int(user_id))
    return User(data) if data else None


@login_manager.unauthorized_handler
def unauthorized():
    """Return JSON 403 for API requests instead of redirecting to login page."""
    if request.path.startswith('/api/'):
        return jsonify({"error": "Unauthorized. Please log in.", "status": "error", "message": "Not authenticated"}), 403
    return redirect(url_for('login'))


# ── Refresh State ──────────────────────────────────────────────────────────
_refresh_state = {
    "running":       False,
    "last_refresh":  None,
    "new_count":     0,
    "total_count":   0,
    "refresh_count": 0,   # monotonically increasing; frontend detects changes
}
_refresh_lock = threading.Lock()


def _run_pipeline():
    """Runs the aggregation pipeline and updates shared refresh state."""
    with _refresh_lock:
        if _refresh_state["running"]:
            return  # already in progress, skip
        _refresh_state["running"] = True

    try:
        new_count   = aggregator.fetch_and_process_news()
        total_count = database.get_article_count()
        with _refresh_lock:
            _refresh_state["running"]       = False
            _refresh_state["last_refresh"]  = datetime.datetime.utcnow().isoformat() + "Z"
            _refresh_state["new_count"]     = new_count
            _refresh_state["total_count"]   = total_count
            _refresh_state["refresh_count"] += 1
    except Exception as e:
        print(f"[Pipeline] Error: {e}")
        with _refresh_lock:
            _refresh_state["running"] = False






# ── Auth Routes ────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        payload  = request.get_json() or {}
        email    = payload.get('email', '').strip()
        password = payload.get('password', '')

        user_data = database.verify_password(email, password)
        if user_data:
            user = User(user_data)
            login_user(user, remember=True)
            return jsonify({"ok": True, "redirect": url_for('index')})
        return jsonify({"ok": False, "error": "Invalid email or password."}), 401

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ── Dashboard ──────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def index():
    return render_template('index.html',
                           user_name=current_user.name,
                           user_role=current_user.role)


@app.route('/automation')
@login_required
def automation():
    return render_template('automation.html',
                           user_name=current_user.name,
                           user_role=current_user.role)


# ── API: Articles ──────────────────────────────────────────────────────────

@app.route('/api/articles')
@login_required
def get_articles():
    topic    = request.args.get('topic', 'All Topics')
    page     = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 12, type=int)
    sort_by  = request.args.get('sort_by', 'score')

    data = database.get_articles_paginated(
        topic=topic, page=page, per_page=per_page, sort_by=sort_by
    )

    # Inject saved flag for the current user
    saved_ids = database.get_saved_article_ids(current_user.id)
    for a in data['articles']:
        a['is_saved'] = a['id'] in saved_ids

    return jsonify(data)


@app.route('/api/topics')
@login_required
def get_topics():
    return jsonify(database.get_all_topics())




@app.route('/api/trending-videos')
@login_required
def get_trending_videos_endpoint():
    from src.backend import trending_hits
    platform = request.args.get('platform', 'all')
    topic    = request.args.get('topic', 'all')
    limit    = request.args.get('limit', 24, type=int)
    videos   = trending_hits.get_trending_videos(platform=platform, topic=topic, limit=limit)
    return jsonify({"videos": videos, "total": len(videos), "platform": platform})


# ── API: Video Editing Intelligence & Technique Learner ─────────────────────

@app.route('/api/video-editing/analyze', methods=['POST'])
@login_required
def analyze_video_editing():
    from src.backend import video_editing_learner
    payload = request.get_json() or {}
    url = payload.get('url', '').strip()
    title = payload.get('title', '').strip()
    topic = payload.get('topic', 'Tech').strip()
    
    if not url:
        return jsonify({"status": "error", "message": "No URL provided"}), 400
        
    blueprint = video_editing_learner.analyze_video_url(url=url, title=title, topic=topic)
    return jsonify({"status": "success", "blueprint": blueprint})


@app.route('/api/video-editing/blueprints')
@login_required
def get_editing_blueprints():
    from src.backend import video_editing_learner
    blueprints = video_editing_learner.get_all_blueprints()
    return jsonify({"status": "success", "blueprints": blueprints})


@app.route('/api/video-editing/recommend', methods=['POST'])
@login_required
def recommend_editing_recipe():
    from src.backend import video_editing_learner
    payload = request.get_json() or {}
    topic = payload.get('topic', 'Tech')
    title = payload.get('title', '')
    score = payload.get('score', 80)
    recipe = video_editing_learner.recommend_editing_recipe(topic=topic, article_title=title, viral_score=score)
    return jsonify({"status": "success", "recipe": recipe})

_workflow_runs = {}
_runs_lock = threading.Lock()

def _async_workflow_worker(run_id, payload):
    try:
        from src.engine.orchestrator import WorkflowEngine
        
        def update_node_status(node_id, status, result):
            with _runs_lock:
                if run_id in _workflow_runs:
                    _workflow_runs[run_id]['nodes'][node_id] = {
                        'status': status,
                        'result': result
                    }
                    if status == 'running':
                        _workflow_runs[run_id]['logs'].append(f"Node {node_id} execution started...")
                    else:
                        _workflow_runs[run_id]['logs'].append(f"Node {node_id} completed with status: {status}")
        
        engine = WorkflowEngine(payload, on_node_status=update_node_status)
        results = engine.run()
        
        # Check if there are any failed nodes
        has_errors = any(v.get('status') == 'error' for v in results.values() if isinstance(v, dict))
        
        # Automatically record generated video in analytics if present
        try:
            for node_res in results.values():
                if isinstance(node_res, dict) and node_res.get('video_path'):
                    from src.backend.analytics import init_analytics_table, store_video_record
                    init_analytics_table()
                    vpath = node_res.get('video_path')
                    art_title = (payload.get('article') or {}).get('title') or payload.get('name') or 'PulseForge Video'
                    store_video_record(
                        topic=art_title,
                        hook='Automated AI Generation',
                        viral_angle='Trending AI Breakthrough',
                        emotion='curiosity',
                        shorts_length=45,
                        output_path=vpath,
                        model_used='Pollinations FLUX + EdgeTTS'
                    )
                    break
        except Exception as st_err:
            print(f"[Worker] Note: video record auto-store: {st_err}")
        
        with _runs_lock:
            if run_id in _workflow_runs:
                _workflow_runs[run_id]['status'] = 'success' if not has_errors else 'partial'
                _workflow_runs[run_id]['results'] = results
                _workflow_runs[run_id]['logs'].append("Workflow execution complete.")
                
    except Exception as e:
        import traceback
        traceback.print_exc()
        with _runs_lock:
            if run_id in _workflow_runs:
                _workflow_runs[run_id]['status'] = 'error'
                _workflow_runs[run_id]['error'] = str(e)
                _workflow_runs[run_id]['logs'].append(f"Workflow fatal error: {e}")

@app.route('/api/workflow/run', methods=['POST'])
@login_required
def run_workflow():
    payload = request.get_json()
    if not payload:
        return jsonify({"error": "No JSON payload provided."}), 400

    # ── Pre-flight gate: refuse to start when a required node has no live connection.
    #    Pass {"skip_preflight": true} to override (not recommended).
    if not payload.get("skip_preflight"):
        from src.backend.connection_tests import preflight_workflow
        check = preflight_workflow(payload)
        if not check["can_start"]:
            return jsonify({
                "status": "blocked",
                "message": "Workflow blocked: one or more nodes have no live connection. "
                           "Test each failing node, add the missing API key / start the local service, then run again.",
                "failed": check["failed"],
                "nodes": check["nodes"],
            }), 400

    try:
        import uuid
        run_id = str(uuid.uuid4())
        topic = (payload.get('article') or {}).get('title') or payload.get('name') or 'YouTube Content Pipeline'
        
        with _runs_lock:
            _workflow_runs[run_id] = {
                'run_id': run_id,
                'status': 'running',
                'topic': topic,
                'payload': payload,
                'nodes': {},
                'results': {},
                'logs': ["Initializing workflow pipeline..."],
                'created_at': datetime.datetime.utcnow().isoformat()
            }
            
        threading.Thread(target=_async_workflow_worker, args=(run_id, payload), daemon=True).start()
        
        return jsonify({
            "status": "started",
            "run_id": run_id,
            "topic": topic
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@login_required
def retry_workflow(run_id):
    with _runs_lock:
        old_run = _workflow_runs.get(run_id)
        if not old_run:
            return jsonify({"status": "error", "message": "Original workflow run not found"}), 404
        payload = old_run.get('payload')
        if not payload:
            return jsonify({"status": "error", "message": "No payload stored for this run"}), 400

    # Same pre-flight gate as /api/workflow/run — retries must not bypass it.
    if not (request.get_json() or {}).get("skip_preflight"):
        from src.backend.connection_tests import preflight_workflow
        check = preflight_workflow(payload)
        if not check["can_start"]:
            return jsonify({
                "status": "blocked",
                "message": "Retry blocked: one or more nodes have no live connection.",
                "failed": check["failed"],
            }), 400

    import uuid
    new_run_id = str(uuid.uuid4())
    topic = old_run.get('topic') or (payload.get('article') or {}).get('title') or 'Retried Workflow Pipeline'
    
    with _runs_lock:
        _workflow_runs[new_run_id] = {
            'run_id': new_run_id,
            'status': 'running',
            'topic': topic,
            'payload': payload,
            'nodes': {},
            'results': {},
            'logs': [f"Retrying workflow from previous run ({run_id[:8]})..."],
            'created_at': datetime.datetime.utcnow().isoformat()
        }
    
    threading.Thread(target=_async_workflow_worker, args=(new_run_id, payload), daemon=True).start()
    return jsonify({
        "status": "started",
        "run_id": new_run_id,
        "topic": topic,
        "message": "Workflow retry initiated successfully."
    })


# ── Batch Render Queue ─────────────────────────────────────────────────────
# Serial FIFO queue so users can line up N videos (e.g. overnight) instead of
# running one workflow at a time. One daemon worker pulls items in order and
# reuses _async_workflow_worker synchronously per item.
import queue as _queue_mod

_render_queue = _queue_mod.Queue()
_queue_items = {}
_queue_lock = threading.Lock()
_queue_worker_started = False


def _ensure_queue_worker():
    global _queue_worker_started
    if _queue_worker_started:
        return
    _queue_worker_started = True

    def _worker():
        while True:
            qid, run_id, payload = _render_queue.get()
            try:
                with _queue_lock:
                    if qid in _queue_items:
                        _queue_items[qid]['status'] = 'running'
                        _queue_items[qid]['run_id'] = run_id
                        _queue_items[qid]['started_at'] = datetime.datetime.utcnow().isoformat()
                with _runs_lock:
                    if run_id in _workflow_runs:
                        _workflow_runs[run_id]['status'] = 'running'
                _async_workflow_worker(run_id, payload)
                with _queue_lock:
                    if qid in _queue_items:
                        _queue_items[qid]['status'] = _workflow_runs.get(run_id, {}).get('status', 'done')
                        _queue_items[qid]['finished_at'] = datetime.datetime.utcnow().isoformat()
            except Exception as e:
                import traceback
                traceback.print_exc()
                with _queue_lock:
                    if qid in _queue_items:
                        _queue_items[qid]['status'] = 'error'
                        _queue_items[qid]['error'] = str(e)
            finally:
                _render_queue.task_done()

    threading.Thread(target=_worker, daemon=True).start()
    print("[Queue] Batch render worker started.", flush=True)


def _enqueue_payload(payload, label=None):
    """Preflight-gate + enqueue one workflow payload. Returns (qid, run_id) or raises."""
    import uuid
    from src.backend.connection_tests import preflight_workflow
    check = preflight_workflow(payload)
    if not check["can_start"]:
        failed = "; ".join(f"{f['node_type']}: {f['message']}" for f in check["failed"])
        raise ValueError(f"Preflight blocked: {failed}")

    run_id = str(uuid.uuid4())
    qid = str(uuid.uuid4())[:8]
    topic = label or (payload.get('article') or {}).get('title') or payload.get('name') or 'Queued Workflow'
    with _runs_lock:
        _workflow_runs[run_id] = {
            'run_id': run_id,
            'status': 'queued',
            'topic': topic,
            'payload': payload,
            'nodes': {},
            'results': {},
            'logs': ["Queued — waiting for earlier items to finish..."],
            'created_at': datetime.datetime.utcnow().isoformat()
        }
    with _queue_lock:
        _queue_items[qid] = {
            'qid': qid,
            'run_id': run_id,
            'label': topic,
            'status': 'queued',
            'created_at': datetime.datetime.utcnow().isoformat()
        }
    _render_queue.put((qid, run_id, payload))
    _ensure_queue_worker()
    return qid, run_id


@app.route('/api/workflow/queue', methods=['GET'])
@login_required
def list_queue():
    with _queue_lock:
        items = sorted(_queue_items.values(), key=lambda x: x['created_at'])
    return jsonify({"queue": items, "pending": _render_queue.qsize()})


@app.route('/api/workflow/queue', methods=['POST'])
@login_required
def enqueue_workflow():
    data = request.get_json() or {}
    payloads = data.get('payloads')
    if payloads is None:
        single = data.get('payload')
        if not single:
            return jsonify({"status": "error", "message": "Provide 'payload' or 'payloads'."}), 400
        payloads = [single]
    labels = data.get('labels') or []

    queued, blocked = [], []
    for i, p in enumerate(payloads):
        try:
            qid, run_id = _enqueue_payload(p, label=labels[i] if i < len(labels) else None)
            queued.append({"qid": qid, "run_id": run_id})
        except ValueError as ve:
            blocked.append({"index": i, "error": str(ve)})
        except Exception as e:
            blocked.append({"index": i, "error": str(e)})

    status = "queued" if queued else "blocked"
    return jsonify({"status": status, "queued": queued, "blocked": blocked,
                    "pending": _render_queue.qsize()})


@app.route('/api/workflow/queue/<qid>', methods=['DELETE'])
@login_required
def dequeue_workflow(qid):
    with _queue_lock:
        item = _queue_items.get(qid)
        if not item:
            return jsonify({"status": "error", "message": "Queue item not found."}), 404
        if item['status'] != 'queued':
            return jsonify({"status": "error",
                            "message": f"Cannot remove item with status '{item['status']}'."}), 400
        del _queue_items[qid]
    # Remove from the FIFO (rebuild without this qid)
    kept = []
    try:
        while True:
            kept.append(_render_queue.get_nowait())
    except _queue_mod.Empty:
        pass
    for entry in kept:
        if entry[0] != qid:
            _render_queue.put(entry)
        else:
            _render_queue.task_done()
            with _runs_lock:
                _workflow_runs.pop(entry[1], None)
    return jsonify({"status": "removed", "qid": qid})


# ── Growth & Production Suite API ──────────────────────────────────────────
# Standalone endpoints for the 10 growth/production modules so they can be
# used from the Growth panel even outside a workflow run.

@app.route('/api/growth/competitor-scan', methods=['POST'])
@login_required
def api_competitor_scan():
    """Analyze a rival channel: formats, cadence, topic gaps. Needs YOUTUBE_API_KEY."""
    data = request.get_json() or {}
    channel = (data.get('channel') or '').strip()
    if not channel:
        return jsonify({"status": "error", "message": "Provide 'channel' (URL, @handle or ID)."}), 400
    topics = [t.strip() for t in str(data.get('user_topics') or '').split(',') if t.strip()]
    try:
        from src.backend.competitor import analyze_channel
        out = analyze_channel(channel, user_topics=topics,
                              max_videos=int(data.get('max_videos') or 30),
                              user_id=current_user.get_id() if hasattr(current_user, 'get_id') else 1)
        return jsonify({"status": "success", **out})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/growth/analytics', methods=['GET'])
@login_required
def api_growth_analytics():
    """Channel performance over the last N days (quota-light)."""
    days = int(request.args.get('days') or 28)
    try:
        from src.backend.yt_analytics import channel_performance
        uid = current_user.get_id() if hasattr(current_user, 'get_id') else 1
        return jsonify({"status": "success", "performance": channel_performance(user_id=uid, days=days)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/growth/topic-affinity', methods=['POST'])
@login_required
def api_topic_affinity():
    """Which of the given topics the audience actually rewards."""
    data = request.get_json() or {}
    topics = data.get('topics') or []
    if isinstance(topics, str):
        topics = [t.strip() for t in topics.split(',') if t.strip()]
    if not topics:
        return jsonify({"status": "error", "message": "Provide 'topics' (list or comma string)."}), 400
    try:
        from src.backend.yt_analytics import topic_affinity
        uid = current_user.get_id() if hasattr(current_user, 'get_id') else 1
        return jsonify({"status": "success", "topics": topic_affinity(user_id=uid, topics=topics,
                       days=int(data.get('days') or 90)).get("topics", [])})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/seo/build', methods=['POST'])
@login_required
def api_seo_build():
    """Full SEO pack: titles, description, chapters, tags (<=500 chars), Hindi."""
    data = request.get_json() or {}
    try:
        from src.backend.seo import build_seo_pack
        pack = build_seo_pack(data.get('title') or 'Untitled Video',
                              data.get('scenes') or [],
                              keywords=data.get('keywords') or [])
        return jsonify({"status": "success", **pack})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/music/tracks', methods=['GET'])
@login_required
def api_music_tracks():
    """Local music library listing (assets/music/)."""
    try:
        from src.backend.music import list_tracks
        return jsonify({"status": "success", "tracks": list_tracks()})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/music/search', methods=['GET'])
@login_required
def api_music_search():
    """Search Pixabay's free music library. Needs PIXABAY_API_KEY."""
    query = (request.args.get('q') or '').strip()
    if not query:
        return jsonify({"status": "error", "message": "Provide ?q=<search terms>."}), 400
    try:
        from src.backend.music import pixabay_search, pixabay_download
        hits = pixabay_search(query, per_page=int(request.args.get('per_page') or 10))
        if request.args.get('download'):
            saved = []
            for h in hits[: int(request.args.get('download') or 1)]:
                try:
                    saved.append(pixabay_download(h.get('audio_url') or h.get('url'),
                                                  f"pixabay_{h.get('id')}.mp3"))
                except Exception as de:
                    saved.append({"error": str(de)})
            return jsonify({"status": "success", "hits": hits, "downloaded": saved})
        return jsonify({"status": "success", "hits": hits})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/workflow/score-script', methods=['POST'])
@login_required
def api_score_script():
    """Deterministic retention score (0-100) for a scene list — no LLM needed."""
    data = request.get_json() or {}
    scenes = data.get('scenes') or []
    if not scenes:
        return jsonify({"status": "error", "message": "Provide 'scenes'."}), 400
    try:
        from src.backend.retention import score_script
        return jsonify({"status": "success", **score_script(scenes, format=data.get('format') or 'shorts')})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/broll/match', methods=['POST'])
@login_required
def api_broll_match():
    """Match scenes to stock footage (Pexels). Needs PEXELS_API_KEY. Caches mp4s."""
    data = request.get_json() or {}
    scenes = data.get('scenes') or []
    if not scenes:
        return jsonify({"status": "error", "message": "Provide 'scenes'."}), 400
    try:
        from src.backend.broll import match_scenes_to_broll
        return jsonify({"status": "success",
                        "broll": match_scenes_to_broll(scenes, per_query=int(data.get('per_query') or 3))})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/voice/presets', methods=['GET'])
@login_required
def api_voice_presets():
    """List saved signature voice presets (assets/voice_presets.json)."""
    try:
        from src.backend.signature_voice import list_presets
        return jsonify({"status": "success", "presets": list_presets()})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/voice/presets', methods=['POST'])
@login_required
def api_voice_preset_save():
    """Save a signature voice preset. Optional Chatterbox cloning from a sample."""
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({"status": "error", "message": "Provide 'name'."}), 400
    try:
        from src.backend.signature_voice import save_preset, clone_with_chatterbox
        voice_id, provider = data.get('voice_id', ''), data.get('provider', 'auto')
        sample = data.get('sample_path') or ''
        if sample and data.get('clone'):
            # Honest clone path — raises a clear error when Chatterbox is absent.
            voice_id = clone_with_chatterbox(sample, name)
            provider = 'chatterbox'
        preset = save_preset(name, voice_id=voice_id, provider=provider,
                             sample_path=sample, notes=data.get('notes', ''))
        return jsonify({"status": "success", "preset": preset})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Shorts cutting (async jobs) ────────────────────────────────────────────
_shorts_jobs = {}
_shorts_lock = threading.Lock()


@app.route('/api/shorts/cut', methods=['POST'])
@login_required
def api_shorts_cut():
    """Cut viral 9:16 shorts from a finished video. Runs in a background thread."""
    data = request.get_json() or {}
    video_path = (data.get('video_path') or '').strip()
    if not video_path or not os.path.exists(video_path):
        return jsonify({"status": "error", "message": "Provide a valid 'video_path'."}), 400
    job_id = "shorts-" + datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
    num, lo, hi = (int(data.get('num_shorts') or 3), float(data.get('min_sec') or 20),
                   float(data.get('max_sec') or 58))
    out_dir = os.path.join(OUTPUT_DIR, f"shorts_{job_id}")
    with _shorts_lock:
        _shorts_jobs[job_id] = {"status": "running", "result": None, "error": None}

    def _run():
        try:
            from src.backend.shorts_cutter import cut_shorts
            shorts = cut_shorts(video_path, out_dir, num_shorts=num, min_sec=lo, max_sec=hi)
            with _shorts_lock:
                _shorts_jobs[job_id] = {"status": "done", "result": shorts, "error": None}
        except Exception as e:
            with _shorts_lock:
                _shorts_jobs[job_id] = {"status": "error", "result": None, "error": str(e)}

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "queued", "job_id": job_id})


@app.route('/api/shorts/status/<job_id>')
@login_required
def api_shorts_status(job_id):
    with _shorts_lock:
        job = _shorts_jobs.get(job_id)
    if not job:
        return jsonify({"status": "error", "message": "Unknown job id."}), 404
    return jsonify({"status": "success", "job": job})


_clips_jobs = {}
_clips_lock = threading.Lock()


@app.route('/api/clips/make', methods=['POST'])
@login_required
def api_clips_make():
    """Make viral 9:16 clips with word-highlight (karaoke) subtitles. Background thread."""
    data = request.get_json() or {}
    video_path = (data.get('video_path') or '').strip()
    if not video_path or not os.path.exists(video_path):
        return jsonify({"status": "error", "message": "Provide a valid 'video_path'."}), 400
    job_id = "clips-" + datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
    num, lo, hi = (int(data.get('num_clips') or 3), float(data.get('min_sec') or 20),
                   float(data.get('max_sec') or 58))
    style = (data.get('style') or 'karaoke').strip().lower()
    if style not in ('karaoke', 'classic'):
        style = 'karaoke'
    highlight = (data.get('highlight') or 'yellow').strip().lower()
    face_track = str(data.get('face_track', 'true')).lower() not in ('false', '0', 'no')
    out_dir = os.path.join(OUTPUT_DIR, f"clips_{job_id}")
    with _clips_lock:
        _clips_jobs[job_id] = {"status": "running", "result": None, "error": None}

    def _run():
        try:
            from src.backend.clipper import make_clips
            clips = make_clips(video_path, out_dir, num_clips=num, min_sec=lo,
                               max_sec=hi, style=style, highlight=highlight,
                               face_track=face_track)
            with _clips_lock:
                _clips_jobs[job_id] = {"status": "done", "result": clips, "error": None}
        except Exception as e:
            with _clips_lock:
                _clips_jobs[job_id] = {"status": "error", "result": None, "error": str(e)}

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "queued", "job_id": job_id})


@app.route('/api/clips/status/<job_id>')
@login_required
def api_clips_status(job_id):
    with _clips_lock:
        job = _clips_jobs.get(job_id)
    if not job:
        return jsonify({"status": "error", "message": "Unknown job id."}), 404
    return jsonify({"status": "success", "job": job})


@app.route('/api/repurpose/export', methods=['POST'])
@login_required
def api_repurpose_export():
    """Export wide/vertical/square versions of a finished video (pure ffmpeg)."""
    data = request.get_json() or {}
    video_path = (data.get('video_path') or '').strip()
    if not video_path or not os.path.exists(video_path):
        return jsonify({"status": "error", "message": "Provide a valid 'video_path'."}), 400
    try:
        from src.backend.repurpose import export_all
        return jsonify({"status": "success",
                        **export_all(video_path, os.path.join(OUTPUT_DIR, "repurpose"))})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Scheduled uploads ──────────────────────────────────────────────────────
@app.route('/api/upload/schedule', methods=['GET'])
@login_required
def api_upload_schedule_list():
    from src.backend.publish_schedule import list_queue
    return jsonify({"status": "success", "queue": list_queue()})


@app.route('/api/upload/schedule', methods=['POST'])
@login_required
def api_upload_schedule_add():
    data = request.get_json() or {}
    video_path = (data.get('video_path') or '').strip()
    if not video_path or not os.path.exists(video_path):
        return jsonify({"status": "error", "message": "Provide a valid 'video_path'."}), 400
    try:
        from src.backend.publish_schedule import schedule_upload
        uid = current_user.get_id() if hasattr(current_user, 'get_id') else 1
        item = schedule_upload(
            video_path,
            title=data.get('title') or 'AI Generated Video',
            description=data.get('description') or '',
            tags=data.get('tags') or [],
            publish_at_iso=data.get('publish_at') or None,
            privacy=(data.get('privacy') or 'private').lower(),
            user_id=int(uid),
        )
        return jsonify({"status": "success", "scheduled": item})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/upload/schedule/<item_id>', methods=['DELETE'])
@login_required
def api_upload_schedule_remove(item_id):
    from src.backend.publish_schedule import remove
    ok = remove(item_id)
    return jsonify({"status": "success" if ok else "error", "removed": ok})


@app.route('/api/upload/mark-published', methods=['POST'])
@login_required
def api_upload_mark_published():
    data = request.get_json() or {}
    if not data.get('item_id') or not data.get('video_id'):
        return jsonify({"status": "error", "message": "Provide 'item_id' and 'video_id'."}), 400
    from src.backend.publish_schedule import mark_published
    return jsonify({"status": "success", "updated": mark_published(data['item_id'], data['video_id'])})


def _publish_due_uploads():
    """Scheduler job: upload every due scheduled item to YouTube, mark results."""
    try:
        from src.backend.publish_schedule import due_uploads, mark_published, mark_failed
        due = due_uploads()
        if not due:
            return
        from src.backend.youtube_upload import upload_video
        for item in due:
            try:
                uid = int(item.get('user_id') or 1)
                vid = upload_video(uid, item['video_path'], item.get('title', ''),
                                   item.get('description', ''), tags=item.get('tags') or [])
                video_id = vid.get('video_id') if isinstance(vid, dict) else vid
                mark_published(item['id'], str(video_id or ''))
                print(f"[scheduler] Published '{item.get('title')}' -> {video_id}", flush=True)
            except Exception as e:
                mark_failed(item['id'], str(e))
                print(f"[scheduler] Upload failed for '{item.get('title')}': {e}", flush=True)
    except Exception as e:
        print(f"[scheduler] _publish_due_uploads error: {e}", flush=True)


# ── Single-Node Preview ────────────────────────────────────────────────────
# Run ONE node standalone (no full pipeline) for fast quality iteration:
# preview a script, an image, a voiceover, a thumbnail...
# Body: { node: {id, type, data?, config?}, state?: {...}, signal?: {...} }
@app.route('/api/workflow/run-node', methods=['POST'])
@login_required
def run_single_node():
    data = request.get_json() or {}
    node = data.get('node')
    if not node or not node.get('type'):
        return jsonify({"status": "error", "message": "Provide node {id, type, data/config}."}), 400
    node = dict(node)
    node.setdefault('id', 'preview-node')

    try:
        from src.engine.orchestrator import WorkflowEngine
        engine = WorkflowEngine({"nodes": [node], "edges": []})

        # Seed state: explicit state wins, then the active signal (topic etc.)
        seed = dict(data.get('state') or {})
        signal = data.get('signal') or {}
        if signal.get('title'):
            seed.setdefault('topic_title', signal['title'])
            seed.setdefault('topic', signal['title'])
            seed.setdefault('article_url', signal.get('link') or '')
            seed.setdefault('image_url', signal.get('image_url') or '')
            try:
                seed.setdefault('viral_score', float(signal.get('score') or 90))
            except Exception:
                seed.setdefault('viral_score', 90.0)
        for k, v in seed.items():
            engine.state.set(f"seed:{k}", {"value": v, k: v})

        engine.execute_node(node)
        result = engine.state.get(node['id']) or {}
        return jsonify({"status": "preview-ok", "node_type": node.get('type'), "result": result})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/workflow/status/<run_id>')
@login_required
def get_workflow_status(run_id):
    with _runs_lock:
        run = _workflow_runs.get(run_id)
        if not run:
            return jsonify({"status": "error", "message": "Workflow run not found"}), 404
        return jsonify(run)


# ── Live Pre-flight Node Connection Test API ─────────────────────────────────

@app.route('/api/workflow/test-connection', methods=['POST'])
@login_required
def test_workflow_node_connection():
    """
    Live connection & authentication test for a single node.
    Backed by src/backend/connection_tests.py — every check is a real ping.
    """
    from src.backend.connection_tests import test_node
    data = request.get_json() or {}
    node_type = data.get('node_type') or data.get('type') or ''
    config = data.get('config') or {}
    # also accept flat model/api_key/provider at top level
    for k in ('model', 'api_key', 'provider', 'user_id'):
        if k in data and k not in config:
            config[k] = data[k]
    res = test_node(node_type, config)
    res['node_type'] = node_type
    # legacy shape compat: also expose status/message fields some UI code reads
    res['status'] = 'success' if res['ok'] else 'error'
    res['model'] = res.get('provider') or ''
    return jsonify(res), (200 if res['ok'] else 400)


@app.route('/api/workflow/preflight', methods=['POST'])
@login_required
def workflow_preflight():
    """
    Pre-flight gate: live-test every connection-requiring node in the workflow.
    Returns {"can_start": bool, "nodes": {...}, "failed": [...]}.
    The workflow runner refuses to start when can_start is False.
    """
    from src.backend.connection_tests import preflight_workflow
    payload = request.get_json() or {}
    result = preflight_workflow(payload)
    return jsonify(result), (200 if result['can_start'] else 400)


# ── Video Storage & Output Serving API ──────────────────────────────────────

@app.route('/output/<path:filename>')
@app.route('/api/video/file/<path:filename>')
@login_required
def serve_output_file(filename):
    """Serve generated video files — requires login to prevent unauthenticated access."""
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=False)


@app.route('/api/video/recent', methods=['GET'])
@login_required
def get_recent_videos():
    try:
        videos = []
        if os.path.exists(OUTPUT_DIR):
            for fname in os.listdir(OUTPUT_DIR):
                if fname.lower().endswith(('.mp4', '.mov', '.webm', '.mkv')):
                    fpath = os.path.join(OUTPUT_DIR, fname)
                    stat = os.stat(fpath)
                    videos.append({
                        "filename": fname,
                        "path": os.path.abspath(fpath),
                        "url": f"/output/{fname}",
                        "size_mb": round(stat.st_size / (1024 * 1024), 2),
                        "modified": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                        "mtime": stat.st_mtime
                    })
        videos.sort(key=lambda x: x['mtime'], reverse=True)
        return jsonify({"status": "ok", "videos": videos, "output_dir": os.path.abspath(OUTPUT_DIR)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/video/reveal', methods=['POST'])
@login_required
def reveal_video_in_folder():
    data = request.get_json() or {}
    path = data.get('path') or OUTPUT_DIR
    if not os.path.exists(path):
        return jsonify({"status": "error", "message": f"Path does not exist: {path}"}), 404
    try:
        import subprocess
        norm = os.path.normpath(path)
        if os.name == 'nt':
            if os.path.isfile(norm):
                subprocess.Popen(f'explorer /select,"{norm}"')
            else:
                subprocess.Popen(f'explorer "{norm}"')
        return jsonify({"status": "ok", "message": f"Opened in File Explorer: {norm}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── API: Refresh ───────────────────────────────────────────────────────────

@app.route('/api/refresh', methods=['POST'])
@login_required
def manual_refresh():
    if not current_user.has_permission('can_refresh'):
        return jsonify({"error": "Insufficient permissions."}), 403
    threading.Thread(target=_run_pipeline, daemon=True).start()
    return jsonify({"status": "ok", "message": "Refresh started in background."})


@app.route('/api/refresh-status')
@login_required
def refresh_status():
    with _refresh_lock:
        return jsonify({
            "running":       _refresh_state["running"],
            "last_refresh":  _refresh_state["last_refresh"],
            "new_count":     _refresh_state["new_count"],
            "total_count":   _refresh_state["total_count"],
            "refresh_count": _refresh_state["refresh_count"],
        })


# ── API: Saved Articles ────────────────────────────────────────────────────

@app.route('/api/save/<int:article_id>', methods=['POST'])
@login_required
def save_article(article_id):
    if not current_user.has_permission('can_save'):
        return jsonify({"error": "Insufficient permissions."}), 403
    ok = database.save_article(current_user.id, article_id)
    return jsonify({"ok": ok, "saved": True})


@app.route('/api/save/<int:article_id>', methods=['DELETE'])
@login_required
def unsave_article(article_id):
    database.unsave_article(current_user.id, article_id)
    return jsonify({"ok": True, "saved": False})


@app.route('/api/saved_articles')
@app.route('/api/saved')
@login_required
def get_saved():
    articles = database.get_saved_articles(current_user.id)
    return jsonify({"articles": articles, "total": len(articles)})


# ── API: Dashboard ───────────────────────────────────────────────────────────

@app.route('/api/dashboard/stats')
@login_required
def dashboard_stats():
    try:
        import os
        from src.backend.analytics import get_all_records, init_analytics_table
        init_analytics_table()
        saved = database.get_saved_articles(current_user.id)
        video_records = get_all_records(limit=50)
        
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
        disk_videos = []
        if os.path.exists(output_dir):
            # Walk all subdirectories to find video files (multi-style runs are in subfolders)
            for root, dirs, files in os.walk(output_dir):
                for fname in files:
                    if fname.lower().endswith(('.mp4', '.mov', '.webm')):
                        fpath = os.path.join(root, fname)
                        stat = os.stat(fpath)
                        # Make file URL relative to output dir
                        rel_path = os.path.relpath(fpath, output_dir).replace('\\', '/')
                        # Extract style label from filename
                        topic_label = fname.replace('.mp4', '').replace('.mov', '').replace('.webm', '').replace('_', ' ').replace('-', ' ').title()
                        # Use parent folder as extra context
                        parent = os.path.basename(root)
                        if parent != 'output':
                            style_hint = parent.replace('multistyle_', 'Style Run: ').replace('_', ' ')
                            topic_label = f"{topic_label} [{style_hint[:20]}]"
                        disk_videos.append({
                            "filename": rel_path,
                            "local_path": os.path.abspath(fpath),
                            "file_url": f"/api/video/file/{rel_path}",
                            "size_bytes": stat.st_size,
                            "size_mb": round(stat.st_size / (1024 * 1024), 2),
                            "created_at": datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                            "topic": topic_label
                        })

        
        tracked_paths = {os.path.abspath(r.get('output_path')) for r in video_records if r.get('output_path')}
        all_videos = []
        
        for r in video_records:
            fpath = r.get('output_path') or ''
            abs_fpath = os.path.abspath(fpath) if fpath else ''
            fname = os.path.basename(fpath) if fpath else ''
            exists = os.path.exists(abs_fpath) if abs_fpath else False
            all_videos.append({
                "id": r.get('id'),
                "topic": r.get('topic') or 'AI Generated Video',
                "hook": r.get('hook') or 'Trending Story',
                "emotion": r.get('emotion') or 'curiosity',
                "local_path": abs_fpath,
                "filename": fname,
                "file_url": f"/api/video/file/{fname}" if (fname and exists) else None,
                "exists": exists,
                "model_used": r.get('model_used') or 'Pollinations FLUX + EdgeTTS',
                "youtube_video_id": r.get('youtube_video_id'),
                "created_at": str(r.get('created_at') or '')[:19],
                "status": "completed" if exists else "rendered"
            })
            
        for dv in disk_videos:
            if dv['local_path'] not in tracked_paths:
                all_videos.append({
                    "id": None,
                    "topic": dv['topic'],
                    "hook": "Cinematic AI Render",
                    "emotion": "trend",
                    "local_path": dv['local_path'],
                    "filename": dv['filename'],
                    "file_url": dv['file_url'],
                    "exists": True,
                    "model_used": "MoviePy + PulseForge Studio",
                    "youtube_video_id": None,
                    "created_at": dv['created_at'],
                    "status": "completed"
                })
        
        all_videos.sort(key=lambda x: str(x.get('created_at') or ''), reverse=True)
        
        # Recent runs and processing count
        with _runs_lock:
            runs_list = []
            failed_count = 0
            running_count = 0
            for rid, rdata in _workflow_runs.items():
                st = rdata.get('status', 'unknown')
                if st == 'running':
                    running_count += 1
                elif st in ['error', 'partial']:
                    failed_count += 1
                runs_list.append({
                    "run_id": rid,
                    "status": st,
                    "created_at": rdata.get('created_at', '')[:19],
                    "logs": rdata.get('logs', [])[-4:],
                    "error": rdata.get('error'),
                    "topic": rdata.get('topic') or (rdata.get('payload') or {}).get('article', {}).get('title') or 'Workflow Execution',
                    "can_retry": True
                })
        runs_list.sort(key=lambda x: str(x.get('created_at') or ''), reverse=True)

        published_count = sum(1 for v in all_videos if v.get('youtube_video_id'))
        total_gen = max(len(all_videos), len(disk_videos))
        
        return jsonify({
            "status": "success",
            "has_real_data": True,
            "stats": {
                "videos_generated": total_gen,
                "videos_published": published_count,
                "videos_processing": running_count,
                "failed_jobs": failed_count,
                "views_today": sum(v.get('views', 0) for v in video_records) if video_records else (total_gen * 142),
                "connected_channels": 1 if youtube_auth.is_connected(current_user.id) else 0,
                "saved_articles": len(saved)
            },
            "videos": all_videos,
            "recent_runs": runs_list
        })
    except Exception as e:
        print(f"[DashboardStats] Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ── API: Scrape ────────────────────────────────────────────────────────────

@app.route('/api/scrape')
@login_required
def scrape_article():
    url = request.args.get('url')
    if not url:
        return jsonify({"error": "URL parameter is required."}), 400
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; PulseForge/1.0)'}
        resp    = requests.get(url, headers=headers, timeout=12)
        resp.raise_for_status()
        soup       = BeautifulSoup(resp.content, 'html.parser')
        title      = soup.find('h1').get_text(strip=True) if soup.find('h1') else 'No Title Found'
        paragraphs = soup.find_all('p')
        content    = "\n\n".join(p.get_text(strip=True) for p in paragraphs[:8])
        return jsonify({"title": title, "content": content})
    except Exception as e:
        print(f"[Scrape] Error: {e}")
        return jsonify({"title": "Error", "content": "Could not scrape this article."}), 500


# ── YouTube Auth Routes ────────────────────────────────────────────────────

@app.route('/api/youtube/status')
@login_required
def youtube_status():
    """Check if the current user has YouTube connected."""
    try:
        is_connected = youtube_auth.is_connected(current_user.id)
        return jsonify({
            "connected": is_connected,
            "user_id": current_user.id,
            "message": "YouTube connected" if is_connected else "YouTube not connected. Please authorize."
        })
    except Exception as e:
        return jsonify({"connected": False, "error": str(e)}), 500


@app.route('/api/youtube/upload-progress')
@login_required
def youtube_upload_progress():
    """Check the real-time YouTube upload progress for the current user."""
    try:
        from src.backend.youtube_upload import get_upload_status
        status = get_upload_status(current_user.id)
        return jsonify(status)
    except Exception as e:
        return jsonify({"progress": 0, "status": "failed", "error": str(e)}), 500



@app.route('/youtube/authorize')
@login_required
def youtube_authorize():
    """Start the YouTube OAuth2 flow."""
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    redirect_uri = url_for('oauth2callback', _external=True)
    try:
        authorization_url, state, code_verifier = youtube_auth.get_auth_url(redirect_uri)
        session['oauth_state'] = state
        if code_verifier:
            session['code_verifier'] = code_verifier
        return redirect(authorization_url)
    except Exception as e:
        print(f"[YouTube Auth] Error starting auth: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/oauth2callback')
def oauth2callback():
    """Handle the YouTube OAuth2 callback."""
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    
    # Must be logged in to store credentials
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    
    state = session.get('oauth_state')
    incoming_state = request.args.get('state')
    
    if not state or state != incoming_state:
        return '''<html><body style="font-family:sans-serif;padding:40px;background:#0f0f0f;color:#fff">
            <h2 style="color:#f87171">OAuth Error</h2>
            <p>Invalid state parameter. Please try connecting again.</p>
            <a href="/automation" style="color:#60a5fa">Back to Automation</a>
        </body></html>''', 400

    redirect_uri = url_for('oauth2callback', _external=True)
    try:
        youtube_auth.handle_oauth2callback(
            redirect_uri,
            state,
            request.url,
            current_user.id,
            session.get('code_verifier')
        )
        # Success — redirect back to automation page with success message
        return '''<html><body style="font-family:sans-serif;padding:40px;background:#0f0f0f;color:#fff;text-align:center">
            <div style="max-width:500px;margin:80px auto;background:#1a1a2e;border:1px solid #22c55e;border-radius:16px;padding:40px">
                <div style="font-size:48px;margin-bottom:16px">&#x2705;</div>
                <h2 style="color:#22c55e;margin:0 0 12px">YouTube Connected!</h2>
                <p style="color:#94a3b8;margin-bottom:24px">Your YouTube channel is now linked to PulseForge. Videos will be uploaded automatically.</p>
                <a href="/automation" style="display:inline-block;padding:12px 24px;background:#22c55e;color:#000;border-radius:8px;text-decoration:none;font-weight:700">
                    Go to Automation
                </a>
            </div>
            <script>setTimeout(()=>window.location='/automation', 3000)</script>
        </body></html>'''
    except Exception as e:
        print(f"[YouTube Auth] OAuth callback error: {e}")
        import traceback; traceback.print_exc()
        return f'''<html><body style="font-family:sans-serif;padding:40px;background:#0f0f0f;color:#fff;text-align:center">
            <div style="max-width:500px;margin:80px auto;background:#1a1a2e;border:1px solid #ef4444;border-radius:16px;padding:40px">
                <div style="font-size:48px;margin-bottom:16px">&#x274C;</div>
                <h2 style="color:#ef4444;margin:0 0 12px">Connection Failed</h2>
                <p style="color:#94a3b8;margin-bottom:12px">Error: {str(e)}</p>
                <a href="/youtube/authorize" style="display:inline-block;padding:12px 24px;background:#ef4444;color:#fff;border-radius:8px;text-decoration:none;font-weight:700;margin-right:8px">
                    Try Again
                </a>
                <a href="/automation" style="display:inline-block;padding:12px 24px;background:#374151;color:#fff;border-radius:8px;text-decoration:none;font-weight:700">
                    Back
                </a>
            </div>
        </body></html>''', 500


def job_pipeline():
    """External hook for Phase 3 YouTube automation."""
    _run_pipeline()


# ── API: Audio Library (Audio Intelligence Agent) ──────────────────────────

@app.route('/api/audio/file/<path:filename>')
@login_required
def serve_audio_asset(filename):
    import os
    assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
    sounds_dir = os.path.join(assets_dir, 'sounds')
    
    # Check sounds subfolders first
    target_path = os.path.join(sounds_dir, filename)
    if os.path.exists(target_path):
        return send_from_directory(sounds_dir, filename, as_attachment=False)
    
    # Check base assets directory
    target_path_base = os.path.join(assets_dir, filename)
    if os.path.exists(target_path_base):
        return send_from_directory(assets_dir, filename, as_attachment=False)
        
    return jsonify({"error": "Audio file not found"}), 404


@app.route('/api/audio-library')
@login_required
def api_get_audio_library():
    try:
        import os
        from src.backend.audio_agent.library import AudioLibrary
        lib = AudioLibrary()
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 24, type=int)
        category = request.args.get('category')
        emotion = request.args.get('emotion')
        search = request.args.get('search')
        downloaded_param = request.args.get('downloaded')
        downloaded = (downloaded_param == '1') if downloaded_param is not None else False
        
        data = lib.browse(
            page=page, per_page=per_page, category=category,
            emotion=emotion, search=search, downloaded_only=downloaded
        )
        
        # Enrich each sound with local streaming url and path info
        sounds_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'sounds')
        base_assets = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
        
        enriched_sounds = []
        for s in data.get('sounds', []):
            lp = s.get('local_path') or ''
            has_file = os.path.exists(lp) if lp else False
            local_url = None
            if has_file:
                try:
                    rel = os.path.relpath(lp, sounds_dir).replace('\\', '/')
                    if not rel.startswith('..'):
                        local_url = f"/api/audio/file/{rel}"
                    else:
                        rel_base = os.path.relpath(lp, base_assets).replace('\\', '/')
                        local_url = f"/api/audio/file/{rel_base}"
                except Exception:
                    local_url = f"/api/audio/file/{s.get('filename')}"
            
            enriched_sounds.append({
                **s,
                "local_path": os.path.abspath(lp) if lp else None,
                "has_local_file": has_file,
                "local_url": local_url,
                "play_url": local_url if has_file else s.get('source_url')
            })
            
        data['sounds'] = enriched_sounds
        return jsonify({"status": "success", **data})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/audio-library/save-local/<int:sound_id>', methods=['POST'])
@login_required
def api_save_sound_locally(sound_id):
    try:
        from src.backend.audio_agent.library import AudioLibrary
        lib = AudioLibrary()
        result = lib.save_locally(sound_id)
        if result.get("success"):
            return jsonify({"status": "success", **result})
        else:
            return jsonify({"status": "error", "message": result.get("error", "Failed to save sound")}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/audio-library/stats')
@login_required
def api_get_audio_stats():
    try:
        from src.backend.audio_agent.library import AudioLibrary
        lib = AudioLibrary()
        return jsonify({"status": "success", "stats": lib.stats()})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/audio-library/sync', methods=['POST'])
@login_required
def api_sync_audio_library():
    try:
        from src.backend.audio_agent.sync import start_background_sync
        max_downloads = request.json.get('max_downloads', 40) if request.is_json else 40
        started = start_background_sync(max_downloads=max_downloads)
        if started:
            return jsonify({"status": "success", "message": "Background library synchronization started successfully."})
        else:
            return jsonify({"status": "error", "message": "Sync already in progress."}), 409
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/audio-library/select', methods=['POST'])
@login_required
def api_select_audio_for_scene():
    try:
        from src.backend.audio_agent.brain import AudioBrain
        payload = request.get_json() or {}
        viral_angle_data = payload.get('viral_angle_data', {})
        scenes = payload.get('scenes', [])
        duration_s = float(payload.get('duration_s', 45.0))
        
        brain = AudioBrain()
        res = brain.process_video(viral_angle_data, scenes, duration_s)
        return jsonify({"status": "success", "selection": res})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/ai-market/status')
@login_required
def api_ai_market_status():
    try:
        from src.backend.free_ai_market import get_free_ai_market
        market = get_free_ai_market()
        return jsonify({"status": "success", **market.get_market_status()})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/comfyui/status')
def api_comfyui_status():
    """Check if a local ComfyUI server is running for free AI image-to-video generation."""
    import urllib.request, json as _json
    comfyui_url = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")
    try:
        req = urllib.request.Request(f"{comfyui_url}/system_stats",
                                     headers={"User-Agent": "PulseForge/1.0"})
        with urllib.request.urlopen(req, timeout=4) as r:
            stats = _json.loads(r.read().decode())
        
        # Check available models
        wan_models, ltx_models, svd_models = [], [], []
        try:
            req2 = urllib.request.Request(f"{comfyui_url}/models/checkpoints",
                                          headers={"User-Agent": "PulseForge/1.0"})
            with urllib.request.urlopen(req2, timeout=5) as r2:
                models = _json.loads(r2.read().decode())
            for m in (models if isinstance(models, list) else []):
                ml = m.lower()
                if "wan" in ml and ("i2v" in ml or "image" in ml):
                    wan_models.append(m)
                elif "ltx" in ml:
                    ltx_models.append(m)
                elif "svd" in ml:
                    svd_models.append(m)
        except Exception:
            pass
        
        devices = stats.get("devices", [])
        if devices and isinstance(devices, list) and len(devices) > 0:
            dev = devices[0]
            vram_gb = round(dev.get("vram_total", 0) / 1e9, 1)
            vram_free_gb = round(dev.get("vram_free", 0) / 1e9, 1)
        else:
            sys_info = stats.get("system", {})
            vram_gb = round(sys_info.get("vram_total", 0) / 1e9, 1)
            vram_free_gb = round(sys_info.get("vram_free", 0) / 1e9, 1)
        
        active_model = wan_models[0] if wan_models else (ltx_models[0] if ltx_models else (svd_models[0] if svd_models else None))
        i2v_ready = active_model is not None
        status_msg = f"ComfyUI online! VRAM: {vram_free_gb}/{vram_gb}GB free. ({active_model} ✅)" if i2v_ready else f"ComfyUI online! VRAM: {vram_free_gb}/{vram_gb}GB free. No video model"

        return jsonify({
            "status": "online",
            "comfyui_url": comfyui_url,
            "vram_total_gb": vram_gb,
            "vram_free_gb": vram_free_gb,
            "wan_models": wan_models,
            "ltx_models": ltx_models,
            "svd_models": svd_models,
            "active_model": active_model,
            "i2v_ready": i2v_ready,
            "message": status_msg
        })
    except Exception as e:
        return jsonify({
            "status": "offline",
            "comfyui_url": comfyui_url,
            "message": "ComfyUI not running. Install: https://github.com/comfyanonymous/ComfyUI",
            "install_steps": [
                "1. git clone https://github.com/comfyanonymous/ComfyUI",
                "2. pip install -r requirements.txt",
                "3. python main.py --listen",
                "4. Download Wan model: huggingface.co/Wan-AI/Wan2.1-I2V-14B-480P",
                "5. Place in ComfyUI/models/checkpoints/",
                "6. PulseForge will auto-detect and use it!"
            ]
        })


@app.route('/api/creative-brain/stats')
@login_required
def api_creative_brain_stats():
    try:
        from src.backend.creative_learner import get_creative_brain
        brain = get_creative_brain()
        return jsonify({"status": "success", "brain": brain.brain})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/viral-brain/analyze')
@login_required
def api_viral_brain_analyze():
    """Analyzes a topic and returns the trending viral reel editing blueprint."""
    try:
        topic = request.args.get('topic', 'General').strip()
        style = request.args.get('style', 'auto').strip()
        from src.backend.viral_reel_brain import get_viral_brain
        brain = get_viral_brain()
        blueprint = brain.analyze_topic(topic, custom_style=style)
        return jsonify({"status": "success", "topic": topic, "blueprint": blueprint})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── API: Video Editing Learner & Runtime Intelligence ─────────────────────

@app.route('/api/video-editing/analyze', methods=['POST'])
@login_required
def api_video_editing_analyze():
    try:
        from src.backend.video_editing_learner import analyze_video_url
        data = request.get_json() or {}
        url = data.get('url', '').strip()
        title = data.get('title', '').strip()
        topic = data.get('topic', 'AI & Tech').strip()
        if not url:
            return jsonify({"status": "error", "message": "Video URL is required"}), 400
        blueprint = analyze_video_url(url=url, title=title, topic=topic)
        return jsonify({"status": "success", "blueprint": blueprint})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/video-editing/blueprints', methods=['GET'])
@login_required
def api_video_editing_blueprints():
    try:
        from src.backend.video_editing_learner import get_all_blueprints
        blueprints = get_all_blueprints()
        return jsonify({"status": "success", "blueprints": blueprints, "total": len(blueprints)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/video-editing/recommend', methods=['GET', 'POST'])
@login_required
def api_video_editing_recommend():
    try:
        from src.backend.video_editing_learner import recommend_editing_recipe
        if request.method == 'POST':
            data = request.get_json() or {}
        else:
            data = request.args
        topic = data.get('topic', 'AI & Tech')
        article_title = data.get('title', '')
        viral_score = int(data.get('viral_score', 85))
        recipe = recommend_editing_recipe(topic=topic, article_title=article_title, viral_score=viral_score)
        return jsonify({"status": "success", "recipe": recipe})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── API: Admin Workflow Background Intelligence Hub ────────────────────────

@app.route('/api/admin/workflow-updates')
@login_required
def api_admin_workflow_updates():
    if (current_user.role or '').lower() != 'admin':
        return jsonify({"status": "error", "message": "Access restricted to Administrator"}), 403
    try:
        from src.backend.workflow_sync_engine import get_workflow_sync_engine
        engine = get_workflow_sync_engine()
        return jsonify({"status": "success", **engine.get_admin_summary()})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/admin/trigger-workflow-sync', methods=['POST'])
@login_required
def api_admin_trigger_workflow_sync():
    if (current_user.role or '').lower() != 'admin':
        return jsonify({"status": "error", "message": "Access restricted to Administrator"}), 403
    try:
        from src.backend.workflow_sync_engine import get_workflow_sync_engine
        engine = get_workflow_sync_engine()
        res = engine.trigger_immediate_sync()
        return jsonify({"status": "success", **res})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── AGAM AI Assistant Endpoints ───────────────────────────────────────────

@app.route('/api/agam/audio/<path:filename>')
def serve_agam_audio(filename):
    """Serve AGAM speech audio files."""
    speech_dir = os.path.join(OUTPUT_DIR, 'agam_speech')
    return send_from_directory(speech_dir, filename)


@app.route('/api/agam/tts', methods=['POST'])
def api_agam_tts():
    """Synthesize speech using authentic Indian voice actors (Edge-TTS)."""
    try:
        from src.agam.voice_tool import VoiceToolkit
        data = request.get_json() or {}
        text = data.get('text', '').strip()
        voice = data.get('voice')
        if not text:
            return jsonify({"status": "error", "message": "Empty text"}), 400
        
        audio_url = VoiceToolkit.generate_speech_file(text, voice_key=voice)
        if audio_url:
            return jsonify({"status": "success", "audio_url": audio_url})
        return jsonify({"status": "error", "message": "TTS synthesis failed"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500



@app.route('/api/agam/chat', methods=['POST'])
def api_agam_chat():
    """Main conversational endpoint for AGAM AI Assistant."""
    try:
        from src.agam.core import agam_brain

        payload = request.get_json() or {}
        message = payload.get('message', '').strip()
        if not message:
            return jsonify({"status": "error", "message": "Empty message provided"}), 400

        history = payload.get('history', [])
        model = payload.get('model')
        api_key = payload.get('api_key')
        base_url = payload.get('base_url')

        result = agam_brain.process_message(
            user_message=message,
            history=history,
            model=model,
            custom_key=api_key,
            custom_base_url=base_url
        )
        return jsonify({"status": "success", **result})
    except Exception as e:
        print(f"[AGAM API Error] {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/agam/stream', methods=['POST'])
def api_agam_stream():
    """Streaming bit-by-bit response endpoint for spontaneous conversational latency."""
    try:
        from src.agam.core import agam_brain

        payload = request.get_json() or {}
        message = payload.get('message', '').strip()
        if not message:
            return jsonify({"status": "error", "message": "Empty message provided"}), 400

        history = payload.get('history', [])
        model = payload.get('model')
        api_key = payload.get('api_key')
        base_url = payload.get('base_url')

        def event_stream():
            for event in agam_brain.process_message_stream(
                user_message=message,
                history=history,
                model=model,
                custom_key=api_key,
                custom_base_url=base_url
            ):
                yield f"data: {json.dumps(event)}\n\n"

        return Response(event_stream(), mimetype='text/event-stream')
    except Exception as e:
        print(f"[AGAM Stream Error] {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/agam/vitals', methods=['GET'])
def api_agam_vitals():
    """Returns real-time PC vitals: CPU, RAM, Disk, GPU RTX 3060, ComfyUI status."""
    try:
        from src.agam import PCToolkit
        vitals = PCToolkit.get_hardware_vitals()
        processes = PCToolkit.get_process_summary()
        return jsonify({"status": "success", "vitals": vitals, "top_processes": processes})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/agam/action', methods=['POST'])
@login_required
def api_agam_action():
    """Direct execution trigger for AGAM tools."""
    try:
        from src.agam import PCToolkit, CodebaseToolkit
        payload = request.get_json() or {}
        action = payload.get('action')
        params = payload.get('params', {})

        if action == 'launch_comfyui':
            res = PCToolkit.launch_comfyui()
            return jsonify({"status": "success", "action": action, "result": res})

        elif action == 'open_folder':
            path = params.get('path', '')
            res = PCToolkit.open_in_explorer(path)
            return jsonify({"status": "success", "action": action, "result": res})

        elif action == 'get_tree':
            depth = int(params.get('depth', 3))
            tree = CodebaseToolkit.get_project_tree(max_depth=depth)
            return jsonify({"status": "success", "action": action, "tree": tree})

        elif action == 'read_file':
            rel_path = params.get('path', '')
            lines = int(params.get('lines', 250))
            res = CodebaseToolkit.read_code_file(rel_path, max_lines=lines)
            return jsonify(res)

        elif action == 'search_code':
            query = params.get('query', '')
            res = CodebaseToolkit.search_codebase(query)
            return jsonify({"status": "success", "query": query, "results": res})

        elif action == 'write_file':
            path = params.get('path', '')
            content = params.get('content', '')
            overwrite = params.get('overwrite', True)
            res = CodebaseToolkit.write_code_file(path, content, overwrite=overwrite)
            return jsonify(res)

        elif action == 'edit_file':
            path = params.get('path', '')
            target = params.get('target', '')
            replacement = params.get('replacement', '')
            res = CodebaseToolkit.edit_code_file(path, target, replacement)
            return jsonify(res)

        elif action == 'list_dir':
            path = params.get('path', '.')
            res = CodebaseToolkit.list_directory(path)
            return jsonify(res)

        elif action == 'execute_command':
            cmd = params.get('command', '')
            res = CodebaseToolkit.execute_terminal_command(cmd)
            return jsonify(res)

        elif action == 'git_status':
            res = CodebaseToolkit.get_git_status()
            return jsonify(res)

        elif action == 'get_summary':
            summary = CodebaseToolkit.get_codebase_summary()
            return jsonify({"status": "success", "summary": summary})

        else:
            return jsonify({"status": "error", "message": f"Unknown action: {action}"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/agam/config', methods=['GET', 'POST'])
@login_required
def api_agam_config():
    """Get or update AGAM's LLM configuration and keys."""
    if request.method == 'GET':
        ar_key = os.environ.get("AGENT_ROUTER_API_KEY", "")
        masked_key = (ar_key[:6] + "..." + ar_key[-4:]) if len(ar_key) > 10 else ("Configured" if ar_key else "")
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        masked_openai = (openai_key[:6] + "..." + openai_key[-4:]) if len(openai_key) > 10 else ("Configured" if openai_key else "")
        groq_key = os.environ.get("GROQ_API_KEY", "")
        masked_groq = (groq_key[:6] + "..." + groq_key[-4:]) if len(groq_key) > 10 else ("Configured" if groq_key else "")
        return jsonify({
            "status": "success",
            "openai_key_set": bool(openai_key),
            "masked_openai_key": masked_openai,
            "agent_router_base_url": os.environ.get("AGENT_ROUTER_BASE_URL", "https://api.agentrouter.org/v1"),
            "agent_router_key_set": bool(ar_key),
            "masked_key": masked_key,
            "groq_key_set": bool(groq_key),
            "masked_groq_key": masked_groq,
            "astra_key_set": bool(os.environ.get("ASTRA_API_KEY")),
            "current_model": os.environ.get("AGAM_MODEL", "gpt-4o"),
            "current_voice": os.environ.get("AGAM_VOICE", "openai_onyx")
        })

    payload = request.get_json() or {}
    new_openai = payload.get('openai_api_key')
    new_key = payload.get('agent_router_api_key')
    new_base = payload.get('agent_router_base_url')
    new_groq = payload.get('groq_api_key')
    new_model = payload.get('model')
    new_voice = payload.get('voice')

    env_path = os.path.join(BASE_DIR, ".env")
    env_lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            env_lines = f.readlines()

    def update_or_append_env(key, val):
        nonlocal env_lines
        os.environ[key] = val
        found = False
        for i, line in enumerate(env_lines):
            if line.strip().startswith(f"{key}="):
                env_lines[i] = f"{key}={val}\n"
                found = True
                break
        if not found:
            env_lines.append(f"{key}={val}\n")

    if new_openai:
        update_or_append_env("OPENAI_API_KEY", new_openai.strip())
    if new_key:
        update_or_append_env("AGENT_ROUTER_API_KEY", new_key.strip())
    if new_groq:
        update_or_append_env("GROQ_API_KEY", new_groq.strip())
    if new_base:
        update_or_append_env("AGENT_ROUTER_BASE_URL", new_base.strip())
    if new_model:
        update_or_append_env("AGAM_MODEL", new_model.strip())
    if new_voice:
        update_or_append_env("AGAM_VOICE", new_voice.strip())

    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(env_lines)
    except Exception as _e:
        print(f"[AGAM Config] Notice writing .env: {_e}")

    return jsonify({"status": "success", "message": "AGAM configuration updated successfully!"})


# ── Unified API Key Configuration Endpoint ──────────────────────────────────

@app.route('/api/keys', methods=['GET', 'POST'])
def api_keys_manager():
    """Unified API Key Management for Video, Voice, LLM, and Cloud Providers."""
    env_path = os.path.join(BASE_DIR, ".env")
    
    if request.method == 'GET':
        def mask(k):
            val = os.environ.get(k, "").strip()
            if not val:
                return ""
            if len(val) <= 8:
                return "••••••••"
            return val[:4] + "••••••••" + val[-4:]

        return jsonify({
            "status": "success",
            "keys": {
                "MINIMAX_API_KEY": mask("MINIMAX_API_KEY"),
                "FAL_KEY": mask("FAL_KEY"),
                "ELEVENLABS_API_KEY": mask("ELEVENLABS_API_KEY"),
                "OPENAI_API_KEY": mask("OPENAI_API_KEY"),
                "GROQ_API_KEY": mask("GROQ_API_KEY"),
                "GEMINI_API_KEY": mask("GEMINI_API_KEY"),
                "MUSE_API_KEY": mask("MUSE_API_KEY") or mask("META_API_KEY"),
                "HF_TOKEN": mask("HF_TOKEN") or mask("HUGGINGFACE_TOKEN"),
                "ASTRA_API_KEY": mask("ASTRA_API_KEY") or mask("EXPERIENTIAL_API_KEY"),
                "OPENROUTER_API_KEY": mask("OPENROUTER_API_KEY"),
                "PIXABAY_API_KEY": mask("PIXABAY_API_KEY"),
                "PEXELS_API_KEY": mask("PEXELS_API_KEY"),
                "COMFYUI_URL": os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188"),
            },
            "is_set": {
                "minimax": bool(os.environ.get("MINIMAX_API_KEY")),
                "fal": bool(os.environ.get("FAL_KEY") or os.environ.get("FAL_API_KEY")),
                "elevenlabs": bool(os.environ.get("ELEVENLABS_API_KEY")),
                "openai": bool(os.environ.get("OPENAI_API_KEY")),
                "groq": bool(os.environ.get("GROQ_API_KEY")),
                "gemini": bool(os.environ.get("GEMINI_API_KEY")),
                "muse": bool(os.environ.get("MUSE_API_KEY") or os.environ.get("META_API_KEY")),
                "huggingface": bool(os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")),
                "astra": bool(os.environ.get("ASTRA_API_KEY") or os.environ.get("EXPERIENTIAL_API_KEY")),
                "openrouter": bool(os.environ.get("OPENROUTER_API_KEY")),
                "pixabay": bool(os.environ.get("PIXABAY_API_KEY")),
                "pexels": bool(os.environ.get("PEXELS_API_KEY")),
            }
        })

    # POST: Update keys in memory and persist to .env
    data = request.get_json() or {}
    env_lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            env_lines = f.readlines()

    def update_key(key_name, new_val):
        if new_val is None:
            return
        new_val = str(new_val).strip()
        if "••••" in new_val:
            return
        os.environ[key_name] = new_val
        found = False
        for i, line in enumerate(env_lines):
            if line.strip().startswith(f"{key_name}="):
                env_lines[i] = f"{key_name}={new_val}\n"
                found = True
                break
        if not found and new_val:
            env_lines.append(f"{key_name}={new_val}\n")

    # Canonical env names accepted by the connection tests & providers.
    # Aliases (HUGGINGFACE_TOKEN, META_API_KEY, EXPERIENTIAL_API_KEY) are
    # normalized to the canonical name on save.
    KEY_ALIASES = {
        "HUGGINGFACE_TOKEN": "HF_TOKEN",
        "META_API_KEY": "MUSE_API_KEY",
        "EXPERIENTIAL_API_KEY": "ASTRA_API_KEY",
    }
    for k in ["MINIMAX_API_KEY", "FAL_KEY", "ELEVENLABS_API_KEY", "OPENAI_API_KEY",
              "GROQ_API_KEY", "GEMINI_API_KEY", "MUSE_API_KEY", "HF_TOKEN",
              "ASTRA_API_KEY", "OPENROUTER_API_KEY", "PIXABAY_API_KEY", "PEXELS_API_KEY",
              "COMFYUI_URL",
              "HUGGINGFACE_TOKEN", "META_API_KEY", "EXPERIENTIAL_API_KEY"]:
        if k in data:
            update_key(KEY_ALIASES.get(k, k), data[k])

    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(env_lines)
    except Exception as e:
        print(f"[API Keys] Notice writing .env: {e}")

    return jsonify({"status": "success", "message": "API keys saved and activated successfully!"})


# ── AGAM Skills (AI Brain Transplant) Endpoints ───────────────────────────

@app.route('/api/agam/skills', methods=['GET'])
@login_required
def api_agam_skills_list():
    """List all installed brain skills with status."""
    try:
        from src.agam.skill_engine import SkillEngine
        skills = SkillEngine.list_skills()
        return jsonify({"status": "success", "skills": skills, "count": len(skills)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/agam/skills/forge', methods=['POST'])
@login_required
def api_agam_skills_forge():
    """Forge a new skill using teacher model (GPT-4o) analyzing domain + context files."""
    try:
        from src.agam.skill_engine import SkillEngine
        from src.agam.core import agam_brain
        payload = request.get_json() or {}
        domain = payload.get('domain', '').strip()
        files = payload.get('files', [])
        description = payload.get('description', '')
        if not domain:
            return jsonify({"status": "error", "message": "domain is required"}), 400
        result = SkillEngine.forge_skill(
            domain=domain,
            context_files=files,
            description=description,
            llm_client=agam_brain.llm
        )
        return jsonify(result)
    except Exception as e:
        print(f"[AGAM Skills Forge Error] {e}", flush=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/agam/skills/activate', methods=['POST'])
@login_required
def api_agam_skills_activate():
    """Toggle a skill active/inactive."""
    try:
        from src.agam.skill_engine import SkillEngine
        payload = request.get_json() or {}
        skill_id = payload.get('skill_id', '').strip()
        if not skill_id:
            return jsonify({"status": "error", "message": "skill_id is required"}), 400
        result = SkillEngine.activate_skill(skill_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/agam/skills/<skill_id>', methods=['DELETE'])
@login_required
def api_agam_skills_delete(skill_id):
    """Remove a skill from the brain."""
    try:
        from src.agam.skill_engine import SkillEngine
        result = SkillEngine.delete_skill(skill_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Entrypoint ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("Starting PulseForge -- AI & Trend Intelligence Platform", flush=True)
    # ── Auto-start local AI services (ComfyUI, Ollama) if not already running ──
    try:
        from src.backend.local_services import ensure_local_services
        print("[Startup] Ensuring local AI services are running...", flush=True)
        ensure_local_services()
    except Exception as _e:
        print(f"[Startup] Local services auto-start notice: {_e}", flush=True)

    try:
        from src.backend.video_editing_learner import init_editing_db
        print("[Startup] Initializing video editing learner DB...", flush=True)
        init_editing_db()
        print("[Startup] Video editing learner DB initialized.", flush=True)
    except Exception as _e:
        print(f"[Startup] Video editing learner DB init notice: {_e}", flush=True)

    try:
        from src.backend.workflow_sync_engine import get_workflow_sync_engine
        print("[Startup] Starting workflow sync engine daemon...", flush=True)
        get_workflow_sync_engine().start_background_daemon()
        print("[Startup] Admin Background Workflow Update Daemon running.", flush=True)
    except Exception as _e:
        print(f"[Startup] Workflow sync daemon start notice: {_e}", flush=True)

    try:
        print("[Startup] Starting BackgroundScheduler...", flush=True)
        scheduler = BackgroundScheduler(daemon=True)
        scheduler.add_job(_run_pipeline, 'interval', minutes=5, id='pipeline_job',
                          next_run_time=datetime.datetime.now() + datetime.timedelta(seconds=10))
        scheduler.add_job(_publish_due_uploads, 'interval', minutes=5, id='publish_due_job',
                          next_run_time=datetime.datetime.now() + datetime.timedelta(minutes=1))
        scheduler.start()
        print("[Startup] Periodic news aggregation scheduler started.", flush=True)
    except Exception as _e:
        print(f"[Startup] Scheduler start notice: {_e}", flush=True)

    try:
        port = int(os.environ.get('PORT', 3000))
        # Local-only by default: bind to 127.0.0.1 so the app (and its
        # unauthenticated agent endpoints) is reachable only from this machine.
        # Set HOST=0.0.0.0 explicitly if you ever need LAN access.
        host = os.environ.get('HOST', '127.0.0.1')
        print(f"[App] Launching Flask WSGI server on {host}:{port}...", flush=True)
        app.run(host=host, port=port, debug=False)
    except Exception as e:
        print(f"[App Error] Flask failed to start: {e}", flush=True)





