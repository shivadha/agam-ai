import os
import re
import json
import random
import requests

# ---------------------------------------------------------------------------
# Constants – mirrors script_gen.py / viral_angle.py
# ---------------------------------------------------------------------------
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "YOUR_OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

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
        
    print(f"[hook_gen] [Ollama] Routing to local model: {ollama_model}")
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
            print("[hook_gen] [Ollama] Stripping <think> reasoning blocks...")
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
            if "<think>" in content:
                content = content.split("<think>")[0]
            content = content.strip()
            
        return content
    except Exception as e:
        print(f"[hook_gen] [Ollama] Request failed for model {ollama_model}: {e}")
        return None


# ---------------------------------------------------------------------------
# Built-in reference hooks for testing / inspiration
# ---------------------------------------------------------------------------
EXAMPLE_HOOKS: list[str] = [
    "This free AI just ended Photoshop",
    "Nobody is talking about this...",
    "This secret scares Big Tech",
    "They hid this from you for years",
    "The AI nobody told you about",
]

# ---------------------------------------------------------------------------
# Emotion → power-word/style guidance for the fallback generator
# ---------------------------------------------------------------------------
_EMOTION_POWER_WORDS: dict[str, list[str]] = {
    "surprise":     ["SHOCKING", "CRAZY", "NEVER", "EVERYONE"],
    "shock":        ["SHOCKING", "BANNED", "NEVER", "CRAZY"],
    "fear":         ["NEVER", "BANNED", "SECRET", "WARNING"],
    "excitement":   ["FREE", "CRAZY", "EVERYONE", "EPIC"],
    "curiosity":    ["SECRET", "NEVER", "SHOCKING", "HIDDEN"],
    "anger":        ["THEY", "BANNED", "EVERYONE", "NEVER"],
    "inspiration":  ["FREE", "EVERYONE", "CRAZY", "SECRET"],
}

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
def _build_system_prompt(emotion: str) -> str:
    power_words = ", ".join(_EMOTION_POWER_WORDS.get(emotion, ["SECRET", "SHOCKING", "NEVER"]))
    return (
        "You are a world-class YouTube Shorts copywriter specialising in scroll-stopping hooks "
        "that achieve 90%+ retention in the first 3 seconds.\n\n"
        "Your task: write ONE single hook line for a YouTube Shorts video.\n\n"
        "STRICT RULES — violating any rule results in immediate rejection:\n"
        f"  1. Maximum 8 words. Fewer is better.\n"
        f"  2. NEVER start with: 'Today we', 'Hello', 'Welcome', 'In this video', 'Hi', 'Hey guys'.\n"
        f"  3. MUST create a strong pattern interrupt — make the viewer STOP scrolling.\n"
        f"  4. MUST match the primary emotion: '{emotion.upper()}'.\n"
        f"  5. Use at least ONE power word from this set: {power_words}.\n"
        f"  6. No hashtags, no emojis, no punctuation at the end (ellipsis '...' is allowed).\n"
        f"  7. Write in plain sentence case or ALL CAPS for impact words only.\n\n"
        "Respond with ONLY the hook text. No explanation, no quotes, no extra text."
    )


# ---------------------------------------------------------------------------
# Fallback hook generator (no LLM needed)
# ---------------------------------------------------------------------------
def _generate_fallback_hook(viral_angle_data: dict) -> str:
    """
    Constructs a hook from viral_angle_data fields without any LLM call.
    Guarantees ≤ 8 words and uses a power word.
    """
    emotion = viral_angle_data.get("emotion", "curiosity")
    hook_type = viral_angle_data.get("hook_type", "curiosity_gap")
    category = viral_angle_data.get("category", "AI")
    viral_angle = viral_angle_data.get("viral_angle", "")

    power_word = random.choice(_EMOTION_POWER_WORDS.get(emotion, ["SECRET"]))

    # Template pool keyed by hook_type
    templates: dict[str, list[str]] = {
        "curiosity_gap":   [
            f"Nobody is talking about {category.lower()} this...",
            f"The {category} {power_word.lower()} they never showed you",
            f"This {category.lower()} change is being ignored...",
        ],
        "shocking_fact":   [
            f"SHOCKING: {category} just broke everything",
            f"This {power_word.lower()} {category.lower()} fact changes everything",
            f"{power_word}: {category} is not what you think",
        ],
        "controversy":     [
            f"They BANNED this {category.lower()} secret",
            f"{category} experts are ANGRY about this",
            f"Why Big Tech fears this {category.lower()} trick",
        ],
        "secret_reveal":   [
            f"This {category.lower()} SECRET scares insiders",
            f"The {power_word.lower()} {category.lower()} secret is out",
            f"They hid this {category.lower()} from everyone",
        ],
        "challenge":       [
            f"EVERYONE failed this {category.lower()} challenge",
            f"I tried the CRAZY {category.lower()} challenge",
            f"NEVER do this {category.lower()} challenge alone",
        ],
        "countdown":       [
            f"Only 3 {category.lower()} tools you'll ever need",
            f"{power_word}: {category} ranked worst to best",
            f"Top {category.lower()} secrets nobody tells you",
        ],
    }

    choices = templates.get(hook_type, templates["curiosity_gap"])
    hook = random.choice(choices)

    # Hard trim to 8 words
    words = hook.split()
    if len(words) > 8:
        hook = " ".join(words[:8]) + "..."

    return hook


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_hook_response(raw: str) -> str:
    """Strip markdown, quotes, and extra whitespace from LLM output."""
    cleaned = raw.strip().strip('"\'`')
    # Remove markdown fences if model wrapped it
    if "```" in cleaned:
        cleaned = cleaned.replace("```", "").strip()
    # Take first line only (some models add commentary on line 2)
    cleaned = cleaned.split("\n")[0].strip()
    return cleaned


def _count_words(text: str) -> int:
    return len(text.split())


def _is_valid_hook(hook: str) -> bool:
    """Returns True if the hook passes quality rules."""
    if not hook:
        return False
    if _count_words(hook) > 8:
        return False
    banned_starts = ("today we", "hello", "welcome", "in this video", "hi ", "hey guys")
    if hook.lower().startswith(banned_starts):
        return False
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_hook(
    viral_angle_data: dict,
    model_name: str = "GPT-4o",
    custom_api_key: str = "",
) -> str:
    """
    Generates a scroll-stopping hook (≤ 8 words) based on viral_angle_data.

    Parameters
    ----------
    viral_angle_data : dict
        Output from viral_angle.extract_viral_angle() — must contain at least
        'emotion', 'hook_type', 'category', and 'viral_angle'.
    model_name : str
        Display name of the LLM to use.
    custom_api_key : str
        Optional direct API key for OpenAI or Google Gemini.

    Returns
    -------
    str
        A single hook line, ≤ 8 words, ready for use as the opening line of a Short.
    """
    emotion = viral_angle_data.get("emotion", "curiosity")
    hook_type = viral_angle_data.get("hook_type", "curiosity_gap")
    category = viral_angle_data.get("category", "AI")
    viral_angle_text = viral_angle_data.get("viral_angle", "")
    target_audience = viral_angle_data.get("target_audience", "general public")

    print(
        f"[hook_gen] Generating hook — emotion={emotion}, hook_type={hook_type}, "
        f"model={model_name}"
    )

    system_prompt = _build_system_prompt(emotion)
    user_prompt = (
        f"Category: {category}\n"
        f"Hook type: {hook_type}\n"
        f"Target audience: {target_audience}\n"
        f"Viral angle: {viral_angle_text}\n\n"
        "Write the hook now (max 8 words):"
    )

    content_str: str | None = None

    # Check if we should route to Ollama first
    is_ollama = "ollama" in model_name.lower() or any(m in model_name.lower() for m in ["shivam-pro", "deepseek", "qwen"])
    if is_ollama:
        content_str = _generate_ollama(model_name, system_prompt, user_prompt)

    # ------------------------------------------------------------------
    # 1. Try direct OpenAI API key
    # ------------------------------------------------------------------
    if not content_str and custom_api_key:
        is_openai = "GPT" in model_name or "gpt" in model_name
        is_gemini = "Gemini" in model_name or "gemini" in model_name

        if is_openai:
            print("[hook_gen] Using direct OpenAI API key...")
            try:
                headers = {
                    "Authorization": f"Bearer {custom_api_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": "gpt-4o",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "max_tokens": 50,  # hooks are short — keep it tight
                    "temperature": 0.9,
                }
                resp = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=30,
                )
                resp.raise_for_status()
                content_str = resp.json()["choices"][0]["message"]["content"]
            except Exception as ex:
                print(f"[hook_gen] Direct OpenAI failed: {ex}. Falling back...")

        elif is_gemini:
            print("[hook_gen] Using direct Google Gemini API key...")
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
                                {"text": f"{system_prompt}\n\nUser Request:\n{user_prompt}"}
                            ],
                        }
                    ],
                    "generationConfig": {"maxOutputTokens": 50, "temperature": 0.9},
                }
                resp = requests.post(url, headers=headers, json=payload, timeout=30)
                resp.raise_for_status()
                content_str = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            except Exception as ex:
                print(f"[hook_gen] Direct Gemini failed: {ex}. Falling back...")

    # ------------------------------------------------------------------
    # 2. Fall back to OpenRouter
    # ------------------------------------------------------------------
    if not content_str:
        # Check if local Ollama can be used as a smart zero-key fallback
        print("[hook_gen] Attempting local Ollama fallback before OpenRouter...")
        content_str = _generate_ollama("Ollama (deepseek-r1)", system_prompt, user_prompt)

    if not content_str:
        print("[hook_gen] Routing via OpenRouter API...")
        openrouter_model = MODEL_MAPPING.get(model_name, "google/gemini-2.5-flash")
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": openrouter_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": 50,
            "temperature": 0.9,
        }
        try:
            resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=45)
            resp.raise_for_status()
            content_str = resp.json()["choices"][0]["message"]["content"]
        except Exception as ex:
            print(f"[hook_gen] OpenRouter call failed: {ex}")

    # ------------------------------------------------------------------
    # 3. Validate LLM output
    # ------------------------------------------------------------------
    if content_str:
        hook = _clean_hook_response(content_str)
        if _is_valid_hook(hook):
            print(f"[hook_gen] LLM hook accepted ({_count_words(hook)} words): '{hook}'")
            return hook
        else:
            print(
                f"[hook_gen] LLM hook rejected (failed rules): '{hook}'. "
                "Switching to smart fallback."
            )

    # ------------------------------------------------------------------
    # 4. Smart fallback from viral_angle_data
    # ------------------------------------------------------------------
    fallback = _generate_fallback_hook(viral_angle_data)
    print(f"[hook_gen] Fallback hook: '{fallback}'")
    return fallback


# ---------------------------------------------------------------------------
# Module-level test helpers
# ---------------------------------------------------------------------------

def get_example_hooks() -> list[str]:
    """Returns the 5 built-in reference hooks for testing/display."""
    return list(EXAMPLE_HOOKS)
