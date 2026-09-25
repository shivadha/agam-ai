import os
import json
import re
import requests
from dotenv import load_dotenv
load_dotenv()

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "YOUR_OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Hugging Face free-tier text fallback (no key strictly required for public models,
# HF_TOKEN raises rate limits when set).
HF_TEXT_MODEL = "Qwen/Qwen2.5-7B-Instruct"
HF_INFERENCE_URL = f"https://api-inference.huggingface.co/models/{HF_TEXT_MODEL}"


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


def _generate_hf_instruct(system_prompt: str, user_prompt: str, max_new_tokens: int = 2500) -> str | None:
    """
    Zero-key fallback via Hugging Face Inference API (Qwen2.5-7B-Instruct).
    Used only when no configured provider produced output.
    """
    hf_token = os.environ.get("HF_TOKEN", "").strip() or os.environ.get("HUGGINGFACE_TOKEN", "").strip()
    chat_text = (
        "<|im_start|>system\n" + system_prompt.strip() + "<|im_end|>\n"
        "<|im_start|>user\n" + user_prompt.strip() + "<|im_end|>\n"
        "<|im_start|>assistant\n"
    )
    headers = {"Content-Type": "application/json"}
    if hf_token:
        headers["Authorization"] = f"Bearer {hf_token}"
    try:
        resp = requests.post(
            HF_INFERENCE_URL,
            headers=headers,
            json={
                "inputs": chat_text,
                "parameters": {
                    "max_new_tokens": max_new_tokens,
                    "temperature": 0.7,
                    "return_full_text": False,
                },
            },
            timeout=90,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and data and isinstance(data[0], dict):
                text = (data[0].get("generated_text") or "").strip()
                if text:
                    print("[script_gen] [OK] Generated via Hugging Face Inference (Qwen2.5-7B-Instruct).")
                    return text
            print(f"[script_gen] HF Inference unexpected payload: {str(data)[:120]}")
        else:
            print(f"[script_gen] HF Inference HTTP {resp.status_code}: {resp.text[:120]}")
    except Exception as e:
        print(f"[script_gen] HF Inference note: {e}")
    return None


def _chat_via_chain(system_prompt: str, user_prompt: str, model_name: str = "GPT-4o",
                   custom_api_key: str = "", tag: str = "task",
                   max_new_tokens: int = 2500) -> str | None:
    """
    Walk the provider chain and return the first successful completion text,
    or None when nothing produced output. Order mirrors production priority:
    Astra -> explicit Ollama -> Muse Spark -> Groq -> Gemini -> OpenAI ->
    OpenRouter (free :free models) -> Pollinations (free) ->
    Hugging Face Inference (free).
    """
    content_str = None
    active_key = custom_api_key or os.environ.get("ASTRA_API_KEY", "") or os.environ.get("EXPERIENTIAL_API_KEY", "")
    clean_key = active_key.strip().rstrip('|') if active_key else ""
    is_astra = "astra" in model_name.lower() or (clean_key and clean_key.startswith("xpl_"))

    # 1. Prioritize Astra if explicitly requested or if an Astra key is configured
    if is_astra and clean_key:
        print(f"[script_gen] [{tag}] [Experiential Labs] Routing to frontier model 'gpt-6-astra'...")
        try:
            headers = {"Authorization": f"Bearer {clean_key}", "Content-Type": "application/json"}
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
                print(f"[script_gen] [{tag}] [SUCCESS] Astra response received.")
            elif resp.status_code == 429 and "card_required" in resp.text:
                print(f"[script_gen] [{tag}] [Astra Info] Card verification required. Falling back...")
            else:
                print(f"[script_gen] [{tag}] Astra HTTP {resp.status_code}: {resp.text[:120]}. Falling back...")
        except Exception as astra_ex:
            print(f"[script_gen] [{tag}] Astra note: {astra_ex}. Falling back...")

    # 2. Explicit local Ollama
    is_explicit_ollama = any(k in model_name.lower() for k in ["ollama", "shivam-pro", "deepseek", "qwen2.5-coder", "local"])
    if not content_str and is_explicit_ollama:
        print(f"[script_gen] [{tag}] Explicit Ollama model selected: {model_name}")
        content_str = _generate_ollama(model_name, system_prompt, user_prompt)

    # 2.5. Meta Muse Spark Model API
    muse_key = clean_key if ("muse" in model_name.lower() or clean_key.startswith("LLM_")) else (os.environ.get("MUSE_API_KEY", "").strip() or os.environ.get("META_API_KEY", "").strip() or (clean_key if clean_key.startswith("LLM_") else ""))
    if not content_str and (("muse" in model_name.lower() or clean_key.startswith("LLM_")) or muse_key):
        print(f"[script_gen] [{tag}] Routing to Meta Muse Spark Model API...")
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
                    print(f"[script_gen] [{tag}] [OK] Muse Spark ({m_model}) responded.")
                    break
                else:
                    print(f"[script_gen] [{tag}] Muse ({m_model}) HTTP {m_resp.status_code}: {m_resp.text[:120]}")
            except Exception as m_err:
                print(f"[script_gen] [{tag}] Muse attempt failed ({m_model}): {m_err}")

    # 3. Groq Fast Cloud API
    groq_key = clean_key if ("groq" in model_name.lower()) else (os.environ.get("GROQ_API_KEY", "").strip() or clean_key)
    if not content_str and groq_key:
        print(f"[script_gen] [{tag}] Routing to Groq Fast Inference API...")
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
                    print(f"[script_gen] [{tag}] [OK] Groq ({g_model}) responded.")
                    break
                else:
                    print(f"[script_gen] [{tag}] Groq ({g_model}) HTTP {g_resp.status_code}: {g_resp.text[:120]}")
            except Exception as g_err:
                print(f"[script_gen] [{tag}] Groq attempt failed ({g_model}): {g_err}")

    # 4. Google Gemini API
    gemini_key = clean_key if ("gemini" in model_name.lower()) else (os.environ.get("GEMINI_API_KEY", "").strip() or clean_key)
    if not content_str and gemini_key:
        print(f"[script_gen] [{tag}] Routing to Google Gemini API...")
        for gem_model in ["gemini-2.0-flash", "gemini-1.5-flash"]:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{gem_model}:generateContent?key={gemini_key}"
                payload = {
                    "contents": [{"role": "user", "parts": [{"text": f"{system_prompt}\n\nUser Request:\n{user_prompt}"}]}],
                    "generationConfig": {"responseMimeType": "application/json"}
                }
                resp = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=45)
                if resp.status_code == 200:
                    content_str = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                    print(f"[script_gen] [{tag}] [OK] Gemini ({gem_model}) responded.")
                    break
                else:
                    print(f"[script_gen] [{tag}] Gemini ({gem_model}) HTTP {resp.status_code}: {resp.text[:120]}")
            except Exception as ex:
                print(f"[script_gen] [{tag}] Gemini failed ({gem_model}): {ex}.")

    # 5. OpenAI API
    openai_key = clean_key if ("gpt" in model_name.lower()) else (os.environ.get("OPENAI_API_KEY", "").strip() or clean_key)
    if (not content_str and openai_key
            and not openai_key.startswith("xpl_") and not openai_key.startswith("LLM_")):
        print(f"[script_gen] [{tag}] Routing to OpenAI API...")
        for o_model in ["gpt-4o", "gpt-4o-mini"]:
            try:
                headers = {"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"}
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
                    print(f"[script_gen] [{tag}] [OK] OpenAI ({o_model}) responded.")
                    break
                else:
                    print(f"[script_gen] [{tag}] OpenAI ({o_model}) HTTP {resp.status_code}: {resp.text[:120]}")
            except Exception as ex:
                print(f"[script_gen] [{tag}] OpenAI failed: {ex}.")

    # 5.5. OpenRouter — one free key unlocks 300+ models, many with :free tiers.
    # Free tier needs no card: 20 req/min, 50 req/day. Tries several free
    # models in order since the free lineup rotates without warning.
    or_key = ""
    if "openrouter" in model_name.lower():
        or_key = clean_key or os.environ.get("OPENROUTER_API_KEY", "").strip()
    else:
        or_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not content_str and or_key:
        or_models = [m.strip() for m in os.environ.get("OPENROUTER_MODELS", "").split(",") if m.strip()] or [
            "deepseek/deepseek-chat:free",
            "qwen/qwen3-235b-a22b:free",
            "google/gemma-3-27b-it:free",
            "openai/gpt-oss-120b:free",
        ]
        print(f"[script_gen] [{tag}] Routing to OpenRouter (free models)...")
        for or_model in or_models:
            try:
                or_resp = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {or_key}", "Content-Type": "application/json",
                             "HTTP-Referer": "http://localhost:3000", "X-Title": "AGAM AI Studio"},
                    json={"model": or_model,
                          "messages": [{"role": "system", "content": system_prompt},
                                       {"role": "user", "content": user_prompt}],
                          "temperature": 0.7},
                    timeout=45,
                )
                if or_resp.status_code == 200:
                    content_str = or_resp.json()["choices"][0]["message"]["content"]
                    print(f"[script_gen] [{tag}] [OK] OpenRouter ({or_model}) responded.")
                    break
                else:
                    print(f"[script_gen] [{tag}] OpenRouter ({or_model}) HTTP {or_resp.status_code}: {or_resp.text[:120]}")
            except Exception as or_err:
                print(f"[script_gen] [{tag}] OpenRouter attempt failed ({or_model}): {or_err}")

    # 6. Free Online Pollinations Text AI Engine
    if not content_str:
        print(f"[script_gen] [{tag}] Routing via Free Zero-Key Pollinations engine...")
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
                print(f"[script_gen] [{tag}] [OK] Pollinations responded.")
        except Exception as poll_err:
            print(f"[script_gen] [{tag}] Pollinations note: {poll_err}")

    # 7. Hugging Face Inference (free tier) — last resort before giving up
    if not content_str:
        print(f"[script_gen] [{tag}] Routing via Hugging Face Inference (free tier)...")
        content_str = _generate_hf_instruct(system_prompt, user_prompt, max_new_tokens=max_new_tokens)

    return content_str


def _scrape_article_text(article_url: str, max_chars: int = 2500) -> str:
    """Best-effort article text extraction for grounding the script in real context."""
    if not article_url:
        return ""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; AGAMStudio/1.0)"}
        resp = requests.get(article_url, headers=headers, timeout=12)
        if resp.status_code != 200:
            return ""
        html = resp.text
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)
        except Exception:
            text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception as e:
        print(f"[script_gen] [context] Article scrape note: {e}")
        return ""


def gather_topic_context(topic_title: str, article_url: str = "", article_summary: str = "",
                         custom_prompt: str = "", model_name: str = "GPT-4o",
                         custom_api_key: str = "") -> str:
    """
    Phase 1 of script generation: build a researched context brief about the title
    BEFORE any script is written. Uses the article (URL scrape or summary) when
    available, otherwise asks the AI to recall key facts about the topic.

    Returns a context string (possibly empty — never raises).
    """
    print(f"[script_gen] [context] Gathering context for: '{topic_title}'")

    source_text = (article_summary or "").strip()
    if not source_text and article_url:
        source_text = _scrape_article_text(article_url)
        if source_text:
            print(f"[script_gen] [context] Scraped {len(source_text)} chars from article URL.")

    system_prompt = (
        "You are a meticulous research assistant for a viral video director.\n"
        "Given a video title (and optional source material), produce a tight CONTEXT BRIEF "
        "the director will use to write an accurate, specific script.\n"
        "Return ONLY valid raw JSON with keys:\n"
        '{"facts": ["..."], "why_it_matters": "...", "target_audience": "...", '
        '"narrative_beats": ["..."], "key_terms": ["..."]}\n'
        "Rules: 4-7 concrete facts (no fluff, no invented statistics — if unsure, say what is "
        "generally known), why_it_matters in one sentence, 3 narrative beats in story order, "
        "key_terms = 5-8 topical nouns for visual generation."
    )
    user_prompt = f"Video title: {topic_title}\n"
    if source_text:
        user_prompt += f"Source material:\n{source_text[:2200]}\n"
    if custom_prompt:
        user_prompt += f"Creator notes: {custom_prompt[:500]}\n"
    user_prompt += "Write the context brief now."

    brief_json = _chat_via_chain(system_prompt, user_prompt, model_name, custom_api_key,
                                 tag="context", max_new_tokens=900)
    if not brief_json:
        print("[script_gen] [context] No AI context available — continuing with title only.")
        fallback = f"Topic: {topic_title}."
        if source_text:
            fallback += f" Source excerpt: {source_text[:600]}"
        return fallback

    try:
        cleaned = brief_json.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        cleaned = cleaned.strip("` \n\t")
        brief = json.loads(cleaned)
        facts = brief.get("facts") or []
        beats = brief.get("narrative_beats") or []
        terms = brief.get("key_terms") or []
        context = (
            f"RESEARCHED CONTEXT for '{topic_title}':\n"
            f"Key facts: {'; '.join(str(f) for f in facts[:7])}\n"
            f"Why it matters: {brief.get('why_it_matters', '')}\n"
            f"Target audience: {brief.get('target_audience', '')}\n"
            f"Narrative beats: {' -> '.join(str(b) for b in beats[:5])}\n"
            f"Visual key terms: {', '.join(str(t) for t in terms[:8])}"
        )
        print(f"[script_gen] [context] Brief ready ({len(facts)} facts, {len(beats)} beats).")
        return context
    except Exception as e:
        print(f"[script_gen] [context] Brief parse note: {e} — using raw text.")
        return f"Topic background notes for '{topic_title}': {brief_json[:1200]}"


def _parse_script_json(content_str: str, topic_title: str) -> dict | None:
    """Parse the director-script JSON; returns None when unparseable."""
    try:
        cleaned_str = content_str.strip()
        if cleaned_str.startswith("```"):
            cleaned_str = cleaned_str.split("```")[1]
            if cleaned_str.startswith("json"):
                cleaned_str = cleaned_str[4:]
        cleaned_str = cleaned_str.strip("` \n\t")
        return json.loads(cleaned_str)
    except Exception as err:
        print(f"[script_gen] JSON Parsing failed: {err}. Raw response was: {content_str[:200]}")
        return None


def _validate_and_repair_scenes(raw_scenes: list, topic_title: str, visual_style: str) -> list:
    """
    Strict per-scene validation. A scene is kept only if it has usable narration;
    missing image_prompt / image_to_video_prompt are repaired from the narration
    (which is itself context-specific). Scenes are renumbered sequentially.
    """
    valid = []
    for s_idx, sc in enumerate(raw_scenes or []):
        if not isinstance(sc, dict):
            print(f"[script_gen] Dropping scene {s_idx + 1}: not a JSON object.")
            continue
        narr = (sc.get("narration") or "").strip()
        if not narr or len(narr.split()) < 4:
            print(f"[script_gen] Dropping scene {s_idx + 1}: no usable narration.")
            continue
        if not sc.get("image_prompt"):
            sc["image_prompt"] = (
                f"Cinematic photorealistic 8k vertical shot of: {narr}. "
                f"Topic: {topic_title}. Dramatic volumetric lighting, hyper-detailed "
                f"environment, movie still, {visual_style} style, 9:16 vertical aspect ratio"
            )
            print(f"[script_gen] Repaired missing image_prompt for scene {s_idx + 1}.")
        if not sc.get("image_to_video_prompt"):
            sc["image_to_video_prompt"] = (
                f"Cinematic slow camera push-in on: {narr[:70]}, volumetric light rays, "
                f"subtle organic motion, 4k 60fps"
            )
            print(f"[script_gen] Repaired missing image_to_video_prompt for scene {s_idx + 1}.")
        if not sc.get("duration"):
            sc["duration"] = 5.0
        sc["scene_number"] = len(valid) + 1
        valid.append(sc)
    return valid


def generate_video_content(topic_title, custom_prompt="", model_name="GPT-4o", custom_api_key="",
                           shorts_length=35, visual_style="cinema_8k",
                           article_url="", article_summary="", topic_context=""):
    """
    Generates a full, high-retention transcript first, then derives scene-specific image prompts,
    img-to-video motion prompts, sound design, and subtitle overlays.
    Enforces a strict MINIMUM duration of 30 seconds (no short clips) and seamless loop engineering.

    Phase 1 (new): gather_topic_context() researches the title first so the script
    is grounded in real context instead of generic filler.
    Phase 2: director script generation. FAIL-FAST — raises RuntimeError when no
    provider can produce a valid, context-aware script (the pipeline must NOT continue).
    """
    target_length = max(int(shorts_length or 35), 30)
    print(f"[script_gen] Generating Director Script for: '{topic_title}' (Model: {model_name}, Style: '{visual_style}', Target: {target_length}s [MIN: 30s])")

    # ── Phase 1: context first ──────────────────────────────────────────────
    context = topic_context or gather_topic_context(
        topic_title,
        article_url=article_url,
        article_summary=article_summary,
        custom_prompt=custom_prompt,
        model_name=model_name,
        custom_api_key=custom_api_key,
    )

    # Word count: 2.5 words per second = ~80-110 words for 30-40s
    word_count_min = max(75, int(target_length * 2.3))
    word_count_max = max(95, int(target_length * 2.8))
    scene_count_target = max(6, int(target_length / 4.5))

    system_prompt = (
        f"You are an award-winning cinematic director and viral storytelling expert (MagnatesMedia & Vox style).\n"
        f"Write a high-retention video transcript and visual storyboard for a vertical video (9:16 Shorts/Reels).\n"
        f"GROUND EVERYTHING in the researched context below — use its specific facts, terms and beats. "
        f"Never write generic filler; every scene must be about THIS topic.\n\n"
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
        f"- 'image_prompt': Hyper-realistic, 8k cinematic visual description tailored to '{visual_style}' style AND to the researched context. "
        f"Describe subject, dramatic lighting (volumetric, neon rim, golden hour, moody chiaroscuro), atmosphere, environment, 9:16 vertical aspect ratio. "
        f"Every prompt must be UNIQUE to its scene's narration — never repeat a prompt.\n"
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
        f"{context}\n"
        f"Target Duration: {target_length} seconds (Must exceed 30 seconds).\n"
        f"Generate Scene 1 as the Title Hero scene with dedicated title image and image-to-video motion, followed by visually connected scenes."
    )

    # ── Phase 2: director script ────────────────────────────────────────────
    content_str = _chat_via_chain(system_prompt, user_prompt, model_name, custom_api_key,
                                  tag="script", max_new_tokens=3000)

    # Parse and strictly validate
    if content_str:
        content_json = _parse_script_json(content_str, topic_title)
        if content_json:
            raw_scenes = content_json.get("scenes", [])
            scenes = _validate_and_repair_scenes(raw_scenes, topic_title, visual_style)
            if len(scenes) >= 3:
                full_script = content_json.get("script") or " ".join(s.get("narration", "") for s in scenes)
                print(f"[script_gen] [SUCCESS] AI generated {len(scenes)} validated context-specific scenes for: '{topic_title}'!")
                return {
                    "title": content_json.get("title", topic_title),
                    "script": full_script,
                    "scenes": scenes,
                    "overall_emotion": content_json.get("overall_emotion", "epic"),
                    "description": content_json.get("description", f"Deep-dive breakdown into {topic_title}."),
                    "tags": content_json.get("tags", ["Shorts", "Viral", "Trending", "AI"])
                }
            else:
                print(f"[script_gen] Validation failed: only {len(scenes)} usable scenes (need >= 3).")

    # FAIL-FAST: No generic hardcoded dummy templates!
    # If script generation is not done, DO NOT start the next process.
    err_msg = (
        f"AI Script Generation Failed: No connected AI model could produce a context-aware script for '{topic_title}'. "
        f"Please check your API key / model settings and test the live connection before running."
    )
    print(f"[script_gen] [CRITICAL ERROR] {err_msg}")
    raise RuntimeError(err_msg)
