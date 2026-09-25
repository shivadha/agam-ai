import os
import json
import re
import requests

# ---------------------------------------------------------------------------
# Constants – same pattern as script_gen.py
# ---------------------------------------------------------------------------
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "YOUR_OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Shared model mapping – mirrors script_gen.py exactly
MODEL_MAPPING = {
    "GPT-4o": "openai/gpt-4o",
    "Claude 3.5 Sonnet": "anthropic/claude-3.5-sonnet",
    "Gemini 1.5 Pro": "google/gemini-pro-1.5",
    "Gemini 2.5 Flash": "google/gemini-2.5-flash",
    "Llama 3.1 405B": "meta-llama/llama-3.1-405b-instruct",
}

def _generate_ollama(model_name: str, system_prompt: str, user_prompt: str) -> str:
    """Sends a local chat request to Ollama and processes the response."""
    ollama_model = "deepseek-r1:latest"
    if "shivam-pro" in model_name.lower():
        ollama_model = "shivam-pro" if ":" in model_name else "shivam-pro:latest"
    elif "deepseek-r1" in model_name.lower():
        ollama_model = "deepseek-r1" if ":" in model_name else "deepseek-r1:latest"
    elif "qwen3" in model_name.lower():
        ollama_model = "qwen3:8b" if "8b" not in model_name else model_name.lower()
    elif "qwen2.5-coder" in model_name.lower():
        ollama_model = "qwen2.5-coder:7b" if "7b" not in model_name else model_name.lower()
    elif "qwen" in model_name.lower():
        ollama_model = "qwen2.5-coder:7b"
    elif "deepseek" in model_name.lower():
        ollama_model = "deepseek-r1:latest"
        
    print(f"[viral_angle] [Ollama] Routing to local model: {ollama_model}")
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
            "stream": False
        }
        resp = requests.post(url, json=payload, timeout=90)
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        
        # Strip DeepSeek R1 reasoning think blocks
        if "<think>" in content:
            print("[viral_angle] [Ollama] Stripping <think> reasoning blocks...")
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
            if "<think>" in content:
                content = content.split("<think>")[0]
            content = content.strip()
            
        return content
    except Exception as e:
        print(f"[viral_angle] [Ollama] Request failed for model {ollama_model}: {e}")
        return None


# ---------------------------------------------------------------------------
# Valid values for structured output validation
# ---------------------------------------------------------------------------
VALID_EMOTIONS = {"surprise", "shock", "fear", "excitement", "curiosity", "anger", "inspiration"}
VALID_HOOK_TYPES = {"curiosity_gap", "shocking_fact", "controversy", "secret_reveal", "challenge", "countdown"}
VALID_LENGTHS = {30, 45, 60}

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
VIRAL_ANGLE_SYSTEM_PROMPT = (
    "You are an elite viral content strategist with 10+ years of experience creating "
    "trending YouTube Shorts, TikToks, and Instagram Reels that routinely hit millions of views. "
    "Your job is to analyse a topic or article summary and extract the single most potent viral angle.\n\n"
    "You MUST respond with a JSON object containing EXACTLY these keys:\n"
    "  - 'category' (str): The content category. One of: 'AI', 'Science', 'Gaming', 'Finance', "
    "'Motivation', 'News', 'Tech', 'Health', 'Entertainment', 'Politics'.\n"
    "  - 'emotion' (str): Primary viewer emotion to trigger. MUST be one of: "
    "'surprise', 'shock', 'fear', 'excitement', 'curiosity', 'anger', 'inspiration'.\n"
    "  - 'hook_type' (str): Hook mechanism to use. MUST be one of: "
    "'curiosity_gap', 'shocking_fact', 'controversy', 'secret_reveal', 'challenge', 'countdown'.\n"
    "  - 'target_audience' (str): Primary target audience description (e.g. 'tech enthusiasts aged 18-34').\n"
    "  - 'viral_angle' (str): Exactly 1 sentence describing the unique, unexpected angle that makes this "
    "content irresistible. Focus on tension, contrast, or revelation.\n"
    "  - 'retention_strategy' (str): The retention mechanic to use throughout the video. "
    "Examples: 'open loop + payoff', 'progressive reveal', 'controversy + resolution', "
    "'cliffhanger chain', 'challenge + result'.\n"
    "  - 'suggested_length' (int): Ideal Shorts length in seconds. MUST be one of: 30, 45, 60.\n\n"
    "Rules:\n"
    "  1. Think like a data-driven growth hacker — prioritise novelty and emotional impact.\n"
    "  2. The viral_angle must be counter-intuitive or surprising.\n"
    "  3. Return ONLY raw, valid JSON. No markdown, no code fences, no commentary.\n"
    "  4. Every key is REQUIRED. Do not omit any key.\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_json_string(raw: str) -> str:
    """Strip markdown fences that some models wrap around JSON."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        # Take the content between the first pair of fences
        cleaned = parts[1] if len(parts) > 1 else cleaned
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    return cleaned.strip("` \n\t")


def _validate_and_coerce(data: dict) -> dict:
    """Validate enum fields and coerce suggested_length to nearest valid value."""
    if data.get("emotion") not in VALID_EMOTIONS:
        data["emotion"] = "curiosity"
    if data.get("hook_type") not in VALID_HOOK_TYPES:
        data["hook_type"] = "curiosity_gap"
    try:
        length = int(data.get("suggested_length", 60))
        # Snap to nearest valid length
        data["suggested_length"] = min(VALID_LENGTHS, key=lambda x: abs(x - length))
    except (TypeError, ValueError):
        data["suggested_length"] = 60
    # Ensure all string keys are present
    for key in ("category", "target_audience", "viral_angle", "retention_strategy"):
        if not data.get(key):
            data[key] = _default_viral_angle()["key"]
    return data


def _default_viral_angle(topic: str = "this topic") -> dict:
    """Returns a smart default dict when the LLM call fails entirely."""
    return {
        "category": "AI",
        "emotion": "curiosity",
        "hook_type": "curiosity_gap",
        "target_audience": "general public",
        "viral_angle": (
            f"The hidden truth about {topic} that mainstream media refuses to cover "
            "is about to change everything you thought you knew."
        ),
        "retention_strategy": "open loop + payoff",
        "suggested_length": 60,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_viral_angle(
    topic: str,
    article_summary: str = "",
    model_name: str = "GPT-4o",
    custom_api_key: str = "",
) -> dict:
    """
    Analyses a topic (and optional article summary) and returns a structured
    viral angle dictionary.

    Parameters
    ----------
    topic : str
        The subject or headline to analyse.
    article_summary : str, optional
        A short summary of the source article for extra context.
    model_name : str
        Display name of the LLM to use (matched via MODEL_MAPPING).
    custom_api_key : str
        Optional direct API key for OpenAI or Google Gemini.

    Returns
    -------
    dict with keys: category, emotion, hook_type, target_audience,
                    viral_angle, retention_strategy, suggested_length.
    """
    print(f"[viral_angle] Extracting viral angle for: '{topic}' (model: {model_name})")

    user_prompt = f"Topic: {topic}\n"
    if article_summary:
        user_prompt += f"Article Summary:\n{article_summary}\n"
    user_prompt += "\nAnalyse the above and return the viral angle JSON."

    content_str: str | None = None

    # Check if we should route to Ollama first
    is_ollama = "ollama" in model_name.lower() or any(m in model_name.lower() for m in ["shivam-pro", "deepseek", "qwen"])
    if is_ollama:
        content_str = _generate_ollama(model_name, VIRAL_ANGLE_SYSTEM_PROMPT, user_prompt)

    # ------------------------------------------------------------------
    # 1. Try direct OpenAI API key
    # ------------------------------------------------------------------
    if not content_str and custom_api_key:
        is_openai = "GPT" in model_name or "gpt" in model_name
        is_gemini = "Gemini" in model_name or "gemini" in model_name

        if is_openai:
            print("[viral_angle] Using direct OpenAI API key...")
            try:
                headers = {
                    "Authorization": f"Bearer {custom_api_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": "gpt-4o",
                    "messages": [
                        {"role": "system", "content": VIRAL_ANGLE_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "response_format": {"type": "json_object"},
                }
                resp = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=45,
                )
                resp.raise_for_status()
                content_str = resp.json()["choices"][0]["message"]["content"]
            except Exception as ex:
                print(f"[viral_angle] Direct OpenAI failed: {ex}. Falling back...")

        elif is_gemini:
            print("[viral_angle] Using direct Google Gemini API key...")
            try:
                url = (
                    f"https://generativelanguage.googleapis.com/v1beta/models/"
                    f"gemini-2.5-flash:generateContent?key={custom_api_key}"
                )
                headers = {"Content-Type": "application/json"}
                payload = {
                    "contents": [
                        {
                            "role": "user",
                            "parts": [
                                {"text": f"{VIRAL_ANGLE_SYSTEM_PROMPT}\n\nUser Request:\n{user_prompt}"}
                            ],
                        }
                    ],
                    "generationConfig": {"responseMimeType": "application/json"},
                }
                resp = requests.post(url, headers=headers, json=payload, timeout=45)
                resp.raise_for_status()
                content_str = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            except Exception as ex:
                print(f"[viral_angle] Direct Gemini failed: {ex}. Falling back...")

        elif "muse" in model_name.lower() or custom_api_key.startswith("LLM_"):
            print("[viral_angle] Using Meta Muse Spark API...")
            for m_model in ["muse-spark-1.3", "muse-spark-1.3-contributor", "muse-spark-1.2"]:
                try:
                    resp = requests.post(
                        "https://api.meta.ai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {custom_api_key}", "Content-Type": "application/json"},
                        json={
                            "model": m_model,
                            "messages": [
                                {"role": "system", "content": VIRAL_ANGLE_SYSTEM_PROMPT},
                                {"role": "user", "content": user_prompt},
                            ],
                        },
                        timeout=30,
                    )
                    if resp.status_code == 200:
                        content_str = resp.json()["choices"][0]["message"]["content"]
                        break
                except Exception as ex:
                    print(f"[viral_angle] Meta Muse ({m_model}) failed: {ex}")

    # ------------------------------------------------------------------
    # 2. Fall back to OpenRouter
    # ------------------------------------------------------------------
    if not content_str:
        # Check if local Ollama can be used as a smart zero-key fallback
        print("[viral_angle] Attempting local Ollama fallback before OpenRouter...")
        content_str = _generate_ollama("Ollama (deepseek-r1)", VIRAL_ANGLE_SYSTEM_PROMPT, user_prompt)

    if not content_str:
        print("[viral_angle] Routing via OpenRouter API...")
        openrouter_model = MODEL_MAPPING.get(model_name, "google/gemini-2.5-flash")
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": openrouter_model,
            "messages": [
                {"role": "system", "content": VIRAL_ANGLE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            content_str = resp.json()["choices"][0]["message"]["content"]
        except Exception as ex:
            print(f"[viral_angle] OpenRouter call failed: {ex}")

    # ------------------------------------------------------------------
    # 3. Parse and return
    # ------------------------------------------------------------------
    if content_str:
        try:
            cleaned = _clean_json_string(content_str)
            data = json.loads(cleaned)
            data = _validate_and_coerce(data)
            print(
                f"[viral_angle] Success — emotion={data['emotion']}, "
                f"hook_type={data['hook_type']}, length={data['suggested_length']}s"
            )
            return data
        except Exception as parse_err:
            print(f"[viral_angle] JSON parsing failed: {parse_err}. Raw: {content_str[:200]}")

    # ------------------------------------------------------------------
    # 4. Smart default fallback
    # ------------------------------------------------------------------
    print("[viral_angle] Returning smart default fallback.")
    return _default_viral_angle(topic)
