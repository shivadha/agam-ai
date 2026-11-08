import os

code = r"""
\"\"\"
background_media_service.py - PulseForge Zero-Budget Shorts Generator
FREE: Gemini Imagen3, Pollinations, HuggingFace FLUX, DALL-E3
Video: FFmpeg local, Audio: edge-tts local
\"\"\"
import os, json, time, uuid, threading, subprocess, tempfile
import urllib.request, urllib.parse, base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict

BASE_DIR   = Path(__file__).resolve().parents[2]
DATA_DIR   = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
SHORTS_DIR = OUTPUT_DIR / "shorts"
IMAGES_DIR = OUTPUT_DIR / "images" / "4k"
MUSIC_DIR  = BASE_DIR / "assets" / "sounds" / "music"
QUEUE_FILE = DATA_DIR / "media_jobs.json"

for d in [DATA_DIR, OUTPUT_DIR, SHORTS_DIR, IMAGES_DIR]:
    d.mkdir(parents=True, exist_ok=True)

_queue_lock = threading.Lock()
_shutdown   = threading.Event()


def _load_queue():
    if not QUEUE_FILE.exists():
        return []
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_queue(items):
    tmp = str(QUEUE_FILE) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
    os.replace(tmp, str(QUEUE_FILE))


def _update_job(job_id, **kwargs):
    with _queue_lock:
        items = _load_queue()
        for item in items:
            if item.get("id") == job_id:
                item.update(kwargs)
                item["updated_at"] = datetime.now(timezone.utc).isoformat()
        _save_queue(items)


def _try_gemini_imagen(prompt, out_path):
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        return False
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.ImageGenerationModel("imagen-3.0-generate-001")
        result = model.generate_images(
            prompt=prompt, number_of_images=1, aspect_ratio="9:16",
            safety_filter_level="block_only_high",
        )
        if result.images:
            with open(out_path, "wb") as f:
                f.write(result.images[0]._image_bytes)
            print(f"[MediaService] Gemini Imagen3 OK -> {out_path}")
            return True
    except Exception as e:
        print(f"[MediaService] Gemini Imagen note: {e}")
    return False


def _try_pollinations(prompt, out_path, width=1080, height=1920):
    try:
        encoded = urllib.parse.quote(prompt[:400])
        url = (f"https://image.pollinations.ai/prompt/{encoded}"
               f"?width={width}&height={height}&model=flux&nologo=true&enhance=true")
        req = urllib.request.Request(url, headers={"User-Agent": "PulseForge/2.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        if len(data) > 5000:
            with open(out_path, "wb") as f:
                f.write(data)
            print(f"[MediaService] Pollinations OK ({len(data)//1024}KB) -> {out_path}")
            return True
    except Exception as e:
        print(f"[MediaService] Pollinations note: {e}")
    return False


def _try_hf_flux(prompt, out_path):
    try:
        import requests as rq
        hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HF_API_KEY", "")
        headers = {"Content-Type": "application/json"}
        if hf_token:
            headers["Authorization"] = f"Bearer {hf_token}"
        url = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-dev"
        resp = rq.post(url, headers=headers,
                       json={"inputs": prompt[:500],
                             "parameters": {"width": 768, "height": 1344}},
                       timeout=90)
        if resp.status_code == 200 and "image" in resp.headers.get("content-type", ""):
            with open(out_path, "wb") as f:
                f.write(resp.content)
            print(f"[MediaService] HF FLUX OK -> {out_path}")
            return True
    except Exception as e:
        print(f"[MediaService] HF FLUX note: {e}")
    return False


def _try_dalle3(prompt, out_path):
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return False
    try:
        import requests as rq
        resp = rq.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "dall-e-3", "prompt": prompt[:4000], "n": 1,
                  "size": "1024x1792", "quality": "hd", "response_format": "b64_json"},
            timeout=60
        )
        if resp.status_code == 200:
            with open(out_path, "wb") as f:
                f.write(base64.b64decode(resp.json()["data"][0]["b64_json"]))
            print(f"[MediaService] DALL-E 3 OK -> {out_path}")
            return True
    except Exception as e:
        print(f"[MediaService] DALL-E3 note: {e}")
    return False


def _upscale_portrait(image_path, w=1080, h=1920):
    try:
        from PIL import Image
        img = Image.open(image_path)
        ir = img.width / img.height
        tr = w / h
        if ir > tr:
            nw, nh = int(h * ir), h
        else:
            nw, nh = w, int(w / ir)
        img = img.resize((nw, nh), Image.LANCZOS)
        l, t = (nw - w) // 2, (nh - h) // 2
        img.crop((l, t, l + w, t + h)).save(image_path, "PNG")
        print(f"[MediaService] Upscaled -> {w}x{h}")
    except Exception as e:
        print(f"[MediaService] Upscale note: {e}")


def generate_4k_image(prompt, job_id, scene_index=0):
    fname = IMAGES_DIR / f"{job_id}_scene{scene_index:02d}.png"
    out_path = str(fname)
    for fn in [_try_gemini_imagen, _try_dalle3, _try_hf_flux,
               lambda p, o: _try_pollinations(p, o)]:
        try:
            if fn(prompt, out_path):
                _upscale_portrait(out_path)
                return out_path
        except Exception as e:
            print(f"[MediaService] Provider err: {e}")
        time.sleep(1)
    return None


def _get_bgm():
    if MUSIC_DIR.exists():
        import random
        tracks = list(MUSIC_DIR.glob("*.mp3"))
        if tracks:
            return str(random.choice(tracks))
    return None


def _gen_tts(script, out_path):
    try:
        import asyncio, edge_tts
        async def _speak():
            await edge_tts.Communicate(script, "en-IN-PrabhatNeural").save(out_path)
        asyncio.run(_speak())
        return os.path.exists(out_path) and os.path.getsize(out_path) > 1000
    except Exception as e:
        print(f"[MediaService] TTS note: {e}")
    return False


def assemble_shorts_video(image_paths, script, job_id, title="", dur_per_img=5.0):
    if not image_paths:
        return None
    out_path = str(SHORTS_DIR / f"{job_id}_shorts.mp4")
    tmpdir = Path(tempfile.mkdtemp(prefix="pf_shorts_"))
    try:
        tts_path = str(tmpdir / "narration.mp3")
        has_tts = _gen_tts(script, tts_path) if script else False
        n = len(image_paths)
        total = n * dur_per_img
        inputs, vfilters = [], []
        for i, img in enumerate(image_paths):
            inputs += ["-loop", "1", "-t", str(dur_per_img), "-i", img]
            d = int(dur_per_img * 25)
            dx = 1 if i % 2 == 0 else -1
            vfilters.append(
                f"[{i}:v]scale=1200:2133,"
                f"zoompan=z='min(zoom+0.0008,1.05)':x='iw/2-(iw/zoom/2)+{dx}*(iw/zoom/2-iw/2)*on/{d}':"
                f"y='ih/2-(ih/zoom/2)':d={d}:s=1080x1920:fps=25,setpts=PTS-STARTPTS[v{i}]"
            )
        concat = "".join(f"[v{i}]" for i in range(n))
        filtergraph = ";".join(vfilters) + f";{concat}concat=n={n}:v=1:a=0[vout]"
        aparts, amaps = [], []
        if has_tts:
            inputs += ["-i", tts_path]
            aparts.append(f"[{n}:a]volume=1.0[tts]"); amaps.append("[tts]")
        bgm = _get_bgm()
        if bgm:
            inputs += ["-stream_loop", "-1", "-i", bgm]
            bi = n + (1 if has_tts else 0)
            aparts.append(f"[{bi}:a]volume=0.15,atrim=0:{total}[bgm]"); amaps.append("[bgm]")
        cmd = ["ffmpeg", "-y"] + inputs
        if amaps:
            filtergraph += ";" + ";".join(aparts) + ";" + "".join(amaps) + f"amix=inputs={len(amaps)}:normalize=0[aout]"
            cmd += ["-filter_complex", filtergraph, "-map", "[vout]", "-map", "[aout]"]
        else:
            cmd += ["-filter_complex", filtergraph, "-map", "[vout]"]
        cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k", "-t", str(total),
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if res.returncode == 0 and os.path.exists(out_path):
            print(f"[MediaService] Shorts ready: {out_path} ({os.path.getsize(out_path)//1024//1024}MB)")
            return out_path
        print(f"[MediaService] FFmpeg err: {res.stderr[-400:]}")
    except Exception as e:
        print(f"[MediaService] Assembly err: {e}")
    finally:
        import shutil; shutil.rmtree(str(tmpdir), ignore_errors=True)
    return None


def _process_job(job):
    jid = job["id"]
    topic = job.get("topic", "")
    script = job.get("script", "")
    prompts = job.get("image_prompts") or [
        f"Cinematic 4K portrait: {topic}, dramatic lighting, bokeh background",
        f"Ultra-realistic close-up: {topic}, golden hour, shallow depth of field",
        f"Epic wide shot: {topic}, vibrant colors, professional photography vertical",
        f"Dramatic reveal: {topic}, neon glow, urban atmosphere, vertical composition",
        f"Emotional story: {topic}, warm tones, detailed textures, portrait mode",
    ]
    print(f"\n[MediaService] Starting job {jid}: '{topic}'")
    _update_job(jid, status="generating_images", progress=5)
    imgs = []
    for i, p in enumerate(prompts):
        _update_job(jid, progress=10 + int(50 * i / len(prompts)))
        img = generate_4k_image(p, jid, i)
        if img:
            imgs.append(img)
        time.sleep(2)
    if not imgs:
        _update_job(jid, status="failed", error="All image providers failed"); return
    _update_job(jid, status="assembling_video", progress=65)
    vid = assemble_shorts_video(imgs, script or topic, jid,
                                title=job.get("title", topic),
                                dur_per_img=job.get("dur_per_img", 5.0))
    if vid:
        _update_job(jid, status="completed", progress=100, output_video=vid,
                    completed_at=datetime.now(timezone.utc).isoformat())
        if job.get("auto_upload"):
            try:
                from src.backend.publish_schedule import schedule_upload
                schedule_upload(vid, job.get("title", topic), description=script or topic,
                                tags=job.get("tags", [topic, "shorts"]),
                                privacy=job.get("privacy", "private"),
                                user_id=job.get("user_id", 1))
            except Exception as e:
                print(f"[MediaService] Upload queue note: {e}")
    else:
        _update_job(jid, status="failed", error="Video assembly failed")


def _worker_loop():
    print("[MediaService] Worker started (zero-budget image+video pipeline)")
    while not _shutdown.is_set():
        try:
            with _queue_lock:
                items = _load_queue()
            for job in items:
                if job.get("status") == "pending":
                    _update_job(job["id"], status="running",
                                started_at=datetime.now(timezone.utc).isoformat())
                    _process_job(job)
                    break
        except Exception as e:
            print(f"[MediaService] Worker err: {e}")
        _shutdown.wait(timeout=10)
    print("[MediaService] Worker stopped.")


class MediaJobService:
    _thread = None

    @classmethod
    def start(cls):
        if cls._thread and cls._thread.is_alive():
            return
        _shutdown.clear()
        cls._thread = threading.Thread(target=_worker_loop, daemon=True, name="MediaWorker")
        cls._thread.start()
        print("[MediaService] Daemon started.")

    @classmethod
    def stop(cls):
        _shutdown.set()

    @classmethod
    def submit_job(cls, topic, script="", image_prompts=None, title="",
                   tags=None, dur_per_img=5.0, auto_upload=False,
                   privacy="private", user_id=1):
        job = {
            "id": uuid.uuid4().hex[:12], "topic": topic,
            "title": title or topic, "script": script,
            "image_prompts": image_prompts or [],
            "tags": tags or [topic, "shorts", "viral"],
            "dur_per_img": dur_per_img, "auto_upload": auto_upload,
            "privacy": privacy, "user_id": user_id,
            "status": "pending", "progress": 0,
            "output_video": None, "error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        with _queue_lock:
            items = _load_queue()
            items.append(job)
            _save_queue(items)
        print(f"[MediaService] Job queued: {job['id']} '{topic}'")
        return job

    @classmethod
    def get_job(cls, job_id):
        with _queue_lock:
            return next((j for j in _load_queue() if j.get("id") == job_id), None)

    @classmethod
    def list_jobs(cls, limit=20):
        with _queue_lock:
            items = _load_queue()
        return sorted(items, key=lambda j: j.get("created_at",""), reverse=True)[:limit]

    @classmethod
    def delete_job(cls, job_id):
        with _queue_lock:
            items = _load_queue()
            kept = [j for j in items if j.get("id") != job_id]
            changed = len(kept) < len(items)
            if changed:
                _save_queue(kept)
        return changed
"""

# The raw string can't hold a literal triple quote, so docstrings are escaped above.
code = code.replace('\\"\\"\\"', '"""')

with open("src/backend/background_media_service.py", "w", encoding="utf-8") as f:
    f.write(code.strip() + "\n")
print("Written:", os.path.getsize("src/backend/background_media_service.py"), "bytes")
