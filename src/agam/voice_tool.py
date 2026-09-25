import os
import re
import hashlib
import asyncio
import edge_tts

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPEECH_DIR = os.path.join(BASE_DIR, "output", "agam_speech")
os.makedirs(SPEECH_DIR, exist_ok=True)

class VoiceToolkit:
    """
    Voice & Speech synthesis toolkit for AGAM using Edge-TTS.
    Provides natural Hindi, Hinglish, and English neural voices.
    """

    VOICES = {
        "indian_male": "hi-IN-MadhurNeural",         # Authentic Indian Male Actor (Hindi + English + Hinglish)
        "indian_male_en": "en-IN-PrabhatNeural",     # Indian English Male Actor
        "indian_female": "hi-IN-SwaraNeural",        # Authentic Indian Female Actor (Hindi + English)
        "indian_female_en": "en-IN-NeerjaNeural",    # Indian English Female Actor
        "hinglish_male": "hi-IN-MadhurNeural",       # Default for Hinglish
        "hindi_male": "hi-IN-MadhurNeural",          # Pure Hindi
        "english_jarvis": "en-IN-PrabhatNeural"      # Indian Jarvis English
    }

    @staticmethod
    def clean_text_for_speech(text: str) -> str:
        """Strips markdown, emotion tags, code blocks, URLs, emojis, and symbols so speech sounds fluid and natural."""
        # 1. Remove code blocks
        clean = re.sub(r"```.*?```", " [Code snippet] ", text, flags=re.DOTALL)
        # 2. Remove inline code
        clean = re.sub(r"`[^`]*`", "", clean)
        # 3. Remove emotion tags like [EMOTION: witty]
        clean = re.sub(r"\[EMOTION:\s*\w+\]", "", clean, flags=re.IGNORECASE)
        # 4. Remove action tags like [ACTION: ...]
        clean = re.sub(r"\[ACTION:\s*.*?\]", "", clean, flags=re.IGNORECASE)
        # 5. Remove agent tags like [AGENT_ACTIVATED: ...]
        clean = re.sub(r"\[AGENT_ACTIVATED:\s*.*?\]", "", clean, flags=re.IGNORECASE)
        # 6. Remove markdown links, bold, italics, bullets
        clean = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", clean)
        clean = re.sub(r"[*_~#]", "", clean)
        clean = re.sub(r"https?://\S+", "", clean)
        # 7. CRITICAL: Strip ALL emojis and pictographs so TTS never reads aloud emoji names
        clean = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27bf\u2b50\u2b55\u2022\u25cf\u25b2\u25bc\u26a1\u200d\ufe0f]", "", clean)
        # 8. Strip decorative symbols and bullet marks
        clean = re.sub(r"[●•★☆▲▼◆■□✓✕→←↑↓—–/\\|]", " ", clean)
        # 9. Normalize whitespace
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    @staticmethod
    def detect_best_voice(text: str, default_voice_key: str = "indian_male") -> str:
        """Determines best Indian voice actor for English and Hindi."""
        # Check for Devanagari script or Hindi phrasing
        has_devanagari = bool(re.search(r"[\u0900-\u097F]", text))
        if has_devanagari:
            return VoiceToolkit.VOICES["indian_male"]

        # Check for Hinglish colloquialisms
        hinglish_words = ["arre", "bhai", "sir", "kya", "karo", "karta", "accha", "bilkul", "haan", "nahin", "theek", "mast", "dekho", "chalo", "namaste"]
        t_lower = text.lower()
        if any(w in t_lower.split() for w in hinglish_words):
            return VoiceToolkit.VOICES["indian_male"]

        return VoiceToolkit.VOICES.get(default_voice_key, VoiceToolkit.VOICES["indian_male"])

    @staticmethod
    def generate_speech_file(text: str, voice_key: str = None) -> str:
        """
        Synthesizes speech using high-fidelity Neural Indian Voice Actor (Edge-TTS),
        fluent in English and Hindi both.
        Uses caching based on text + voice hash.
        """
        cleaned = VoiceToolkit.clean_text_for_speech(text)
        if not cleaned:
            return None

        # Truncate for audio preview if speech is excessively long
        if len(cleaned) > 500:
            cleaned = cleaned[:500] + "..."

        voice_engine = os.environ.get("AGAM_VOICE_ENGINE", "edge_tts").lower()
        openai_key = os.environ.get("OPENAI_API_KEY", "").strip()

        # If user explicitly configured openai voice engine and key is valid
        if voice_engine == "openai" and openai_key and not getattr(VoiceToolkit, '_openai_disabled', False):
            openai_voice = os.environ.get("OPENAI_VOICE", "onyx").strip()
            cache_key = hashlib.md5(f"openai_{cleaned}_{openai_voice}".encode("utf-8")).hexdigest()
            filename = f"agam_openai_{cache_key}.mp3"
            filepath = os.path.join(SPEECH_DIR, filename)

            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                return f"/api/agam/audio/{filename}"

            try:
                import requests
                headers = {
                    "Authorization": f"Bearer {openai_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": "tts-1",
                    "input": cleaned,
                    "voice": openai_voice,
                    "response_format": "mp3"
                }
                resp = requests.post("https://api.openai.com/v1/audio/speech", headers=headers, json=payload, timeout=12)
                if resp.status_code == 200 and len(resp.content) > 500:
                    with open(filepath, "wb") as f:
                        f.write(resp.content)
                    return f"/api/agam/audio/{filename}"
                elif resp.status_code in [401, 403, 429]:
                    print(f"[VoiceToolkit] OpenAI TTS quota notice ({resp.status_code}). Switching to Indian Neural Voice Actor.")
                    VoiceToolkit._openai_disabled = True
            except Exception as e:
                print(f"[VoiceToolkit] OpenAI TTS notice: {e}. Falling back to Indian Neural Voice.")

        # Primary Default: Authentic Indian Voice Actor (Edge-TTS hi-IN-MadhurNeural / en-IN-PrabhatNeural)
        chosen_voice = VoiceToolkit.VOICES.get(voice_key) if voice_key else VoiceToolkit.detect_best_voice(cleaned)
        cache_key = hashlib.md5(f"indian_{cleaned}_{chosen_voice}".encode("utf-8")).hexdigest()
        filename = f"agam_in_{cache_key}.mp3"
        filepath = os.path.join(SPEECH_DIR, filename)

        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            return f"/api/agam/audio/{filename}"

        try:
            async def _synthesize():
                communicate = edge_tts.Communicate(cleaned, chosen_voice, rate="+4%", pitch="+0Hz")
                await communicate.save(filepath)

            asyncio.run(_synthesize())

            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                return f"/api/agam/audio/{filename}"
        except Exception as e:
            print(f"[VoiceToolkit] Indian Neural Edge-TTS generation failed: {e}")

        return None
