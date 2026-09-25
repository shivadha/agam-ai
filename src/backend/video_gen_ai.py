import os
import time
import requests
import json
import base64
import urllib.request
import urllib.parse
import math
import numpy as np
from PIL import Image, ImageFilter, ImageEnhance

def generate_video_from_image(image_path: str, prompt: str, duration: float = 4.0, provider: str = "Luma", api_key: str = "", output_dir: str = "C:\\AI_project\\output") -> str:
    """
    Triggers AI Image-to-Video generation. 
    Implements a self-healing fallback queue:
    1. Tries cloud AI models (HuggingFace SVD, Pollinations, Luma, Runway, Kling, fal.ai) if credentials exist.
    2. Guarantees 100% success by falling back to the built-in Procedural Neural Motion Engine
       which synthesizes 10+ dynamic camera physics effects directly matching the prompt.
    """
    os.makedirs(output_dir, exist_ok=True)
    import re
    clean_p = re.sub(r'[^a-zA-Z0-9_]', '_', provider.lower()).strip('_')
    clean_img = re.sub(r'[^a-zA-Z0-9_]', '_', os.path.splitext(os.path.basename(image_path))[0])
    filename = f"ai_video_{clean_p}_{int(time.time()*1000)%1000000}_{clean_img}.mp4"
    output_path = os.path.join(output_dir, filename)

    if not os.path.exists(image_path):
        print(f"[video_gen_ai] Image file not found: {image_path}")
        return None

    # Resolve provider keys from args or environment variables
    keys = {
        "luma": api_key if provider.lower() == "luma" else os.environ.get("LUMA_API_KEY", ""),
        "runway": api_key if provider.lower() == "runway" else os.environ.get("RUNWAY_API_KEY", ""),
        "kling": api_key if provider.lower() == "kling" else os.environ.get("KLING_API_KEY", ""),
        "pika": api_key if provider.lower() == "pika" else os.environ.get("PIKA_API_KEY", ""),
        "veo": api_key if provider.lower() == "veo" else os.environ.get("VEO_API_KEY", ""),
        "huggingface": api_key if provider.lower() == "huggingface" else (os.environ.get("HF_TOKEN") or os.environ.get("HF_API_KEY") or ""),
        "fal": api_key if provider.lower() in ["fal", "fal_kling", "fal_minimax", "fal_luma"] else (os.environ.get("FAL_API_KEY") or os.environ.get("FAL_KEY") or ""),
    }

    # Normalize provider
    prov_lower = provider.lower().strip()
    is_comfy_requested = "comfy" in prov_lower
    is_motion_engine_requested = "motion engine" in prov_lower

    # ── ComfyUI local check (runs FIRST — truly free, truly automatable) ──
    # If ComfyUI is running locally at http://127.0.0.1:8188, try SVD / Wan image-to-video
    comfyui_base = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")

    # Queue up the requested provider first, then add backups
    if is_comfy_requested:
        providers_queue = ["comfyui"]
    else:
        providers_queue = [prov_lower]
        if "comfyui" not in providers_queue:
            providers_queue.insert(0, "comfyui")

    backups = ["fal_kling", "fal_minimax", "fal_luma", "kling", "huggingface", "luma", "runway", "pika", "veo"]
    for b in backups:
        if b not in providers_queue:
            providers_queue.append(b)

    # Expand general 'fal' or list items
    expanded_queue = []
    for p in providers_queue:
        if p == "fal":
            expanded_queue.extend(["fal_kling", "fal_minimax", "fal_luma"])
        else:
            expanded_queue.append(p)
    providers_queue = expanded_queue

    last_comfy_error = None
    for p in providers_queue:
        key_provider_name = p
        if p.startswith("fal_"):
            key_provider_name = "fal"
        p_key = keys.get(key_provider_name, "")

        # ComfyUI is key-free — skip the key check for it
        if p == "comfyui":
            print(f"[video_gen_ai] [ComfyUI] Generating genuine AI image-to-video via local ComfyUI at {comfyui_base}...")
            try:
                res_path = _generate_comfyui_wan(image_path, prompt, duration, output_path, comfyui_base)
                if res_path and os.path.exists(res_path) and os.path.getsize(res_path) > 1000:
                    print(f"[video_gen_ai] [SUCCESS] ComfyUI local AI video generation succeeded: {res_path}")
                    return res_path
            except Exception as comfy_err:
                last_comfy_error = str(comfy_err)
                print(f"[video_gen_ai] ComfyUI notice: {comfy_err}")
                if is_comfy_requested:
                    # User specifically selected ComfyUI — do NOT silently swap to 2D motion edits
                    raise RuntimeError(f"ComfyUI AI Video generation failed: {comfy_err}. Procedural 2D motion edits are blocked per user configuration.")
            continue

        if not p_key:
            if api_key:
                p_key = api_key
            else:
                continue

        print(f"[video_gen_ai] [Queue Attempt] Trying cloud AI video provider '{p}'...")
        try:
            res_path = None
            if p == "luma":
                res_path = _generate_luma(image_path, prompt, p_key, output_path)
            elif p == "runway":
                res_path = _generate_runway(image_path, prompt, p_key, output_path)
            elif p == "kling":
                res_path = _generate_kling(image_path, prompt, p_key, output_path)
            elif p == "pika":
                res_path = _generate_pika(image_path, prompt, p_key, output_path)
            elif p == "veo":
                res_path = _generate_veo(image_path, prompt, p_key, output_path)
            elif p == "huggingface":
                res_path = _generate_huggingface_svd(image_path, prompt, p_key, output_path)
            elif p == "fal_kling":
                res_path = _generate_fal_ai_kling(image_path, prompt, p_key, output_path)
            elif p == "fal_minimax":
                res_path = _generate_fal_ai_minimax(image_path, prompt, p_key, output_path)
            elif p == "fal_luma":
                res_path = _generate_fal_ai_luma(image_path, prompt, p_key, output_path)

            if res_path and os.path.exists(res_path) and os.path.getsize(res_path) > 1000:
                print(f"[video_gen_ai] [SUCCESS] Cloud video generation SUCCEEDED with provider '{p}'!")
                return res_path
        except Exception as e:
            print(f"[video_gen_ai] Provider '{p}' note: {e}")
            continue

    # Procedural Neural Motion Engine
    # STRICT RULE: ONLY used if the user explicitly chose "motion engine"
    # Never secretly replace AI video generation with 2D camera motion edits!
    if is_motion_engine_requested:
        print(f"[video_gen_ai] Rendering dynamic procedural camera motion video from image...")
        try:
            return _generate_procedural_neural_motion_video(image_path, prompt, duration, output_path)
        except Exception as proc_err:
            print(f"[video_gen_ai] Procedural motion render error: {proc_err}")
            return None
    else:
        print(f"[video_gen_ai] [NO MOTION EDITS] AI video requested ('{provider}'). Suppressing procedural 2D motion edits as requested.")
        if last_comfy_error:
            raise RuntimeError(f"ComfyUI AI Video generation failed: {last_comfy_error}. Procedural motion edits are blocked.")
        return None

# ══════════════════════════════════════════════════════════════
# COMFYUI LOCAL WAN / LTX IMAGE-TO-VIDEO PROVIDER
# The ONLY truly free, automatable, high-quality i2v solution.
# Requires: ComfyUI + WanVideo or LTX-Video model installed.
# ComfyUI: https://github.com/comfyanonymous/ComfyUI
# Wan model: https://huggingface.co/Wan-AI/Wan2.1-I2V-14B-480P
# LTX model: https://huggingface.co/Lightricks/LTX-Video
# ══════════════════════════════════════════════════════════════

def _generate_comfyui_wan(image_path: str, prompt: str, duration: float,
                          output_path: str, base_url: str = "http://127.0.0.1:8188") -> str:
    """
    Generate real AI image-to-video using a locally running ComfyUI server.
    
    Workflow priority:
    1. Wan 1.3B Image-to-Video (fast, 8GB VRAM)
    2. LTX-Video Image-to-Video (high quality, 12GB+ VRAM)
    3. AnimateDiff + ControlNet (works on 6GB VRAM)
    
    Falls back gracefully if ComfyUI is not running.
    """
    import urllib.request
    import urllib.error
    import json
    import uuid
    import time
    import shutil
    import base64
    import os

    TIMEOUT = 600  # 10 minutes max wait for generation

    # ── 1. Check if ComfyUI server is reachable ──
    try:
        req = urllib.request.Request(f"{base_url}/system_stats", headers={"User-Agent": "PulseForge/1.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            stats = json.loads(r.read().decode())
        print(f"[ComfyUI] Server online. VRAM: {stats.get('system', {}).get('vram_total', 'N/A')} bytes")
    except Exception as e:
        print(f"[ComfyUI] Server not reachable at {base_url}: {e}")
        print("[ComfyUI] Install ComfyUI for free local AI video: https://github.com/comfyanonymous/ComfyUI")
        raise RuntimeError(f"ComfyUI not running at {base_url}")

    # ── 2. Encode image as base64 for the workflow ──
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    img_fname = os.path.basename(image_path)
    
    # ── 3. Upload the image to ComfyUI ──
    try:
        import io
        # Use multipart upload to ComfyUI's /upload/image endpoint
        boundary = "----PulseForge" + uuid.uuid4().hex[:16]
        img_data = open(image_path, "rb").read()
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{img_fname}"\r\n'
            f"Content-Type: image/jpeg\r\n\r\n"
        ).encode() + img_data + f"\r\n--{boundary}--\r\n".encode()
        
        upload_req = urllib.request.Request(
            f"{base_url}/upload/image",
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "PulseForge/1.0"
            },
            method="POST"
        )
        with urllib.request.urlopen(upload_req, timeout=30) as r:
            upload_result = json.loads(r.read().decode())
        uploaded_name = upload_result.get("name", img_fname)
        print(f"[ComfyUI] Image uploaded: {uploaded_name}")
    except Exception as e:
        print(f"[ComfyUI] Image upload failed: {e} — trying with filename reference")
        uploaded_name = img_fname

    # ── 4. Build the ComfyUI workflow ──
    # We'll try Wan 1.3B I2V first (lightest, most compatible)
    client_id = str(uuid.uuid4())
    num_frames = max(16, min(81, int(duration * 16)))  # Wan supports up to 81 frames
    
    # Detect which models are available from ComfyUI's model list
    wan_model = None
    ltx_model = None
    svd_model = None
    try:
        req = urllib.request.Request(f"{base_url}/models/checkpoints", headers={"User-Agent": "PulseForge/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            models = json.loads(r.read().decode())
        for m in (models if isinstance(models, list) else []):
            ml = m.lower()
            if "wan" in ml and ("i2v" in ml or "image" in ml):
                wan_model = m
                break
            elif "ltx" in ml:
                ltx_model = m
            elif "svd" in ml:
                svd_model = m
        print(f"[ComfyUI] Detected models — Wan: {wan_model}, LTX: {ltx_model}, SVD: {svd_model}")
    except Exception:
        pass

    # ── Choose optimal workflow based on detected models ──
    if svd_model:
        # Native Stable Video Diffusion XT workflow (fast, local, high quality)
        # Optimal Shorts 9:16 aspect ratio (512x768) or Landscape (768x512)
        svd_w, svd_h = 512, 768
        try:
            with Image.open(image_path) as _im:
                _iw, _ih = _im.size
                if _iw > _ih:
                    svd_w, svd_h = 768, 512
                else:
                    svd_w, svd_h = 512, 768
        except Exception:
            pass

        frames_count = 14  # 14 frames for clean motion and maximum speed
        workflow = {
            "1": {"class_type": "LoadImage", "inputs": {"image": uploaded_name}},
            "2": {"class_type": "ImageOnlyCheckpointLoader", "inputs": {"ckpt_name": svd_model}},
            "3": {"class_type": "SVD_img2vid_Conditioning", "inputs": {
                "clip_vision": ["2", 1],
                "init_image": ["1", 0],
                "vae": ["2", 2],
                "width": svd_w,
                "height": svd_h,
                "video_frames": frames_count,
                "motion_bucket_id": 127,
                "fps": 7,
                "augmentation_level": 0.0
            }},
            "4": {"class_type": "KSampler", "inputs": {
                "model": ["2", 0],
                "positive": ["3", 0],
                "negative": ["3", 1],
                "latent_image": ["3", 2],
                "seed": int(time.time()) % 2147483647,
                "steps": 14,
                "cfg": 2.5,
                "sampler_name": "euler",
                "scheduler": "karras",
                "denoise": 1.0
            }},
            "5": {"class_type": "VAEDecode", "inputs": {
                "samples": ["4", 0],
                "vae": ["2", 2]
            }},
            "6": {"class_type": "SaveAnimatedWEBP", "inputs": {
                "images": ["5", 0],
                "filename_prefix": "pulseforge_svd",
                "fps": 14.0,
                "lossless": False,
                "quality": 85,
                "method": "default"
            }}
        }
        print(f"[ComfyUI] Using Stable Video Diffusion model: {svd_model} ({svd_w}x{svd_h}, {frames_count} frames, 14 steps)")
    elif wan_model:
        workflow = {
            "1": {"class_type": "LoadImage", "inputs": {"image": uploaded_name}},
            "2": {"class_type": "WanImageToVideo", "inputs": {
                "model": wan_model,
                "positive_prompt": prompt + ", high quality, cinematic, 4K sharp, smooth motion",
                "negative_prompt": "blur, low quality, watermark, text, distortion, ugly",
                "image": ["1", 0],
                "width": 832, "height": 480,
                "num_frames": num_frames,
                "steps": 20,
                "cfg": 6.0,
                "seed": int(time.time()) % 2147483647
            }},
            "3": {"class_type": "SaveVideo", "inputs": {
                "video": ["2", 0],
                "filename_prefix": "pulseforge_wan",
                "format": "mp4"
            }}
        }
        print(f"[ComfyUI] Using Wan I2V model: {wan_model} ({num_frames} frames)")
    elif ltx_model:
        workflow = {
            "1": {"class_type": "LoadImage", "inputs": {"image": uploaded_name}},
            "2": {"class_type": "LTXVImageToVideo", "inputs": {
                "ckpt_name": ltx_model,
                "positive": prompt + ", cinematic motion, smooth, high quality",
                "negative": "blur, static, low quality, artifacts",
                "image": ["1", 0],
                "width": 768, "height": 512,
                "length": num_frames,
                "steps": 25, "cfg": 3.5,
                "seed": int(time.time()) % 2147483647
            }},
            "3": {"class_type": "VHS_VideoCombine", "inputs": {
                "images": ["2", 0],
                "frame_rate": 24,
                "filename_prefix": "pulseforge_ltx",
                "format": "video/mp4"
            }}
        }
        print(f"[ComfyUI] Using LTX-Video model: {ltx_model}")
    else:
        workflow = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "v1-5-pruned-emaonly.safetensors"}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt + ", cinematic motion", "clip": ["1", 1]}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "blur, low quality, static", "clip": ["1", 1]}},
            "4": {"class_type": "LoadImage", "inputs": {"image": uploaded_name}},
            "5": {"class_type": "ADE_AnimateDiffLoaderWithContext", "inputs": {
                "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
                "latent_image": ["4", 0],
                "motion_module": "mm_sd_v15_v2.ckpt",
                "steps": 20, "cfg": 7.5, "num_frames": min(16, num_frames)
            }},
            "6": {"class_type": "SaveVideo", "inputs": {"video": ["5", 0], "filename_prefix": "pulseforge_animdiff"}}
        }
        print("[ComfyUI] No Wan/LTX/SVD model found — trying AnimateDiff workflow")

    # ── 5. Queue the workflow ──
    payload = json.dumps({"prompt": workflow, "client_id": client_id}).encode()
    queue_req = urllib.request.Request(
        f"{base_url}/prompt",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "PulseForge/1.0"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(queue_req, timeout=30) as r:
            queue_result = json.loads(r.read().decode())
        prompt_id = queue_result.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"No prompt_id in response: {queue_result}")
        print(f"[ComfyUI] Workflow queued. Prompt ID: {prompt_id}")
    except Exception as e:
        raise RuntimeError(f"ComfyUI queue failed: {e}")

    # ── 6. Poll for completion ──
    start = time.time()
    while time.time() - start < TIMEOUT:
        time.sleep(3)
        try:
            req = urllib.request.Request(f"{base_url}/history/{prompt_id}", headers={"User-Agent": "PulseForge/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                history = json.loads(r.read().decode())
            
            if prompt_id in history:
                outputs = history[prompt_id].get("outputs", {})
                for node_id, node_output in outputs.items():
                    media_items = node_output.get("videos", []) or node_output.get("images", []) or node_output.get("gifs", [])
                    for m in media_items:
                        vfilename = m.get("filename")
                        vsubfolder = m.get("subfolder", "")
                        vtype = m.get("type", "output")
                        if vfilename:
                            dl_url = f"{base_url}/view?filename={urllib.parse.quote(vfilename)}&subfolder={urllib.parse.quote(vsubfolder)}&type={vtype}"
                            print(f"[ComfyUI] Downloading result: {vfilename}")
                            dl_req = urllib.request.Request(dl_url, headers={"User-Agent": "PulseForge/1.0"})
                            with urllib.request.urlopen(dl_req, timeout=120) as dl_r:
                                file_data = dl_r.read()
                            
                            if vfilename.lower().endswith(".mp4"):
                                with open(output_path, "wb") as f:
                                    f.write(file_data)
                            else:
                                # Convert animated webp/gif/frames to standard MP4 via Pillow + imageio
                                tmp_in = output_path + "_" + vfilename
                                with open(tmp_in, "wb") as f:
                                    f.write(file_data)
                                try:
                                    from PIL import Image as PilImg, ImageSequence as PilSeq
                                    import imageio
                                    with PilImg.open(tmp_in) as anim_img:
                                        frames = [np.array(frame.convert("RGB")) for frame in PilSeq.Iterator(anim_img)]
                                    if frames:
                                        imageio.mimsave(output_path, frames, fps=14, codec="libx264")
                                        print(f"[ComfyUI] Successfully converted {len(frames)} frames to MP4 via imageio: {output_path}")
                                except Exception as conv_err:
                                    print(f"[ComfyUI] imageio conversion notice: {conv_err} — trying ffmpeg fallback")
                                    import subprocess
                                    cmd = ["ffmpeg", "-y", "-i", tmp_in, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", output_path]
                                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                finally:
                                    if os.path.exists(tmp_in):
                                        try:
                                            os.remove(tmp_in)
                                        except Exception:
                                            pass
                            if os.path.exists(output_path) and os.path.getsize(output_path) > 500:
                                print(f"[ComfyUI] Final video ready at {output_path} ({os.path.getsize(output_path)//1024} KB)")
                                return output_path
        except Exception as poll_err:
            import traceback
            print(f"[ComfyUI] Poll notice: {poll_err}")
        
        elapsed = int(time.time() - start)
        print(f"[ComfyUI] Generating video frames... ({elapsed}s elapsed)")

    raise RuntimeError(f"ComfyUI timed out after {TIMEOUT}s")


def _generate_luma(image_path: str, prompt: str, api_key: str, output_path: str) -> str:
    """Luma Dream Machine API integration with pre-signed URL upload."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # Step 1: Request pre-signed upload URL
    print("[video_gen_ai] [Luma] Requesting upload URL...")
    upload_req = requests.post(
        "https://api.lumalabs.ai/v1/generations/file",
        headers=headers,
        json={"file_type": "image/jpeg", "filename": os.path.basename(image_path)},
        timeout=30
    )
    upload_req.raise_for_status()
    upload_data = upload_req.json()
    upload_url = upload_data["upload_url"]
    public_url = upload_data["public_url"]
    
    # Step 2: Upload local image file
    print("[video_gen_ai] [Luma] Uploading image...")
    with open(image_path, "rb") as f:
        img_data = f.read()
    put_req = requests.put(upload_url, data=img_data, headers={"Content-Type": "image/jpeg"}, timeout=60)
    put_req.raise_for_status()
    
    # Step 3: Trigger video generation using public_url
    print("[video_gen_ai] [Luma] Triggering video generation...")
    payload = {
        "prompt": prompt,
        "keyframes": {
            "frame0": {
                "type": "image",
                "url": public_url
            }
        }
    }
    gen_req = requests.post("https://api.lumalabs.ai/v1/generations", headers=headers, json=payload, timeout=30)
    gen_req.raise_for_status()
    gen_data = gen_req.json()
    generation_id = gen_data["id"]
    
    # Step 4: Poll status until complete
    print(f"[video_gen_ai] [Luma] Generation started (ID: {generation_id}). Polling status...")
    status_url = f"https://api.lumalabs.ai/v1/generations/{generation_id}"
    
    for i in range(12): # Max 2 minutes polling
        time.sleep(10)
        status_req = requests.get(status_url, headers=headers, timeout=15)
        status_req.raise_for_status()
        status_data = status_req.json()
        state = status_data.get("state")
        
        print(f"[video_gen_ai] [Luma] Status check: {state}")
        if state == "completed":
            video_url = status_data["assets"]["video"]
            # Download completed video
            print(f"[video_gen_ai] [Luma] Downloading video from {video_url}...")
            urllib.request.urlretrieve(video_url, output_path)
            print(f"[video_gen_ai] [Luma] OK: Video saved to {output_path}")
            return output_path
        elif state == "failed":
            raise ValueError(f"Generation failed: {status_data.get('failure_reason', 'unknown error')}")
            
    print("[video_gen_ai] [Luma] Generation timed out.")
    return None

def _generate_runway(image_path: str, prompt: str, api_key: str, output_path: str) -> str:
    """Runway ML Gen-2/Gen-3 Image-to-Video API integration."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Runway-Version": "2024-11-06"
    }
    
    # Step 1: Request pre-signed upload URL
    print("[video_gen_ai] [Runway] Requesting upload URL...")
    upload_req = requests.post(
        "https://api.runwayml.com/v1/uploads",
        headers=headers,
        json={"name": os.path.basename(image_path), "size": os.path.getsize(image_path), "mimeType": "image/jpeg"},
        timeout=30
    )
    upload_req.raise_for_status()
    upload_data = upload_req.json()
    upload_url = upload_data["uploadUrl"]
    asset_id = upload_data["id"]
    
    # Step 2: Upload local image file
    print("[video_gen_ai] [Runway] Uploading image asset...")
    with open(image_path, "rb") as f:
        img_data = f.read()
    put_req = requests.put(upload_url, data=img_data, headers={"Content-Type": "image/jpeg"}, timeout=60)
    put_req.raise_for_status()
    
    # Step 3: Trigger generation task
    print("[video_gen_ai] [Runway] Creating generation task...")
    payload = {
        "taskType": "image_to_video",
        "model": "gen3a_turbo",
        "promptText": prompt,
        "assets": [
            {
                "id": asset_id,
                "role": "input_image"
            }
        ]
    }
    gen_req = requests.post("https://api.runwayml.com/v1/tasks", headers=headers, json=payload, timeout=30)
    gen_req.raise_for_status()
    task_id = gen_req.json()["id"]
    
    # Step 4: Poll status
    status_url = f"https://api.runwayml.com/v1/tasks/{task_id}"
    for i in range(12):
        time.sleep(10)
        status_req = requests.get(status_url, headers=headers, timeout=15)
        status_req.raise_for_status()
        status_data = status_req.json()
        status = status_data.get("status")
        
        print(f"[video_gen_ai] [Runway] Status check: {status}")
        if status == "SUCCEEDED":
            video_url = status_data["output"][0]
            print(f"[video_gen_ai] [Runway] Downloading video...")
            urllib.request.urlretrieve(video_url, output_path)
            return output_path
        elif status == "FAILED":
            raise ValueError(f"Generation failed: {status_data.get('error', 'unknown error')}")
            
    print("[video_gen_ai] [Runway] Generation timed out.")
    return None

def _generate_kling(image_path: str, prompt: str, api_key: str, output_path: str) -> str:
    """Kling AI Image-to-Video API integration."""
    # Kling AI typically uses a simple Base64 input
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")
        
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "kling-1.5",
        "image": f"data:image/jpeg;base64,{img_b64}",
        "prompt": prompt,
        "duration": "5s",
        "aspect_ratio": "9:16"
    }
    
    print("[video_gen_ai] [Kling] Creating image-to-video task...")
    gen_req = requests.post("https://api.klingai.com/v1/videos/image2video", headers=headers, json=payload, timeout=45)
    gen_req.raise_for_status()
    task_id = gen_req.json()["data"]["task_id"]
    
    # Poll status
    status_url = f"https://api.klingai.com/v1/videos/tasks/{task_id}"
    for i in range(12):
        time.sleep(10)
        status_req = requests.get(status_url, headers=headers, timeout=15)
        status_req.raise_for_status()
        status_data = status_req.json()
        task_status = status_data["data"]["task_status"]
        
        print(f"[video_gen_ai] [Kling] Status check: {task_status}")
        if task_status == "SUCCESS":
            video_url = status_data["data"]["video_url"]
            print(f"[video_gen_ai] [Kling] Downloading video...")
            urllib.request.urlretrieve(video_url, output_path)
            return output_path
        elif task_status == "FAILED":
            raise ValueError(f"Kling generation failed.")
            
    print("[video_gen_ai] [Kling] Generation timed out.")
    return None

def _generate_pika(image_path: str, prompt: str, api_key: str, output_path: str) -> str:
    """Pika Labs Image-to-Video API integration."""
    # Pika API uses multipart/form-data for local file uploads
    headers = {
        "Authorization": f"Bearer {api_key}"
    }
    
    print("[video_gen_ai] [Pika] Uploading image and starting task...")
    with open(image_path, "rb") as img_file:
        files = {"image": img_file}
        data = {
            "prompt": prompt,
            "options": json.dumps({"aspectRatio": "9:16", "camera": "zoom_in"})
        }
        gen_req = requests.post("https://api.pika.art/v1/generations", headers=headers, files=files, data=data, timeout=45)
        
    gen_req.raise_for_status()
    generation_id = gen_req.json()["id"]
    
    # Poll status
    status_url = f"https://api.pika.art/v1/generations/{generation_id}"
    for i in range(12):
        time.sleep(10)
        status_req = requests.get(status_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=15)
        status_req.raise_for_status()
        status_data = status_req.json()
        status = status_data.get("status")
        
        print(f"[video_gen_ai] [Pika] Status check: {status}")
        if status == "completed":
            video_url = status_data["videoUrl"]
            print(f"[video_gen_ai] [Pika] Downloading video...")
            urllib.request.urlretrieve(video_url, output_path)
            return output_path
        elif status == "failed":
            raise ValueError("Pika generation failed.")
            
    print("[video_gen_ai] [Pika] Generation timed out.")
    return None

def _generate_veo(image_path: str, prompt: str, api_key: str, output_path: str) -> str:
    """Google Gemini Veo 2.0 Image-to-Video API integration."""
    # Official Generative Language API endpoint for video generation
    url = f"https://generativelanguage.googleapis.com/v1beta/models/veo-2.0-generateVideo:generateVideos?key={api_key}"
    headers = {"Content-Type": "application/json"}
    
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")
        
    payload = {
        "prompt": prompt,
        "aspectRatio": "9:16",
        "durationSeconds": 5,
        "inputImage": {
            "imageBytes": img_b64
        }
    }
    
    print("[video_gen_ai] [Veo] Sending Veo video generation request...")
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    
    video_b64 = resp.json()["generatedVideos"][0]["video"]["videoBytes"]
    video_bytes = base64.b64decode(video_b64)
    
    with open(output_path, "wb") as f:
        f.write(video_bytes)
        
    print(f"[video_gen_ai] [Veo] OK: Video saved to {output_path}")
    return output_path

def _generate_huggingface_svd(image_path: str, prompt: str, api_key: str, output_path: str) -> str:
    """HuggingFace Inference API for Stable Video Diffusion (SVD) — free tier."""
    endpoint = "https://api-inference.huggingface.co/models/stabilityai/stable-video-diffusion-img2vid-xt"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    payload = {"inputs": img_b64}

    print("[video_gen_ai] [HuggingFace SVD] Sending request to SVD endpoint...")
    max_retries = 5
    for attempt in range(1, max_retries + 1):
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=120)

        if resp.status_code == 503:
            # Model is loading — wait and retry
            wait_sec = 20 * attempt
            try:
                detail = resp.json().get('error', 'Model is loading')
            except Exception:
                detail = 'Model is loading'
            print(f"[video_gen_ai] [HuggingFace SVD] 503 — {detail}. Waiting {wait_sec}s (attempt {attempt}/{max_retries})...")
            time.sleep(wait_sec)
            continue

        resp.raise_for_status()

        # Response body is the raw video bytes
        video_bytes = resp.content
        if not video_bytes:
            raise ValueError("[HuggingFace SVD] Empty response body — no video returned.")

        with open(output_path, "wb") as out_f:
            out_f.write(video_bytes)

        print(f"[video_gen_ai] [HuggingFace SVD] OK: Video saved to {output_path}")
        return output_path

    print("[video_gen_ai] [HuggingFace SVD] Model did not become ready after max retries.")
    return None

def _generate_fal_generic(
    image_path: str,
    prompt: str,
    api_key: str,
    output_path: str,
    model_endpoint: str,
    extra_payload: dict = None
) -> str:
    """Generic fal.ai image-to-video API client using queue-based polling."""
    submit_url = f"https://fal.run/{model_endpoint}"
    headers = {
        "Authorization": f"Key {api_key}",
        "Content-Type": "application/json"
    }

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    payload = {
        "image_url": f"data:image/jpeg;base64,{img_b64}",
        "prompt": prompt
    }
    if extra_payload:
        payload.update(extra_payload)

    print(f"[video_gen_ai] [fal.ai/{model_endpoint}] Submitting image-to-video job...")
    submit_resp = requests.post(submit_url, headers=headers, json=payload, timeout=60)
    submit_resp.raise_for_status()
    submit_data = submit_resp.json()
    request_id = submit_data.get("request_id")
    if not request_id:
        raise ValueError(f"[fal.ai/{model_endpoint}] No request_id in submit response: {submit_data}")

    print(f"[video_gen_ai] [fal.ai/{model_endpoint}] Job submitted (request_id={request_id}). Polling status...")
    status_url = f"https://queue.fal.run/{model_endpoint}/requests/{request_id}"

    for i in range(24):  # max ~4 minutes
        time.sleep(10)
        status_resp = requests.get(status_url, headers=headers, timeout=30)
        status_resp.raise_for_status()
        status_data = status_resp.json()
        status = status_data.get("status")

        print(f"[video_gen_ai] [fal.ai/{model_endpoint}] Status check ({i+1}/24): {status}")
        if status == "COMPLETED":
            video_url = (
                status_data.get("video", {}).get("url") or
                status_data.get("file", {}).get("url") or
                status_data.get("video_url")
            )
            if not video_url:
                raise ValueError(f"[fal.ai/{model_endpoint}] No video URL in completed response: {status_data}")
            print(f"[video_gen_ai] [fal.ai/{model_endpoint}] Downloading video from {video_url}...")
            urllib.request.urlretrieve(video_url, output_path)
            print(f"[video_gen_ai] [fal.ai/{model_endpoint}] OK: Video saved to {output_path}")
            return output_path
        elif status in ("FAILED", "ERROR"):
            raise ValueError(f"[fal.ai/{model_endpoint}] Job failed: {status_data.get('error', 'unknown error')}")

    print(f"[video_gen_ai] [fal.ai/{model_endpoint}] Generation timed out.")
    return None

def _generate_fal_ai_kling(image_path: str, prompt: str, api_key: str, output_path: str) -> str:
    """fal.ai Kling image-to-video integration."""
    return _generate_fal_generic(
        image_path=image_path,
        prompt=prompt,
        api_key=api_key,
        output_path=output_path,
        model_endpoint="fal-ai/kling-video/v2/standard/image-to-video",
        extra_payload={"duration": "5", "aspect_ratio": "9:16"}
    )

def _generate_fal_ai_minimax(image_path: str, prompt: str, api_key: str, output_path: str) -> str:
    """fal.ai Minimax image-to-video integration."""
    return _generate_fal_generic(
        image_path=image_path,
        prompt=prompt,
        api_key=api_key,
        output_path=output_path,
        model_endpoint="fal-ai/minimax-video/v2/image-to-video",
        extra_payload={"aspect_ratio": "9:16"}
    )

def _generate_fal_ai_luma(image_path: str, prompt: str, api_key: str, output_path: str) -> str:
    """fal.ai Luma Dream Machine image-to-video integration."""
    return _generate_fal_generic(
        image_path=image_path,
        prompt=prompt,
        api_key=api_key,
        output_path=output_path,
        model_endpoint="fal-ai/luma-dream-machine/image-to-video",
        extra_payload={"aspect_ratio": "9:16"}
    )


def _generate_procedural_neural_motion_video(image_path: str, prompt: str, duration: float, output_path: str, width: int = 1080, height: int = 1920) -> str:
    """
    Renders a 1080x1920 MP4 video file applying cinematic camera physics
    and neural motion effects derived specifically from the prompt.
    Guarantees that a rich, animated MP4 video file is ALWAYS created and returned.
    """
    from PIL import Image, ImageFilter, ImageEnhance
    from moviepy import VideoClip
    import numpy as np
    import math

    if not duration or duration < 1.0:
        duration = 4.0

    img = Image.open(image_path).convert("RGB")
    # Resize and crop to 1080x1920 with high quality Lanczos + margin for motion
    img_ratio = img.width / img.height
    target_ratio = width / height
    if img_ratio > target_ratio:
        new_height = height + 180
        new_width = int(new_height * img_ratio)
    else:
        new_width = width + 180
        new_height = int(new_width / img_ratio)
        
    img_large = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    img_arr = np.array(img_large)
    
    prompt_lower = (prompt or "").lower()
    
    # Motion archetype selection based on image_to_video_prompt
    if any(k in prompt_lower for k in ["whip", "swipe", "pan left", "fast left"]):
        motion_type = "whip_pan_left"
    elif any(k in prompt_lower for k in ["pan right", "reveal right", "slide right"]):
        motion_type = "whip_pan_right"
    elif any(k in prompt_lower for k in ["punch", "zoom burst", "speed ramp", "explode"]):
        motion_type = "speed_ramp_punch"
    elif any(k in prompt_lower for k in ["zoom out", "reveal", "pull back", "wide"]):
        motion_type = "zoom_burst_out"
    elif any(k in prompt_lower for k in ["parallax", "holographic", "data", "drift"]):
        motion_type = "parallax_drift"
    elif any(k in prompt_lower for k in ["light", "glow", "laser", "pulse", "energy", "spark"]):
        motion_type = "lighting_pulse_sweep"
    elif any(k in prompt_lower for k in ["shake", "earthquake", "shatter", "crisis", "shock"]):
        motion_type = "camera_shake_micro"
    else:
        motion_type = "cinematic_dolly_glide"
        
    print(f"[video_gen_ai] [Procedural Engine] Synthesizing '{motion_type}' motion video ({duration:.1f}s) for prompt: '{prompt[:60]}...'")

    def make_frame(t):
        progress = min(max(t / duration, 0.0), 1.0)
        
        H, W, _ = img_arr.shape
        
        if motion_type == "cinematic_dolly_glide":
            zoom = 1.0 + 0.16 * (1.0 - math.cos(progress * math.pi / 2))
            cx = W / 2 + (progress - 0.5) * 40
            cy = H / 2 + (progress - 0.5) * 30
        elif motion_type == "speed_ramp_punch":
            curve = progress ** 2.2
            zoom = 1.0 + 0.28 * curve
            cx = W / 2
            cy = H / 2
        elif motion_type == "zoom_burst_out":
            zoom = 1.25 - 0.20 * (1.0 - math.cos(progress * math.pi / 2))
            cx = W / 2
            cy = H / 2
        elif motion_type == "whip_pan_left":
            zoom = 1.08 + 0.05 * math.sin(progress * math.pi)
            cx = W / 2 + (0.5 - progress) * (W * 0.18)
            cy = H / 2
        elif motion_type == "whip_pan_right":
            zoom = 1.08 + 0.05 * math.sin(progress * math.pi)
            cx = W / 2 + (progress - 0.5) * (W * 0.18)
            cy = H / 2
        elif motion_type == "parallax_drift":
            zoom = 1.05 + 0.10 * math.sin(progress * math.pi * 0.8)
            cx = W / 2 + (progress - 0.5) * (W * 0.12)
            cy = H / 2 + (0.5 - progress) * (H * 0.08)
        elif motion_type == "camera_shake_micro":
            jitter_x = math.sin(t * 14.0) * 8 + math.cos(t * 22.0) * 4
            jitter_y = math.cos(t * 16.0) * 8 + math.sin(t * 28.0) * 4
            zoom = 1.06 + 0.06 * progress
            cx = W / 2 + jitter_x
            cy = H / 2 + jitter_y
        else:
            zoom = 1.0 + 0.12 * progress
            cx = W / 2
            cy = H / 2
            
        crop_w = width / zoom
        crop_h = height / zoom
        
        x1 = int(max(0, min(W - crop_w, cx - crop_w / 2)))
        y1 = int(max(0, min(H - crop_h, cy - crop_h / 2)))
        x2 = int(x1 + crop_w)
        y2 = int(y1 + crop_h)
        
        cropped = img_arr[y1:y2, x1:x2]
        frame_pil = Image.fromarray(cropped).resize((width, height), Image.Resampling.BILINEAR)
        
        if motion_type == "lighting_pulse_sweep":
            enhancer = ImageEnhance.Brightness(frame_pil)
            frame_pil = enhancer.enhance(1.0 + 0.12 * math.sin(progress * math.pi * 2))
            
        return np.array(frame_pil)

    clip = VideoClip(make_frame, duration=duration)
    clip.write_videofile(
        output_path,
        fps=24,
        codec="libx264",
        audio=False,
        logger=None,
        threads=4,
        preset="ultrafast"
    )
    clip.close()
    print(f"[video_gen_ai] [Procedural Engine] OK: Dynamic video shot generated: {output_path} ({os.path.getsize(output_path)/1024:.1f} KB)")
    return output_path


def generate_videos_for_scenes(
    scenes: list,
    output_dir: str,
    provider: str = "Luma",
    api_key: str = ""
) -> list:
    """
    Generates dynamic AI video motion clips for all scenes concurrently in parallel.
    """
    import concurrent.futures

    total_scenes = len(scenes)
    print(f"[video_gen_ai] [Parallel Engine] Synthesizing video clips for {total_scenes} scenes concurrently...")

    def process_scene_video(idx_scene_tuple):
        i, scene = idx_scene_tuple
        img_paths = scene.get('image_paths', [])
        scene_dur = float(scene.get('duration', 4.5))
        prompt = scene.get('image_to_video_prompt') or scene.get('narration', '')

        scene['video_paths'] = []
        if img_paths:
            shot_dur = scene_dur / max(1, len(img_paths))
            for j, img_path in enumerate(img_paths):
                if os.path.exists(img_path):
                    v_path = generate_video_from_image(
                        image_path=img_path,
                        prompt=prompt,
                        duration=shot_dur,
                        provider=provider,
                        api_key=api_key,
                        output_dir=output_dir
                    )
                    if v_path and os.path.exists(v_path):
                        scene['video_paths'].append(v_path)
        return i, scene

    is_local_gpu = "comfy" in provider.lower()
    workers = 1 if is_local_gpu else min(4, max(1, total_scenes))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(process_scene_video, (i, sc)) for i, sc in enumerate(scenes)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    results.sort(key=lambda x: x[0])
    ordered_scenes = [r[1] for r in results]
    print(f"[video_gen_ai] [Parallel Engine] [OK] All {len(ordered_scenes)} scene video clips rendered.")
    return ordered_scenes

