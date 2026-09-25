import os
import json
import re
import requests
from dotenv import load_dotenv
load_dotenv()

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "YOUR_OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

def _generate_ollama(model_name: str, system_prompt: str, user_prompt: str) -> str:
    """Sends a local chat request to Ollama and processes the response."""
    ollama_model = "qwen2.5-coder:7b"
    if "shivam-pro" in model_name.lower():
        ollama_model = "shivam-pro" if ":" in model_name else "shivam-pro:latest"
    elif "deepseek-r1" in model_name.lower():
        ollama_model = "deepseek-r1" if ":" in model_name else "deepseek-r1:latest"
    elif "qwen3" in model_name.lower():
        ollama_model = "qwen3:8b" if "8b" not in model_name else model_name.lower()
    elif "qwen2.5-coder" in model_name.lower() or "qwen" in model_name.lower():
        ollama_model = "qwen2.5-coder:7b"
    elif "deepseek" in model_name.lower():
        ollama_model = "deepseek-r1:latest"
        
    print(f"[script_gen] [Ollama] Routing to local model: {ollama_model}")
    try:
        url = "http://localhost:11434/api/chat"
        payload = {
            "model": ollama_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "options": {
                "temperature": 0.75
            },
            "stream": True
        }
        resp = requests.post(url, json=payload, timeout=120.0, stream=True)
        resp.raise_for_status()
        
        chunks = []
        for line in resp.iter_lines():
            if line:
                try:
                    data = json.loads(line)
                    chunk = data.get("message", {}).get("content", "")
                    if chunk:
                        chunks.append(chunk)
                    if data.get("done"):
                        break
                except Exception:
                    continue
        content = "".join(chunks).strip()
        
        # Strip DeepSeek R1 reasoning think blocks
        if "<think>" in content:
            print("[script_gen] [Ollama] Stripping <think> reasoning blocks...")
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
            if "<think>" in content:
                content = content.split("<think>")[0]
            content = content.strip()
            
        return content if content else None
    except Exception as e:
        print(f"[script_gen] [Ollama] Request failed for model {ollama_model}: {e}")
        return None


def generate_video_content(topic_title, custom_prompt="", model_name="GPT-4o", custom_api_key="", shorts_length=35, visual_style="cinema_8k"):
    """
    Generates a full, high-retention transcript first, then derives scene-specific image prompts,
    img-to-video motion prompts, sound design, and subtitle overlays.
    Enforces a strict MINIMUM duration of 30 seconds (no short clips) and seamless loop engineering.
    """
    target_length = max(int(shorts_length or 35), 30)
    print(f"[script_gen] Generating Director Script for: '{topic_title}' (Model: {model_name}, Style: '{visual_style}', Target: {target_length}s [MIN: 30s])")
    
    # Word count: 2.5 words per second = ~80-110 words for 30-40s
    word_count_min = max(75, int(target_length * 2.3))
    word_count_max = max(95, int(target_length * 2.8))
    scene_count_target = max(6, int(target_length / 4.5))

    system_prompt = (
        f"You are an award-winning cinematic director and viral storytelling expert (MagnatesMedia & Vox style).\n"
        f"Write a high-retention video transcript and visual storyboard for a vertical video (9:16 Shorts/Reels).\n\n"
        f"STRICT DURATION & WORD COUNT RULES:\n"
        f"- Target Duration: {target_length} SECONDS (MUST BE AT LEAST 30 SECONDS).\n"
        f"- Total Spoken Words: Between {word_count_min} and {word_count_max} words.\n"
        f"- Total Scenes: {scene_count_target} scenes. Each scene duration between 4.0 and 5.5 seconds.\n\n"
        f"STORYTELLING & RETENTION LOOP STRUCTURE:\n"
        f"1. THE SCROLL-STOPPING HOOK (Scenes 1-2): Immediate dramatic mystery or shocking premise without any greetings.\n"
        f"2. THE DEEPENING STAKES (Scenes 3-4): The hidden story, data, secret mechanism, or crisis.\n"
        f"3. THE BREAKTHROUGH / TWIST (Scenes 5-6): The turning point, breakthrough discovery, or unexpected reality.\n"
        f"4. THE SEAMLESS RETENTION LOOP (Final Scene): Deliver a powerful climax where the final words connect seamlessly into Scene 1's hook sentence for an infinite replay loop.\n\n"
        f"CRITICAL VISUAL & MOTION INSTRUCTIONS FOR EVERY SCENE (Aesthetic: {visual_style}):\n"
        f"- 'narration': Voiceover sentence (10-16 words per scene).\n"
        f"- 'image_prompt': Hyper-realistic, 8k cinematic visual description tailored to '{visual_style}' style. "
        f"Describe subject, dramatic lighting (volumetric, neon rim, golden hour, moody chiaroscuro), atmosphere, environment, 9:16 vertical aspect ratio.\n"
        f"- 'image_to_video_prompt': Exact camera movement and dynamic motion instruction for Image-to-Video models (e.g. 'cinematic slow zoom into subject, volumetric fog floating, 4k 60fps', 'whip pan to reveal details, subtle particle drift').\n"
        f"- 'subtitle_text': 2 to 4 high-impact words summarizing the scene punchline (e.g. 'THE HIDDEN TRUTH', 'EVERYTHING CHANGED').\n"
        f"- 'sfx': Sound effect ('whoosh', 'impact', 'glitch', 'rise', 'chime', 'bass_drop').\n"
        f"- 'transition_type': One of: 'whip_pan', 'glitch_flash', 'zoom_burst_in', 'speed_ramp', 'motion_blur_push', 'parallax_slide', 'white_flash'.\n"
        f"- 'emotion': One of: 'epic', 'suspenseful', 'dark', 'tech', 'energetic', 'curiosity'.\n\n"
        f"Return ONLY valid raw JSON with keys:\n"
        f'{{"title": "...", "description": "...", "tags": [...], "script": "...", "overall_emotion": "epic", "visual_style": "{visual_style}", "scenes": [...]}}'
    )
    
    user_prompt = (
        f"Topic: {topic_title}\n"
        f"{('Additional Context: ' + custom_prompt) if custom_prompt else ''}\n"
        f"Target Duration: {target_length} seconds (Must exceed 30 seconds).\n"
        f"Synthesize the script first with a seamless loop, then detailed scene image prompts, motion prompts, and audio sound design."
    )

    content_str = None

    # 1. Prioritize Astra if explicitly requested or if an Astra key is configured
    active_key = custom_api_key or os.environ.get("ASTRA_API_KEY", "") or os.environ.get("EXPERIENTIAL_API_KEY", "")
    clean_key = active_key.strip().rstrip('|') if active_key else ""
    is_astra = "astra" in model_name.lower() or (clean_key and clean_key.startswith("xpl_"))

    if is_astra and clean_key:
        print(f"[script_gen] [Experiential Labs] Routing to frontier model 'gpt-6-astra'...")
        try:
            headers = {
                "Authorization": f"Bearer {clean_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "gpt-6-astra",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "response_format": {"type": "json_object"}
            }
            resp = requests.post("https://api.experientiallabs.ai/v1/chat/completions", headers=headers, json=payload, timeout=60)
            if resp.status_code == 200:
                content_str = resp.json()["choices"][0]["message"]["content"]
                print(f"[script_gen] [SUCCESS] GPT-6 Astra script synthesized successfully!")
            elif resp.status_code == 429 and "card_required" in resp.text:
                print(f"[script_gen] [Astra Info] Card verification required on experientiallabs.ai to activate platform credits. Falling back to local/free model...")
            else:
                print(f"[script_gen] Astra HTTP {resp.status_code}: {resp.text[:120]}. Falling back...")
        except Exception as astra_ex:
            print(f"[script_gen] Experiential Astra note: {astra_ex}. Falling back...")

    # 2. Local Ollama if requested OR if Astra failed / not used and local Ollama is active
    if not content_str:
        is_ollama = "ollama" in model_name.lower() or any(m in model_name.lower() for m in ["shivam-pro", "deepseek", "qwen"])
        if not is_ollama and not custom_api_key:
            try:
                chk = requests.get("http://localhost:11434/api/tags", timeout=1.5)
                if chk.status_code == 200:
                    is_ollama = True
                    model_name = "qwen2.5-coder:7b"
                    print(f"[script_gen] [100% FREE AI] Detected active local Ollama! Auto-routing to local '{model_name}'.")
            except Exception:
                pass

        if is_ollama:
            content_str = _generate_ollama(model_name, system_prompt, user_prompt)

    # 3. Direct OpenAI / Gemini if custom key provided
    if not content_str and clean_key:
        is_openai = "GPT" in model_name or "gpt" in model_name
        is_gemini = "Gemini" in model_name or "gemini" in model_name
        if is_openai:
            print("[script_gen] Using Direct OpenAI API...")
            try:
                headers = {
                    "Authorization": f"Bearer {clean_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": "gpt-4o",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "response_format": {"type": "json_object"}
                }
                resp = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=45)
                resp.raise_for_status()
                content_str = resp.json()["choices"][0]["message"]["content"]
            except Exception as ex:
                print(f"[script_gen] Direct OpenAI failed: {ex}. Falling back...")
        elif is_gemini:
            print("[script_gen] Using Direct Google Gemini API...")
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={custom_api_key}"
                headers = {"Content-Type": "application/json"}
                payload = {
                    "contents": [
                        {
                            "role": "user",
                            "parts": [
                                {"text": f"{system_prompt}\n\nUser Request:\n{user_prompt}"}
                            ]
                        }
                    ],
                    "generationConfig": {
                        "responseMimeType": "application/json"
                    }
                }
                resp = requests.post(url, headers=headers, json=payload, timeout=45)
                resp.raise_for_status()
                result_json = resp.json()
                content_str = result_json["candidates"][0]["content"]["parts"][0]["text"]
            except Exception as ex:
                print(f"[script_gen] Direct Gemini failed: {ex}. Falling back...")

    # 3. Free Online Pollinations Text AI Engine
    if not content_str:
        print(f"[script_gen] Routing via Free Zero-Key AI Engine for '{topic_title}'...")
        try:
            poll_resp = requests.post(
                "https://text.pollinations.ai/",
                json={
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "jsonMode": True
                },
                timeout=35
            )
            if poll_resp.ok and poll_resp.text:
                content_str = poll_resp.text
                print(f"[script_gen] [OK] Successfully synthesized custom AI director script.")
        except Exception as poll_err:
            print(f"[script_gen] Free AI Engine note: {poll_err}")

    # Parse JSON if available
    if content_str:
        try:
            cleaned_str = content_str.strip()
            if cleaned_str.startswith("```"):
                cleaned_str = cleaned_str.split("```")[1]
                if cleaned_str.startswith("json"):
                    cleaned_str = cleaned_str[4:]
            cleaned_str = cleaned_str.strip("` \n\t")
            
            content_json = json.loads(cleaned_str)
            raw_scenes = content_json.get("scenes", [])
            if len(raw_scenes) >= 4:
                # Ensure each scene has rich image prompt and img-to-video prompt
                for s_idx, sc in enumerate(raw_scenes):
                    if not sc.get("image_prompt"):
                        sc["image_prompt"] = f"Cinematic 8k photorealistic vertical visual depicting {sc.get('narration', topic_title)}, dramatic volumetric lighting, ultra-detailed 9:16"
                    if not sc.get("image_to_video_prompt"):
                        sc["image_to_video_prompt"] = "Cinematic slow zoom into subject with floating ambient particles and volumetric light rays"
                    if not sc.get("duration"):
                        sc["duration"] = 5.0
                
                full_script = content_json.get("script") or " ".join([s.get("narration", "") for s in raw_scenes])
                return {
                    "title": content_json.get("title", topic_title),
                    "script": full_script,
                    "scenes": raw_scenes,
                    "overall_emotion": content_json.get("overall_emotion", "epic"),
                    "description": content_json.get("description", f"Deep-dive breakdown into {topic_title}."),
                    "tags": content_json.get("tags", ["Shorts", "Viral", "Trending", "AI"])
                }
        except Exception as err:
            print(f"[script_gen] JSON Parsing note: {err}. Building guaranteed 30s+ director script...")

    # Guaranteed 30s+ High-Retention Director Script tailored specifically to topic_title
    print(f"[script_gen] Synthesizing comprehensive 32-second director script for: '{topic_title}'...")
    safe_topic = topic_title.strip()
    
    fallback_scenes = [
        {
            "scene_number": 1,
            "narration": f"This is the untold story behind {safe_topic} that almost nobody is talking about.",
            "duration": 5.2,
            "image_prompt": f"Dramatic cinematic opening shot of {safe_topic}, ominous storm atmosphere, hyper-realistic 8k, volumetric rays, neon rim lighting, 9:16 vertical",
            "image_to_video_prompt": "Slow cinematic dolly zoom in with atmospheric smoke drifting across the screen",
            "subtitle_text": "THE UNTOLD STORY",
            "sfx": "rise",
            "transition_type": "zoom_burst_in",
            "emotion": "suspenseful"
        },
        {
            "scene_number": 2,
            "narration": "Behind closed doors, a massive breakthrough was unfolding that caught everyone off guard.",
            "duration": 5.0,
            "image_prompt": f"Secret laboratory and high-tech command center researching {safe_topic}, glowing holographic blueprints, deep blue and cyan lighting, vertical 9:16",
            "image_to_video_prompt": "Whip pan left across high-tech holographic displays with digital glimmers",
            "subtitle_text": "MASSIVE BREAKTHROUGH",
            "sfx": "impact",
            "transition_type": "whip_pan",
            "emotion": "tech"
        },
        {
            "scene_number": 3,
            "narration": "What seemed impossible just months ago has now shattered previous industry standards.",
            "duration": 5.4,
            "image_prompt": f"Shattered glass barrier with glowing golden quantum energy bursts illuminating {safe_topic}, ultra-detailed 8k, vertical 9:16",
            "image_to_video_prompt": "Fast speed ramp with glowing energy burst exploding outwards",
            "subtitle_text": "STANDARDS SHATTERED",
            "sfx": "glitch",
            "transition_type": "glitch_flash",
            "emotion": "epic"
        },
        {
            "scene_number": 4,
            "narration": "The data reveals an exponential surge, changing the landscape faster than predicted.",
            "duration": 5.2,
            "image_prompt": f"Futuristic exponential glowing growth charts and neural network nodes analyzing {safe_topic}, hyper-detailed dark aesthetic, vertical 9:16",
            "image_to_video_prompt": "Parallax slide motion across glowing neural nodes and data streams",
            "subtitle_text": "EXPONENTIAL SURGE",
            "sfx": "rise",
            "transition_type": "parallax_slide",
            "emotion": "epic"
        },
        {
            "scene_number": 5,
            "narration": "Experts agree that this marks a turning point you simply cannot afford to ignore.",
            "duration": 5.0,
            "image_prompt": f"Silhouette of visionary innovators looking towards an illuminated futuristic city skyline for {safe_topic}, golden hour, vertical 9:16",
            "image_to_video_prompt": "Smooth forward camera glide with golden lens flares spreading across the frame",
            "subtitle_text": "TURNING POINT",
            "sfx": "impact",
            "transition_type": "white_flash",
            "emotion": "epic"
        },
        {
            "scene_number": 6,
            "narration": "Subscribe now and comment below to stay ahead of the next major wave!",
            "duration": 4.8,
            "image_prompt": f"Epic victory emblem glowing with neon pulse and particle fire, cinematic clean finish, vertical 9:16",
            "image_to_video_prompt": "Camera punch zoom with glowing particle sparks and pulse wave",
            "subtitle_text": "SUBSCRIBE NOW",
            "sfx": "chime",
            "transition_type": "motion_blur_push",
            "emotion": "energetic"
        }
    ]
    
    total_dur = sum(s["duration"] for s in fallback_scenes)
    print(f"[script_gen] [OK] Script generated with {len(fallback_scenes)} scenes, total duration: {total_dur:.1f}s.")
    
    return {
        "title": safe_topic,
        "script": " ".join([s["narration"] for s in fallback_scenes]),
        "scenes": fallback_scenes,
        "overall_emotion": "epic",
        "description": f"Deep-dive breakdown into {safe_topic}. Explore how this event is changing everything.",
        "tags": ["Shorts", "Trending", "AI", safe_topic.replace(' ', '')[:15]]
    }


