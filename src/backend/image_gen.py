"""
image_gen.py — PulseForge AI Image Generation Engine
====================================================
Features:
  - Dynamic Free AI Market integration (Pollinations Flux/Turbo, Hugging Face Serverless)
  - Creative AI Brain integration for dynamic camera angle enhancement
  - Strict image deduplication (SHA-256 tracking & distinct seeds per scene)
  - Support for Direct OpenAI (DALL-E 3) & Google Gemini (Imagen 3) when keys are supplied
  - Graceful fallback sequence with zero failure guarantee
"""

import os
import time
import struct
import zlib
import base64
import hashlib
import re
import json
import threading
import urllib.request
import urllib.parse
import requests

from .free_ai_market import get_free_ai_market
from .creative_learner import get_creative_brain

# Base project paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Session deduplication registry: maps image hash to file path.
# Enforced (not just recorded): generate_image() retries with a fresh seed
# when a provider returns a byte-identical image.
_used_image_hashes = set()
_hash_lock = threading.Lock()


def _get_image_hash(file_path: str) -> str:
    """Calculate SHA256 hash of an image file to guarantee visual uniqueness."""
    try:
        with open(file_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return ""


def _extract_topic_keywords(prompt: str) -> str:
    """Extracts high-relevance subject keywords from a visual prompt, filtering generic adjectives."""
    stop_words = {
        'cinematic', 'hyper-realistic', 'photorealistic', 'ultra-detailed', 'volumetric',
        'vertical', 'aspect', 'ratio', 'lighting', 'lens', 'photography', 'photo', 'shot',
        'scene', 'depicting', 'view', 'close-up', 'portrait', '9:16', '8k', '4k', 'raw',
        'dramatic', 'opening', 'looking', 'standing', 'high', 'quality', 'with', 'into',
        'across', 'from', 'over', 'under', 'about', 'behind', 'against', 'overlooking', 'this', 'that'
    }
    words = [w.strip(' ,.-:;!?') for w in prompt.lower().split()]
    filtered = [w for w in words if len(w) > 2 and w not in stop_words]
    return " ".join(filtered[:3]) if filtered else "superhero"


# Scenery words that must never be used ALONE as a stock query — they are
# what produced the infamous "Batman video with a sky photo" bug. They may
# only appear inside a multi-word subject query ("gotham sky" is fine).
_GENERIC_SCENERY = {
    'sky', 'grass', 'cloud', 'clouds', 'water', 'sunset', 'sunrise', 'background',
    'landscape', 'nature', 'field', 'fields', 'tree', 'trees', 'ocean', 'sea',
    'mountain', 'mountains', 'flower', 'flowers', 'road', 'street',
}

_STYLE_NOISE = {
    'cinematic', 'hyper-realistic', 'hyperrealistic', 'photorealistic', 'ultra-detailed',
    'ultradetailed', 'volumetric', 'dramatic', 'moody', 'epic', 'vertical', '8k', '4k',
    'raw', 'photo', 'photography', 'shot', 'film', 'still', 'frame', 'lighting', 'lens',
}


def _extract_subject_queries(prompt: str, topic: str = "") -> list:
    """Build ordered stock-search queries anchored on the SUBJECT, not scenery.

    Order: video topic -> quoted phrases -> Capitalized entities ->
    leading meaningful nouns. Single generic scenery words ('sky', 'grass')
    are never emitted alone.
    """
    queries = []
    seen = set()

    def add(q):
        q = re.sub(r"\s+", " ", (q or "").strip(" ,.-:;!?\"'"))
        if len(q) >= 3 and q.lower() not in seen:
            seen.add(q.lower())
            queries.append(q)

    # 1. The video topic itself is the strongest subject signal.
    if topic:
        add(topic)

    text = prompt or ""
    # 2. Quoted phrases ("Gotham City") are almost always the subject.
    for m in re.finditer(r'"([^"]{3,60})"', text):
        add(m.group(1))
    # 3. Capitalized entity runs (Batman, Gotham City, Eiffel Tower).
    for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b", text):
        ent = m.group(1)
        if ent.lower() not in _STYLE_NOISE:
            add(ent)
    # 4. Leading meaningful nouns from the cleaned prompt.
    words = [w.strip(' ,.-:;!?\"\'') for w in text.lower().split()]
    _weak_lone = {'standing', 'sitting', 'looking', 'shown', 'showcasing',
                  'featuring', 'with', 'and', 'the', 'for', 'from'}
    meaningful = [w for w in words
                  if len(w) > 2 and w not in _STYLE_NOISE and w not in {
                      'with', 'into', 'across', 'from', 'over', 'under', 'about',
                      'behind', 'against', 'this', 'that', 'and', 'the', 'for'}]
    if meaningful:
        add(" ".join(meaningful[:3]))
        for w in meaningful[:4]:
            if w not in _GENERIC_SCENERY and w not in _weak_lone:
                add(w)
    return queries


def _title_vocab(title: str) -> set:
    """Tokenize a file title into whole lowercase words for matching."""
    return set(re.findall(r"[a-z0-9]+", (title or "").lower()))


def _fetch_topic_stock_image(prompt: str, width: int, height: int, output_path: str,
                             topic: str = "") -> bool:
    """
    Searches for high-resolution free stock images matching the SUBJECT.
    Every candidate result is validated: the file title must contain at least
    one subject token as a WHOLE WORD, otherwise it is rejected (no more sky
    photos for a Batman video). Returns False instead of a wrong image.
    """
    queries = _extract_subject_queries(prompt, topic)
    headers = {'User-Agent': 'PulseForge/2.0 (MediaBot; admin@pulseforge.local)'}

    best = None  # (score, title, url) — highest whole-word token overlap wins
    for query in queries:
        qwords = re.findall(r"[a-z0-9]+", query.lower())
        # A lone short token ("now", "ice", "bat") matches inside unrelated
        # words ("NOW ON", "meeting", "combat") — never search one alone.
        if len(qwords) == 1 and len(qwords[0]) < 4:
            continue
        matchable = {t for t in qwords if len(t) >= 4}
        if not matchable:
            continue
        # Never search a lone scenery word ("sky") — it can only return junk.
        if len(matchable) == 1 and next(iter(matchable)) in _GENERIC_SCENERY:
            continue
        try:
            api_url = ("https://commons.wikimedia.org/w/api.php?action=query"
                       f"&generator=search&gsrsearch={urllib.parse.quote(query)}"
                       "&gsrnamespace=6&gsrlimit=6&prop=imageinfo&iiprop=url|mime&format=json")
            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8'))

            pages = data.get("query", {}).get("pages", {})
            for page_id, page_data in pages.items():
                title = page_data.get("title") or ""
                # Validate on WHOLE WORDS: substring matching let "now" match
                # "NOW ON" and "ice" match "meeting"/"police".
                hits = matchable & _title_vocab(title)
                if not hits:
                    continue
                img_info = page_data.get("imageinfo", [{}])[0]
                url = img_info.get("url")
                if url:
                    clean_url = url.split("?")[0].lower()
                    if any(clean_url.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                        score = len(hits)
                        if best is None or score > best[0]:
                            best = (score, title, url)
        except Exception as e:
            print(f"[image_gen] Topic stock search for '{query}' note: {e}")

    if best:
        _score, title, url = best
        try:
            dl_req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(dl_req, timeout=15) as dl_resp:
                content = dl_resp.read()
                if len(content) > 10000:
                    with open(output_path, "wb") as f:
                        f.write(content)
                    print(f"[image_gen] [Stock Match] '{title[:60]}' ({len(content)//1024} KB)")
                    return True
        except Exception as e:
            print(f"[image_gen] Stock download note: {e}")

    return False


def _upscale_to_target(image_path: str, width: int, height: int) -> None:
    """High-quality upscale of a downloaded image to the target resolution.

    Free image APIs (Pollinations) return ~580x1015 regardless of the requested
    size. A LANCZOS upscale + mild sharpen here gives every downstream stage
    (motion engine, assembler) a clean 1080x1920 source instead of letting
    moviepy's default resizer smear a small image (2026-09-27 loop-test).
    Only upscales — never downscales an already-large image.
    """
    try:
        from PIL import Image, ImageFilter
        img = Image.open(image_path).convert("RGB")
        if img.width >= width and img.height >= height:
            return
        # Preserve aspect: fit inside target, then center-crop to exact size.
        scale = max(width / img.width, height / img.height)
        nw, nh = int(img.width * scale + 0.5), int(img.height * scale + 0.5)
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        left = (nw - width) // 2
        top = (nh - height) // 2
        img = img.crop((left, top, left + width, top + height))
        img = img.filter(ImageFilter.UnsharpMask(radius=2.0, percent=60, threshold=2))
        img.save(image_path, "JPEG", quality=93)
        print(f"[image_gen] Upscaled to {width}x{height} (LANCZOS+sharpen): "
              f"{os.path.basename(image_path)}")
    except Exception as e:
        print(f"[image_gen] Upscale note: {e}")


def _create_placeholder_image(output_path: str, prompt: str, width: int, height: int, seed_val: int = 0):
    """Create a high-contrast dark cinematic title card with topic typography and glowing border."""
    from PIL import Image, ImageDraw, ImageFont
    
    keywords = _extract_topic_keywords(prompt).upper()
    img = Image.new("RGB", (width, height), color=(10, 14, 26))
    draw = ImageDraw.Draw(img)
    
    # Draw dark moody background with subtle radial gradient effect
    for y in range(height):
        ratio = y / height
        r = int(10 + 15 * ratio)
        g = int(14 + 20 * (1 - ratio))
        b = int(26 + 35 * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    
    # Draw neon cyan/amber accent framing lines
    border_color = (0, 255, 170) if seed_val % 2 == 0 else (56, 189, 248)
    draw.rectangle([40, 60, width - 40, height - 60], outline=border_color, width=3)
    draw.rectangle([50, 70, width - 50, height - 70], outline=(255, 255, 255, 40), width=1)
    
    # Add topic text in center
    display_title = keywords[:36] if keywords else "CINEMATIC SCENE"
    draw.text((width // 2, height // 2 - 40), display_title, fill=(241, 245, 249), anchor="mm")
    draw.text((width // 2, height // 2 + 20), f"SCENE {seed_val} · AGAM AI", fill=border_color, anchor="mm")
    
    img.save(output_path, "JPEG", quality=92)
    print(f"[image_gen] OK: Cinematic contextual artwork generated for '{display_title}' at {output_path}")


# ── Anti-slop image stack (2026-09-28 research: "no-AI-slop Shorts") ────
# The glossy plastic AI look has known causes with known fixes. They live
# here, in one central place, so every image the pipeline makes gets them.

# Style anchor appended to EVERY prompt: names a real medium, a real film
# stock and real imperfections. "beautiful / studio quality / 8k" style
# fluff is what produces the waxy render sheen.
STYLE_ANCHOR = ("shot on 35mm film, Kodak Portra 400, soft warm color grade, "
                "subtle film grain, natural skin texture with visible pores, "
                "candid, imperfect, photojournalistic")

# One idea per image, subject gets headroom (captions live in the
# lower third), and NEVER any baked-in text — captions are burned in the
# edit, never generated into the frame.
COMPOSITION_RULES = ("vertical 9:16 composition, subject with headroom above, "
                     "lower third left clear for captions, one clear subject, "
                     "no text, no letters, no watermark, no logo")

# Negatives that kill the slop tells on NON-distilled checkpoints. Distilled
# checkpoints (Lightning/Turbo, CFG=1) ignore negatives — they are inert
# there but harmless to send.
ANTI_SLOP_NEGATIVE = ("plastic skin, glossy, cgi, 3d render, cartoon, neon, "
                      "gradient background, text, letters, watermark, logo, "
                      "bad hands, deformed, blurry, low quality")

_VIDEO_MODEL_MARKERS = ("svd", "wan", "ltx", "video")


def build_image_prompt(raw_prompt: str) -> str:
    """Apply the anti-slop template to a raw scene prompt (idempotent).

    Returns: raw prompt + composition rules + style anchor. Never bakes
    text into the image; the film-stock anchor kills the plastic render
    sheen; the composition rules keep captions readable.
    """
    base = (raw_prompt or "").strip().rstrip(".,;:")
    if not base:
        base = "cinematic vertical scene"
    if "Kodak Portra" in base:  # already templated — don't double-append
        return base
    return f"{base}, {COMPOSITION_RULES}, {STYLE_ANCHOR}"


def _is_distilled_checkpoint(ckpt_name: str) -> bool:
    """True for few-step distilled checkpoints (Lightning/Turbo/Hyper).

    These run CFG=1 with ~8 steps; negative prompts are inert on them.
    """
    cl = (ckpt_name or "").lower()
    return any(m in cl for m in ("lightning", "turbo", "hyper", "dmd2", "lcm"))


def _pick_image_checkpoint(checkpoints: list) -> tuple[str | None, bool]:
    """Pick the best txt2img checkpoint: SDXL-Lightning first, then SDXL.

    Returns (ckpt_name, is_distilled). Dedicated video checkpoints (SVD /
    Wan / LTX) are excluded — they are for image-to-VIDEO, not txt2img.
    """
    cands = [c for c in (checkpoints or [])
             if c and not any(v in c.lower() for v in _VIDEO_MODEL_MARKERS)]
    if not cands:
        return None, False

    def _rank(c):
        cl = c.lower()
        return (
            0 if "lightning" in cl else 1,   # SDXL-Lightning 8-step first
            0 if "xl" in cl else 1,          # then any SDXL-class
            0 if "realistic" in cl or "photo" in cl else 1,  # photoreal bases
            c,
        )
    best = sorted(cands, key=_rank)[0]
    return best, _is_distilled_checkpoint(best)


def _generate_comfyui_image(prompt: str, output_path: str, width: int = 512, height: int = 768, base_url: str = "http://127.0.0.1:8188") -> str:
    """Generates an AI image locally using ComfyUI txt2img workflow (100% free, offline, GPU-accelerated)."""
    try:
        req = requests.get(f"{base_url}/system_stats", timeout=2)
        if req.status_code != 200:
            return None

        models_resp = requests.get(f"{base_url}/models/checkpoints", timeout=3)
        checkpoints = models_resp.json() if models_resp.status_code == 200 else []
        if not checkpoints:
            return None

        # Prefer SDXL-Lightning (8-step, CFG=1) — the 6GB anti-slop sweet
        # spot — over whatever checkpoint happens to be first in the list.
        img_model, distilled = _pick_image_checkpoint(checkpoints)
        if not img_model:
            return None

        # Distilled checkpoints want few steps + CFG=1 (+ sgm_uniform
        # scheduler); full checkpoints get the classic 20-step / CFG 7.
        steps, cfg, scheduler = (8, 1.0, "sgm_uniform") if distilled else (20, 7.0, "normal")
        # Native vertical bucket for Shorts; 832×1216 is SDXL-comfortable.
        lat_w, lat_h = min(width, 832), min(height, 1216)
        prompt = build_image_prompt(prompt)

        print(f"[image_gen] [100% Free Local ComfyUI] Synthesizing image with checkpoint '{img_model}' "
              f"({'distilled' if distilled else 'full'}, {steps} steps, CFG {cfg})...")
        prompt_workflow = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": img_model}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt[:600], "clip": ["1", 1]}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": ANTI_SLOP_NEGATIVE, "clip": ["1", 1]}},
            "4": {"class_type": "EmptyLatentImage", "inputs": {"width": lat_w, "height": lat_h, "batch_size": 1}},
            "5": {"class_type": "KSampler", "inputs": {
                "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0],
                "seed": int(time.time()*1000) % 2147483647, "steps": steps, "cfg": cfg, "sampler_name": "euler", "scheduler": scheduler, "denoise": 1.0
            }},
            "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
            "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "pulseforge_img"}}
        }
        
        q_resp = requests.post(f"{base_url}/prompt", json={"prompt": prompt_workflow}, timeout=10)
        if q_resp.status_code != 200:
            return None
        prompt_id = q_resp.json().get("prompt_id")
        if not prompt_id:
            return None
            
        for _ in range(45):
            time.sleep(2)
            h_resp = requests.get(f"{base_url}/history/{prompt_id}", timeout=5)
            if h_resp.status_code == 200:
                h_data = h_resp.json().get(prompt_id, {})
                outputs = h_data.get("outputs", {})
                if "7" in outputs and outputs["7"].get("images"):
                    img_info = outputs["7"]["images"][0]
                    fname = img_info.get("filename")
                    subfolder = img_info.get("subfolder", "")
                    view_url = f"{base_url}/view?filename={fname}&subfolder={subfolder}&type=output"
                    v_resp = requests.get(view_url, timeout=15)
                    if v_resp.status_code == 200 and len(v_resp.content) > 1000:
                        with open(output_path, "wb") as f:
                            f.write(v_resp.content)
                        print(f"[image_gen] [SUCCESS] ComfyUI local image saved to {output_path}")
                        # Optional FaceDetailer pass (AGAM_FACEDETAIL=1) —
                        # fixes waxy/plastic faces; skipped by default.
                        _facedetail_pass(base_url, output_path, img_model, distilled)
                        return output_path
        return None
    except Exception as e:
        print(f"[image_gen] ComfyUI local image note: {e}")
        return None


def _facedetail_pass(base_url: str, image_path: str, img_model: str,
                   distilled: bool) -> str | None:
    """Optional ComfyUI-Impact-Pack FaceDetailer pass (uncanny-face killer).

    Runs ONLY when AGAM_FACEDETAIL=1 and ComfyUI has the Impact Pack —
    default renders are untouched. Re-imports the generated image, runs
    FaceDetailer at low denoise (0.20–0.26) to fix waxy/plastic faces, and
    overwrites image_path with the detailed result. Returns image_path on
    success, None when skipped or failed.
    """
    if os.environ.get("AGAM_FACEDETAIL", "0") != "1":
        return None
    try:
        info = requests.get(f"{base_url}/object_info/FaceDetailer", timeout=5)
        if info.status_code != 200:
            print("[image_gen] FaceDetailer not found in ComfyUI "
                  "(install ComfyUI-Impact-Pack) — skipping detail pass.")
            return None
        with open(image_path, "rb") as fh:
            up = requests.post(
                f"{base_url}/upload/image",
                files={"image": (os.path.basename(image_path), fh,
                                 "image/png")},
                data={"overwrite": "true"}, timeout=60)
        if up.status_code != 200:
            print(f"[image_gen] FaceDetailer upload failed ({up.status_code}).")
            return None
        up_name = up.json().get("name") or os.path.basename(image_path)

        steps = 8 if distilled else 20
        wf = {
            "10": {"class_type": "LoadImage",
                   "inputs": {"image": up_name}},
            "11": {"class_type": "CheckpointLoaderSimple",
                   "inputs": {"ckpt_name": img_model}},
            "12": {"class_type": "FaceDetailer", "inputs": {
                "image": ["10", 0],
                "model": ["11", 0], "clip": ["11", 1], "vae": ["11", 2],
                "guide_size": 512, "guide_size_for": True, "max_size": 768,
                "seed": int(time.time() * 1000) % 2147483647,
                "steps": steps, "cfg": 1.0 if distilled else 7.0,
                "sampler_name": "euler",
                "scheduler": "sgm_uniform" if distilled else "normal",
                "denoise": 0.24, "feather": 5,
                "noise_mask": True, "force_inpaint": True,
                "bbox_threshold": 0.5, "bbox_dilation": 10,
                "bbox_crop_factor": 3.0,
                "sam_detection_hint": "center-1", "sam_dilation": 0,
                "sam_threshold": 0.93, "sam_bbox_expansion": 0,
                "sam_mask_hint_threshold": 0.7,
                "sam_mask_hint_use_negative": "False",
                "drop_size": 10, "cycle": 1}},
            "13": {"class_type": "SaveImage",
                   "inputs": {"images": ["12", 0],
                              "filename_prefix": "pulseforge_detail"}},
        }
        q = requests.post(f"{base_url}/prompt", json={"prompt": wf}, timeout=10)
        if q.status_code != 200:
            return None
        prompt_id = q.json().get("prompt_id")
        if not prompt_id:
            return None
        for _ in range(30):
            time.sleep(3)
            h = requests.get(f"{base_url}/history/{prompt_id}", timeout=5)
            if h.status_code == 200:
                outputs = h.json().get(prompt_id, {}).get("outputs", {})
                if "13" in outputs and outputs["13"].get("images"):
                    info_img = outputs["13"]["images"][0]
                    v = requests.get(
                        f"{base_url}/view?filename={info_img.get('filename')}"
                        f"&subfolder={info_img.get('subfolder', '')}&type=output",
                        timeout=15)
                    if v.status_code == 200 and len(v.content) > 1000:
                        with open(image_path, "wb") as f:
                            f.write(v.content)
                        print("[image_gen] FaceDetailer pass applied "
                              f"-> {os.path.basename(image_path)}")
                        return image_path
        print("[image_gen] FaceDetailer pass timed out — keeping base image.")
        return None
    except Exception as e:
        print(f"[image_gen] FaceDetailer pass note: {e}")
        return None


def _generate_image_once(
    prompt: str,
    output_path: str,
    width: int = 1080,
    height: int = 1920,
    model_name: str = "DALL-E 3",
    custom_api_key: str = "",
    scene_index: int = 0,
    total_scenes: int = 1,
    seed: int | None = None,
    topic: str = "",
) -> str | None:
    """
    Single attempt at generating a unique image (no dedup retry here —
    use generate_image() which enforces it).
    Returns the output path, or None when every provider failed.
    """
    output_dir = os.path.dirname(os.path.abspath(output_path))
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # Enhance prompt with Creative AI Learner for unique camera angles & style consistency
    brain = get_creative_brain()
    enhanced_prompt = brain.enhance_scene_prompt(prompt, scene_index, total_scenes, visual_style="Cinematic")
    
    # Generate unique seed per scene (overridable for dedup retries)
    unique_seed = seed if seed is not None else (int(time.time() * 1000) + scene_index * 1337 + hash(prompt)) % 1000000

    # ── Attempt 1: 100% Free Local ComfyUI GPU Generation ────────────────────────
    try:
        comfy_img = _generate_comfyui_image(enhanced_prompt, output_path, width=min(width, 768), height=min(height, 1024))
        if comfy_img and os.path.exists(comfy_img) and os.path.getsize(comfy_img) > 1000:
            return comfy_img
    except Exception as comfy_err:
        print(f"[image_gen] Local ComfyUI check note: {comfy_err}")

    # ── Attempt 2: Direct OpenAI or Gemini API if custom API key provided ──────
    if custom_api_key:
        is_openai_model = model_name == "DALL-E 3"
        is_gemini_model = "Gemini" in model_name or "Imagen" in model_name

        if is_openai_model:
            print(f"[image_gen] Using Direct OpenAI DALL-E 3 API (Scene {scene_index+1})...")
            try:
                headers = {
                    "Authorization": f"Bearer {custom_api_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": "dall-e-3",
                    "prompt": enhanced_prompt[:950],
                    "n": 1,
                    "size": "1024x1792",
                    "quality": "standard"
                }
                resp = requests.post("https://api.openai.com/v1/images/generations", headers=headers, json=payload, timeout=60)
                resp.raise_for_status()
                img_url = resp.json()["data"][0]["url"]
                
                req = urllib.request.Request(img_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=30) as response:
                    content = response.read()
                    with open(output_path, 'wb') as f:
                        f.write(content)
                print(f"[image_gen] OK: Direct DALL-E 3 image saved to {output_path}")
                return output_path
            except Exception as e:
                print(f"[image_gen] Direct DALL-E 3 failed: {e}. Falling back to Free AI Market...")

        elif is_gemini_model:
            print(f"[image_gen] Using Direct Google Gemini Imagen 3 API (Scene {scene_index+1})...")
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:generateImages?key={custom_api_key}"
                headers = {"Content-Type": "application/json"}
                payload = {
                    "numberOfImages": 1,
                    "prompt": enhanced_prompt[:950],
                    "aspectRatio": "9:16",
                    "outputMimeType": "image/jpeg"
                }
                resp = requests.post(url, headers=headers, json=payload, timeout=60)
                resp.raise_for_status()
                img_b64 = resp.json()["generatedImages"][0]["image"]["imageBytes"]
                img_bytes = base64.b64decode(img_b64)
                
                with open(output_path, "wb") as f:
                    f.write(img_bytes)
                print(f"[image_gen] OK: Direct Gemini Imagen 3 image saved to {output_path}")
                return output_path
            except Exception as e:
                print(f"[image_gen] Direct Gemini Imagen 3 failed: {e}. Falling back to next...")

    # ── Attempt 3: HuggingFace Cloud Spaces (FLUX.1-schnell & SD 3.5 Turbo) ──────
    from src.backend.connection_tests import clean_token as _clean_token
    hf_token = _clean_token(os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN"))
    if hf_token or model_name in ["FLUX.1", "HuggingFace", "SD 3.5"]:
        try:
            from gradio_client import Client
            import shutil
            print(f"[image_gen] [HuggingFace Space] Generating scene via black-forest-labs/FLUX.1-schnell...")
            hf_client = Client("black-forest-labs/FLUX.1-schnell", token=hf_token)
            hf_res = hf_client.predict(
                prompt=enhanced_prompt[:400],
                seed=unique_seed % 2147483647,
                randomize_seed=True,
                width=min(width, 1024),
                height=min(height, 1024),
                num_inference_steps=4,
                api_name="/infer"
            )
            if hf_res and isinstance(hf_res, (tuple, list)) and len(hf_res) > 0:
                img_val = hf_res[0]
                img_path = img_val.get("path") if isinstance(img_val, dict) else img_val
                if img_path and os.path.exists(img_path) and os.path.getsize(img_path) > 1000:
                    shutil.copyfile(img_path, output_path)
                    print(f"[image_gen] OK: HuggingFace FLUX.1 image saved to {output_path}")
                    return output_path
        except Exception as hf_err:
            print(f"[image_gen] HuggingFace Space image note: {hf_err}. Continuing to Pollinations...")

    # ── Attempt 4: Free AI Market Router (Pollinations Turbo & Flux-Realism) ─────
    clean_prompt = re.sub(r'[\r\n\t]+', ' ', enhanced_prompt).strip()
    if len(clean_prompt) > 400:
        clean_prompt = clean_prompt[:400]
    encoded_prompt = urllib.parse.quote(clean_prompt)
    
    poll_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    }

    # Free models on Pollinations that do not require paid balance/pollen
    # NOTE (2026-09-27 loop-test): the free tier caps output at ~576x1024 and
    # preserves the REQUESTED aspect ratio — so request true 9:16 (the old
    # 768x1024 request returned 3:4 images that lost content to center-crop).
    # _upscale_to_target() then upscales cleanly to 1080x1920.
    req_w, req_h = 576, 1024
    if width and height:
        req_h = 1024
        req_w = max(320, int(req_h * width / height))
    for model_choice in ["turbo", "flux-realism", "flux-anime"]:
        pollinations_url = (
            f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            f"?model={model_choice}&width={req_w}&height={req_h}&nologo=true&seed={unique_seed}"
        )
        try:
            r = requests.get(pollinations_url, headers=poll_headers, timeout=40)
            if r.status_code == 200 and len(r.content) > 3000:
                with open(output_path, 'wb') as f:
                    f.write(r.content)
                _upscale_to_target(output_path, width, height)
                print(f"[image_gen] OK: AI Image synthesized via free model '{model_choice}' saved to {output_path}")
                return output_path
        except Exception as e:
            print(f"[image_gen] Pollinations {model_choice} attempt note: {e}")

    # ── Attempt 5: Subject-Anchored Stock Search ──
    # Only accepts results whose title matches the subject; returns False
    # (→ topic-titled placeholder) instead of an irrelevant photo.
    _subj = _extract_subject_queries(prompt, topic)
    print(f"[image_gen] Searching subject-anchored stock assets: '{(_subj[0] if _subj else topic)}'...")
    if _fetch_topic_stock_image(prompt, width, height, output_path, topic=topic):
        return output_path

    # ── Attempt 6: Dynamic Local Cinematic Poster Artwork (100% Offline & Topic-Aligned) ──
    print(f"[image_gen] Rendering contextual cinematic artwork for Scene {scene_index+1}...")
    _create_placeholder_image(output_path, prompt, width, height, seed_val=scene_index + 1)
    return output_path


# ── Visual Art Style Matrix Presets ──────────────────────────────────────────
STYLE_PRESETS = {
    "cinema_8k": "Hyper-realistic 8k raw cinematic photography, ARRI Alexa LF, 35mm master prime lens, dramatic volumetric lighting, photorealistic textures, vertical 9:16",
    "cyberpunk": "Futuristic neon-drenched cyberpunk aesthetic, glowing cyan and magenta holographic lighting, dark rainy cityscape, ultra-detailed 8k, vertical 9:16",
    "anime_ghibli": "Studio Ghibli aesthetic, Makoto Shinkai inspired anime illustration, vibrant lush colors, hand-drawn anime background, ethereal sunlight, vertical 9:16",
    "vintage_doc": "Gritty historical documentary archive photo, Kodak Portra 400 film grain, authentic 35mm texture, dramatic chiaroscuro shadows, vertical 9:16",
    "unreal_3d": "Unreal Engine 5 isometric 3D render, octane render lighting, raytraced glass and metallic reflections, clean minimalist 3D, vertical 9:16"
}


def generate_images_for_scenes(
    scenes: list,
    output_dir: str,
    width: int = 1080,
    height: int = 1920,
    model_name: str = "DALL-E 3",
    custom_api_key: str = "",
    visual_style: str = "cinema_8k",
    topic_title: str = "",
) -> list:
    """
    Generates distinct, non-duplicate images for every scene concurrently in parallel using ThreadPoolExecutor.
    """
    import concurrent.futures

    total_scenes = len(scenes)
    style_suffix = STYLE_PRESETS.get(visual_style.lower(), STYLE_PRESETS["cinema_8k"])
    print(f"[image_gen] [Parallel Engine] Launching concurrent asset generation for {total_scenes} scenes (Style: '{visual_style}')...")

    def process_scene(idx_scene_tuple):
        i, scene = idx_scene_tuple
        prompts = []
        if scene.get('image_prompt'):
            prompts = [scene['image_prompt']]
        elif scene.get('image_prompts'):
            prompts = scene['image_prompts'] if isinstance(scene['image_prompts'], list) else [scene['image_prompts']]

        if not prompts:
            # Last-resort: build a topic-specific prompt from the narration so the
            # scene is never silently skipped for lack of a prompt.
            narr = scene.get('narration') or f"Scene {i + 1}"
            prompts = [f"Cinematic photorealistic 8k vertical shot of: {narr}. Dramatic volumetric lighting, 9:16"]
            print(f"[image_gen] Scene {i + 1}: no image_prompt supplied — built one from narration.")

        scene['image_paths'] = []
        for j, base_prompt in enumerate(prompts):
            filename = f"scene_{i+1}_shot_{j+1}_{int(time.time()*1000)%1000000}_{i}.jpg"
            out_path = os.path.join(output_dir, filename)

            # Apply Style Matrix preset to prompt
            full_prompt = f"{base_prompt}, {style_suffix}" if style_suffix not in base_prompt else base_prompt
            # Relevance guard: providers love rendering gibberish text/logos —
            # ban them in every prompt so the image stays on-topic.
            _no_text = "no text, no words, no letters, no captions, no logos, no watermarks"
            if "no text" not in full_prompt.lower():
                full_prompt = f"{full_prompt}, {_no_text}"

            path = generate_image(
                prompt=full_prompt,
                output_path=out_path,
                width=width,
                height=height,
                model_name=model_name,
                custom_api_key=custom_api_key,
                scene_index=i,
                total_scenes=total_scenes,
                topic=topic_title or scene.get("topic_title") or "",
            )
            if path and os.path.exists(path):
                scene['image_paths'].append(path)

        if not scene['image_paths']:
            # Fail LOUDLY — a scene with no image must halt the pipeline via the
            # orchestrator's CRITICAL HALT, never silently vanish from the video.
            raise RuntimeError(
                f"Scene {i + 1}: every image provider failed (see logs above). "
                f"Check the image node connection and retry."
            )
        print(f"[image_gen] Scene {i + 1}/{total_scenes}: {len(scene['image_paths'])} image(s) ready.")

        return i, scene

    # Execute all scenes simultaneously in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, max(1, total_scenes))) as executor:
        futures = [executor.submit(process_scene, (i, sc)) for i, sc in enumerate(scenes)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    # Preserve chronological scene order
    results.sort(key=lambda x: x[0])
    ordered_scenes = [r[1] for r in results]
    print(f"[image_gen] [Parallel Engine] [OK] All {len(ordered_scenes)} scene images generated concurrently in parallel.")
    return ordered_scenes


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2:
        generate_image(sys.argv[1], sys.argv[2])
    else:
        print("Usage: python image_gen.py <prompt> <output_path>")


# ── Public entry point: enforced visual uniqueness ──────────────────────────

def generate_image(
    prompt: str,
    output_path: str,
    width: int = 1080,
    height: int = 1920,
    model_name: str = "DALL-E 3",
    custom_api_key: str = "",
    scene_index: int = 0,
    total_scenes: int = 1,
    max_attempts: int = 3,
    topic: str = "",
) -> str | None:
    """
    Generates a unique image for a scene.

    Enforces the session dedup registry: if a provider returns a byte-identical
    image to one already used this session, the attempt is discarded and retried
    with a fresh seed (up to max_attempts). Returns the output path, or None
    when every provider failed.
    """
    base_seed = (int(time.time() * 1000) + scene_index * 1337 + hash(prompt)) % 1000000
    # Relevance guard (same as batch path): ban rendered text/logos.
    _no_text = "no text, no words, no letters, no captions, no logos, no watermarks"
    if "no text" not in prompt.lower():
        prompt = f"{prompt}, {_no_text}"
    for attempt in range(max_attempts):
        seed = (base_seed + attempt * 7919) % 1000000
        try:
            path = _generate_image_once(
                prompt, output_path, width=width, height=height,
                model_name=model_name, custom_api_key=custom_api_key,
                scene_index=scene_index, total_scenes=total_scenes, seed=seed,
                topic=topic,
            )
        except Exception as e:
            print(f"[image_gen] Attempt {attempt + 1}/{max_attempts} crashed: {e}")
            path = None
        if not path or not os.path.exists(path) or os.path.getsize(path) <= 1000:
            print(f"[image_gen] Attempt {attempt + 1}/{max_attempts}: no image produced; retrying...")
            continue
        img_hash = _get_image_hash(path)
        with _hash_lock:
            if img_hash and img_hash in _used_image_hashes:
                print(f"[image_gen] Attempt {attempt + 1}/{max_attempts}: duplicate image detected "
                      f"(hash seen before) — regenerating with a fresh seed.")
                continue
            if img_hash:
                _used_image_hashes.add(img_hash)
        return path
    print(f"[image_gen] FAILED: all {max_attempts} attempts produced duplicates or nothing for scene {scene_index + 1}.")
    return None
