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
        f"MANDATORY ARCHITECTURE — TITLE SCENE & CONNECTING SCENES:\n"
        f"1. SCENE 1 (THE TITLE HERO SCENE):\n"
        f"   - Must serve as the Title Visual Hook. Its 'image_prompt' must be a jaw-dropping, iconic visual embodiment of the Topic Title: '{topic_title}'.\n"
        f"   - Its 'image_to_video_prompt' must be an attention-grabbing dynamic camera motion (e.g. 'cinematic push-in with volumetric lighting flare, 4k 60fps') that brings the title to life in the first 2 seconds.\n"
        f"   - 'scene_type': 'title_hero'\n\n"
        f"2. CONNECTING SCENE CONTINUITY (SCENES 2 TO {scene_count_target}):\n"
        f"   - EVERY subsequent scene MUST logically and visually connect to the previous scene ('connected_from' anchor).\n"
        f"   - Maintain identical character appearance, environment lighting, cinematic color grading, and smooth camera momentum from scene to scene.\n"
        f"   - Never generate disconnected, random clips. Each scene must carry the visual narrative forward seamlessly.\n\n"
        f"3. THE SEAMLESS RETENTION LOOP (FINAL SCENE):\n"
        f"   - Deliver a powerful climax where the final words connect seamlessly into Scene 1's hook sentence for an infinite replay loop.\n\n"
        f"CRITICAL PER-SCENE JSON SCHEMA (Aesthetic: {visual_style}):\n"
        f"- 'scene_number': Integer (1, 2, ...)\n"
        f"- 'scene_type': 'title_hero' for Scene 1, 'connecting_story' for subsequent scenes.\n"
        f"- 'connected_from': Visual bridge from previous scene (e.g. 'Continuing from Scene 1 camera push, now tracking subject...').\n"
        f"- 'narration': Voiceover sentence (10-16 words per scene).\n"
        f"- 'image_prompt': Hyper-realistic, 8k cinematic visual description tailored to '{visual_style}' style. "
        f"Describe subject, dramatic lighting (volumetric, neon rim, golden hour, moody chiaroscuro), atmosphere, environment, 9:16 vertical aspect ratio.\n"
        f"- 'image_to_video_prompt': Exact camera movement and dynamic motion instruction for Image-to-Video models (e.g. 'cinematic slow zoom into subject, volumetric fog floating, 4k 60fps', 'whip pan to reveal details, subtle particle drift').\n"
        f"- 'subtitle_text': 2 to 4 high-impact words summarizing the scene punchline (e.g. 'THE HIDDEN TRUTH', 'EVERYTHING CHANGED').\n"
        f"- 'sfx': Sound effect ('whoosh', 'impact', 'glitch', 'rise', 'chime', 'bass_drop').\n"
        f"- 'transition_type': One of: 'whip_pan', 'glitch_flash', 'zoom_burst_in', 'speed_ramp', 'motion_blur_push', 'parallax_slide', 'white_flash'.\n"
        f"- 'emotion': One of: 'epic', 'suspenseful', 'dark', 'tech', 'energetic', 'curiosity'.\n\n"
        f"Return ONLY valid raw JSON with keys:\n"
        f'{{"title": "{topic_title}", "description": "...", "tags": [...], "script": "...", "overall_emotion": "epic", "visual_style": "{visual_style}", "scenes": [...]}}'
    )
    
    user_prompt = (
        f"Topic Title: {topic_title}\n"
        f"{('Additional Context: ' + custom_prompt) if custom_prompt else ''}\n"
        f"Target Duration: {target_length} seconds (Must exceed 30 seconds).\n"
        f"Generate Scene 1 as the Title Hero scene with dedicated title image and image-to-video motion, followed by visually connected scenes."
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
                print(f"[script_gen] [Astra Info] Card verification required on experientiallabs.ai to activate platform credits. Falling back to next...")
            else:
                print(f"[script_gen] Astra HTTP {resp.status_code}: {resp.text[:120]}. Falling back...")
        except Exception as astra_ex:
            print(f"[script_gen] Experiential Astra note: {astra_ex}. Falling back...")

    # 2. If user explicitly requested local Ollama
    is_explicit_ollama = any(k in model_name.lower() for k in ["ollama", "shivam-pro", "deepseek", "qwen2.5-coder", "local"])
    if not content_str and is_explicit_ollama:
        print(f"[script_gen] Explicit Ollama model selected: {model_name}")
        content_str = _generate_ollama(model_name, system_prompt, user_prompt)

    # 2.5. Meta Muse Spark Model API
    muse_key = clean_key if ("muse" in model_name.lower() or clean_key.startswith("LLM_")) else (os.environ.get("MUSE_API_KEY", "").strip() or os.environ.get("META_API_KEY", "").strip() or (clean_key if clean_key.startswith("LLM_") else ""))
    if not content_str and (("muse" in model_name.lower() or clean_key.startswith("LLM_")) or muse_key):
        print("[script_gen] Routing to Meta Muse Spark Model API...")
        muse_models = ["muse-spark-1.3", "muse-spark-1.3-contributor", "muse-spark-1.2", "muse-spark-1.1"]
        for m_model in muse_models:
            try:
                m_resp = requests.post(
                    "https://api.meta.ai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {muse_key}", "Content-Type": "application/json"},
                    json={
                        "model": m_model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "temperature": 0.7
                    },
                    timeout=30
                )
                if m_resp.status_code == 200:
                    content_str = m_resp.json()["choices"][0]["message"]["content"]
                    print(f"[script_gen] [OK] Successfully generated script using Meta Muse Spark ({m_model})!")
                    break
                else:
                    print(f"[script_gen] Meta Muse ({m_model}) HTTP {m_resp.status_code}: {m_resp.text[:120]}")
            except Exception as m_err:
                print(f"[script_gen] Meta Muse attempt failed ({m_model}): {m_err}")

    # 3. Groq Fast Cloud API (Free & ultra-fast ~800 tokens/sec)
    groq_key = clean_key if ("groq" in model_name.lower()) else (os.environ.get("GROQ_API_KEY", "").strip() or clean_key)
    if not content_str and groq_key:
        print("[script_gen] Routing to Groq Fast Inference API...")
        groq_models = ["qwen/qwen3.8-27b", "openai/gpt-oss-20b", "openai/gpt-oss-120b"]
        for g_model in groq_models:
            try:
                g_resp = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                    json={
                        "model": g_model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.7
                    },
                    timeout=30
                )
                if g_resp.status_code == 200:
                    content_str = g_resp.json()["choices"][0]["message"]["content"]
                    print(f"[script_gen] [OK] Successfully generated script using Groq ({g_model})!")
                    break
                else:
                    print(f"[script_gen] Groq ({g_model}) HTTP {g_resp.status_code}: {g_resp.text[:120]}")
            except Exception as g_err:
                print(f"[script_gen] Groq attempt failed ({g_model}): {g_err}")

    # 4. Google Gemini API (Free tier from Jio / Google AI Studio)
    gemini_key = clean_key if ("gemini" in model_name.lower()) else (os.environ.get("GEMINI_API_KEY", "").strip() or clean_key)
    if not content_str and gemini_key:
        print("[script_gen] Routing to Google Gemini API (gemini-2.0-flash)...")
        for gem_model in ["gemini-2.0-flash", "gemini-1.5-flash"]:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{gem_model}:generateContent?key={gemini_key}"
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
                if resp.status_code == 200:
                    result_json = resp.json()
                    content_str = result_json["candidates"][0]["content"]["parts"][0]["text"]
                    print(f"[script_gen] [OK] Successfully generated script using Gemini ({gem_model})!")
                    break
                else:
                    print(f"[script_gen] Gemini ({gem_model}) HTTP {resp.status_code}: {resp.text[:120]}")
            except Exception as ex:
                print(f"[script_gen] Direct Gemini failed ({gem_model}): {ex}. Trying next...")

    # 5. OpenAI API
    openai_key = clean_key if ("gpt" in model_name.lower()) else (os.environ.get("OPENAI_API_KEY", "").strip() or clean_key)
    if not content_str and openai_key:
        print("[script_gen] Routing to OpenAI API (gpt-4o)...")
        for o_model in ["gpt-4o", "gpt-4o-mini"]:
            try:
                headers = {
                    "Authorization": f"Bearer {openai_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": o_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "response_format": {"type": "json_object"}
                }
                resp = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=45)
                if resp.status_code == 200:
                    content_str = resp.json()["choices"][0]["message"]["content"]
                    print(f"[script_gen] [OK] Successfully generated script using OpenAI ({o_model})!")
                    break
                else:
                    print(f"[script_gen] OpenAI ({o_model}) HTTP {resp.status_code}: {resp.text[:120]}")
            except Exception as ex:
                print(f"[script_gen] Direct OpenAI failed: {ex}. Falling back...")

    # 6. Free Online Pollinations Text AI Engine
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
                print(f"[script_gen] [OK] Successfully synthesized custom AI director script via Pollinations.")
        except Exception as poll_err:
            print(f"[script_gen] Free AI Engine note: {poll_err}")

    # Parse and validate JSON
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
            if len(raw_scenes) >= 3:
                # Ensure each scene has rich, contextual image_prompt and img-to-video prompt
                for s_idx, sc in enumerate(raw_scenes):
                    narr = sc.get("narration") or f"Scene {s_idx+1} about {topic_title}"
                    if not sc.get("image_prompt"):
                        sc["image_prompt"] = (
                            f"Cinematic photorealistic 8k vertical shot depicting {narr}. "
                            f"Dramatic volumetric lighting, hyper-detailed environment, movie still, 9:16 vertical aspect ratio"
                        )
                    if not sc.get("image_to_video_prompt"):
                        sc["image_to_video_prompt"] = (
                            f"Cinematic slow camera push-in focusing on {narr[:60]}, atmospheric lighting rays and subtle organic movement"
                        )
                    if not sc.get("duration"):
                        sc["duration"] = 5.0
                    sc["scene_number"] = s_idx + 1
                
                full_script = content_json.get("script") or " ".join([s.get("narration", "") for s in raw_scenes])
                print(f"[script_gen] [SUCCESS] AI generated {len(raw_scenes)} custom context-specific scenes for: '{topic_title}'!")
                return {
                    "title": content_json.get("title", topic_title),
                    "script": full_script,
                    "scenes": raw_scenes,
                    "overall_emotion": content_json.get("overall_emotion", "epic"),
                    "description": content_json.get("description", f"Deep-dive breakdown into {topic_title}."),
                    "tags": content_json.get("tags", ["Shorts", "Viral", "Trending", "AI"])
                }
        except Exception as err:
            print(f"[script_gen] JSON Parsing failed: {err}. Raw response was: {content_str[:200]}")

    # FAIL-FAST: No generic hardcoded dummy templates!
    # If script generation is not done, DO NOT start the next process.
    err_msg = (
        f"AI Script Generation Failed: No connected AI model could produce a context-aware script for '{topic_title}'. "
        f"Please check your API key / model settings and test the live connection before running."
    )
    print(f"[script_gen] [CRITICAL ERROR] {err_msg}")
    raise RuntimeError(err_msg)


