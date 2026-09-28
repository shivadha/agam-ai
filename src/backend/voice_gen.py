import os
import re
import asyncio
import edge_tts

# Default output directory: C:\AI_project\output
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

import datetime

def format_time(time_in_100ns):
    # Convert 100-nanosecond units to milliseconds
    total_ms = time_in_100ns / 10000
    hours = int(total_ms / (1000 * 60 * 60))
    minutes = int((total_ms / (1000 * 60)) % 60)
    seconds = int((total_ms / 1000) % 60)
    milliseconds = int(total_ms % 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

async def _generate_audio_async(text: str, output_path: str, voice: str):
    communicate = edge_tts.Communicate(text, voice)
    
    boundaries = []
    
    with open(output_path, "wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] in ["SentenceBoundary", "WordBoundary"]:
                boundaries.append(chunk)
                
    # If edge-tts returns WordBoundary, use them. Otherwise, interpolate from SentenceBoundary.
    words = []
    word_boundaries = [b for b in boundaries if b["type"] == "WordBoundary"]
    
    if word_boundaries:
        words = word_boundaries
    else:
        # Interpolate from SentenceBoundary
        sentence_boundaries = [b for b in boundaries if b["type"] == "SentenceBoundary"]
        for sb in sentence_boundaries:
            offset = sb["offset"]
            duration = sb["duration"]
            sentence_text = sb["text"]
            
            sentence_words = sentence_text.split()
            if not sentence_words:
                continue
                
            total_chars = sum(len(w) for w in sentence_words)
            current_offset = offset
            
            for w in sentence_words:
                w_duration = int((len(w) / total_chars) * duration)
                words.append({
                    "offset": current_offset,
                    "duration": w_duration,
                    "text": w
                })
                current_offset += w_duration

    # Generate SRT
    srt_content = ""
    for i, w in enumerate(words):
        start_time = format_time(w["offset"])
        end_time = format_time(w["offset"] + w["duration"])
        # Some padding for spacing
        text = w["text"].strip()
        srt_content += f"{i+1}\n{start_time} --> {end_time}\n{text}\n\n"

    # Save SRT file alongside audio
    srt_path = output_path.replace(".mp3", ".srt")
    with open(srt_path, "w", encoding="utf-8") as srt_file:
        srt_file.write(srt_content)

    # ── Exact word timings (user report 2026-09-27: "subtitle and voice is
    # different"). edge-tts tells us the EXACT words it spoke with 100ns
    # offsets — write them as the <audio>.words.json cache so the pipeline
    # NEVER needs faster-whisper (which mistranscribes accented TTS and put
    # wrong words in the captions). transcribe_word_timings() picks this up
    # from the cache and skips transcription entirely.
    try:
        from .captions import timed_words_from_edge_boundaries
        exact_words = timed_words_from_edge_boundaries(boundaries)
        if exact_words:
            import json as _json
            words_path = os.path.splitext(output_path)[0] + ".words.json"
            with open(words_path, "w", encoding="utf-8") as wf:
                _json.dump(exact_words, wf)
            print(f"[VoiceGen] Saved {len(exact_words)} exact TTS word timings -> {os.path.basename(words_path)}")
    except Exception as wt_err:
        print(f"[VoiceGen] Exact word-timing note: {wt_err}")

    return output_path, srt_path


# ── Chatterbox TTS (resemble-ai/chatterbox — free, local, MIT) ──────────
CHATTERBOX_MODEL = os.environ.get("CHATTERBOX_MODEL", "").strip() or None
CHATTERBOX_BACKEND = os.environ.get("CHATTERBOX_BACKEND", "turbo").strip().lower()
CHATTERBOX_EXAGGERATION = float(os.environ.get("CHATTERBOX_EXAGGERATION", "0.6") or 0.6)
CHATTERBOX_CFG_WEIGHT = float(os.environ.get("CHATTERBOX_CFG_WEIGHT", "0.4") or 0.4)
CHATTERBOX_LANGUAGE = os.environ.get("CHATTERBOX_LANGUAGE", "en").strip() or "en"


def _chatterbox_available() -> bool:
    """True when the `chatterbox-tts` package is importable (no torch import here)."""
    import importlib.util
    return importlib.util.find_spec("chatterbox") is not None


def _chatterbox_default_ref() -> str | None:
    """Resolve the default voice-clone reference, in priority order.

    1. CHATTERBOX_REF_AUDIO env var
    2. assets/chatterbox_ref.wav (user drops ONE energetic 10–30s clip here
       and every render clones it automatically)
    """
    env_ref = os.environ.get("CHATTERBOX_REF_AUDIO", "").strip()
    if env_ref:
        return env_ref
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "..", "..", "assets", "chatterbox_ref.wav"),
        os.path.join(here, "..", "..", "assets", "chatterbox_ref.mp3"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def _parse_chatterbox_voice(voice: str) -> dict:
    """Parse the Chatterbox voice spec into a worker kwargs dict.

    Accepted forms (case-insensitive prefix):
      chatterbox | Chatterbox (Local Free)  -> turbo, clone ref from
                                              CHATTERBOX_REF_AUDIO or
                                              assets/chatterbox_ref.wav
      chatterbox:turbo                       -> Turbo 350M (default)
      chatterbox:multilingual                -> Multilingual 500M (23+ langs;
                                              CHATTERBOX_LANGUAGE / --language)
      chatterbox:clone:<ref.wav>             -> zero-shot clone of this clip
    The emotion in the reference carries into the output — clone an
    energetic, conversational clip, get energetic narration.
    """
    v = (voice or "").strip()
    low = v.lower()
    spec = {"backend": "turbo", "ref_audio": None}
    body = ""
    if low.startswith("chatterbox:"):
        body = v[len("chatterbox:"):]
    elif low.startswith("chatterbox"):
        body = ""
    else:
        body = v

    bl = body.strip().lower()
    if bl.startswith("multilingual"):
        spec["backend"] = "multilingual"
    elif bl.startswith("turbo"):
        spec["backend"] = "turbo"
    elif bl.startswith("clone:"):
        ref = body.strip()[6:].strip()
        spec["ref_audio"] = ref or None
    if not spec["ref_audio"]:
        spec["ref_audio"] = _chatterbox_default_ref()
    return spec


def _generate_audio_chatterbox(text: str, output_path: str, voice: str = "chatterbox",
                               exaggeration: float = None, cfg_weight: float = None,
                               language: str = None):
    """Generate audio via local Chatterbox (MIT, ~2–3GB VRAM, human-grade TTS).

    Runs src/backend/chatterbox_synthesize.py in a subprocess so the web app
    never imports torch; the model loads once per call and VRAM is released
    when the worker exits. Raises RuntimeError on any failure — the caller
    falls back to Edge-TTS.
    """
    import subprocess
    import sys
    import tempfile

    if not _chatterbox_available():
        raise RuntimeError(
            "Chatterbox is not installed. Run `python scripts/install_local.py` "
            "(or install_local.bat on Windows) after pulling — it installs the "
            "`chatterbox-tts` package (MIT, free).")

    spec = _parse_chatterbox_voice(voice)
    if spec["ref_audio"] and not os.path.exists(spec["ref_audio"]):
        raise RuntimeError(f"Chatterbox clone reference not found: {spec['ref_audio']}")

    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "chatterbox_synthesize.py")
    tmpdir = tempfile.mkdtemp(prefix="chatterbox_")
    text_file = os.path.join(tmpdir, "input.txt")
    wav_tmp = os.path.join(tmpdir, "out.wav")
    with open(text_file, "w", encoding="utf-8") as fh:
        fh.write(text)

    cmd = [sys.executable, helper,
           "--text-file", text_file,
           "--output", wav_tmp,
           "--backend", spec["backend"],
           "--exaggeration", str(exaggeration if exaggeration is not None
                                 else CHATTERBOX_EXAGGERATION),
           "--cfg-weight", str(cfg_weight if cfg_weight is not None
                               else CHATTERBOX_CFG_WEIGHT),
           "--language", language or CHATTERBOX_LANGUAGE]
    if CHATTERBOX_MODEL:
        cmd += ["--model", CHATTERBOX_MODEL]
    if spec["ref_audio"]:
        cmd += ["--audio-prompt", spec["ref_audio"]]

    print(f"[VoiceGen] Chatterbox local TTS ({spec['backend']}, "
          f"{'clone' if spec['ref_audio'] else 'default voice'}) — {len(text)} chars...")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1500)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Chatterbox synthesis timed out (25 min) — the model "
                           "downloads from HuggingFace on first run.")
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-600:]
        raise RuntimeError(f"Chatterbox worker failed (exit {proc.returncode}): {tail}")
    if not os.path.exists(wav_tmp) or os.path.getsize(wav_tmp) < 1024:
        raise RuntimeError("Chatterbox produced no usable audio.")

    if output_path.endswith(".mp3"):
        subprocess.run(
            ["ffmpeg", "-y", "-i", wav_tmp, "-b:a", "192k", output_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
    else:
        import shutil as _sh
        _sh.copyfile(wav_tmp, output_path)
    try:
        import shutil as _sh2
        _sh2.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass
    if not os.path.exists(output_path) or os.path.getsize(output_path) < 1024:
        raise RuntimeError("Chatterbox finished but the output file is missing/empty.")
    print(f"[VoiceGen] Chatterbox saved -> {os.path.basename(output_path)}")
    # No word-level timings from the worker; the orchestrator's
    # transcribe_word_timings() runs faster-whisper on this file automatically.
    return output_path, None


# ── Fish Audio TTS (free s2.1-pro-free tier) ──────────────────────────────
FISH_TTS_URL = "https://api.fish.audio/v1/tts"

def _fish_api_key() -> str:
    """Canonical FISH_AUDIO_KEY, with FISH_API_KEY accepted as an alias."""
    return (os.environ.get("FISH_AUDIO_KEY", "").strip()
            or os.environ.get("FISH_API_KEY", "").strip())


def _generate_audio_fish(text: str, output_path: str, voice: str = "fish", api_key: str = None):
    """Generate audio via the Fish Audio TTS API (free s2.1-pro-free model).

    `voice` may be "fish" (model default voice) or "fish:<reference_id>" to
    pin a specific Fish Audio library/cloned voice. Raises RuntimeError on
    any failure — the caller falls back to Edge-TTS so a render never dies
    because the free promo tier hiccuped.
    """
    import requests

    key = (api_key or "").strip() or _fish_api_key()
    if not key:
        raise RuntimeError("FISH_AUDIO_KEY is not set (get a free key at fish.audio → API keys)")

    reference_id = None
    m = re.search(r"fish:([A-Za-z0-9_-]{1,128})", (voice or ""), re.IGNORECASE)
    if m:
        reference_id = m.group(1)

    model = os.environ.get("FISH_AUDIO_MODEL", "s2.1-pro-free").strip() or "s2.1-pro-free"
    body = {
        "text": text,
        "format": "mp3",
        "normalize": True,
        "prosody": {"speed": 1.0, "volume": 0},
    }
    if reference_id:
        body["reference_id"] = reference_id

    # NOTE: the model rides in the `model` HTTP header, NOT the JSON body.
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "model": model,
    }
    print(f"[VoiceGen] Fish Audio TTS ({model}) — {len(text)} chars"
          + (f", voice {reference_id}" if reference_id else ", default voice") + "...")
    r = requests.post(FISH_TTS_URL, headers=headers, json=body, timeout=300)
    if r.status_code == 402:
        raise RuntimeError(
            "Fish Audio: insufficient API credit (HTTP 402). Claim the free "
            "sign-up credits at fish.audio/app/developers — API credit is "
            "separate from platform credit.")
    if r.status_code in (401, 403):
        raise RuntimeError(f"Fish Audio: API key rejected (HTTP {r.status_code}).")
    if r.status_code != 200:
        raise RuntimeError(f"Fish Audio TTS failed (HTTP {r.status_code}): {r.text[:200]}")
    if "json" in r.headers.get("Content-Type", ""):
        raise RuntimeError(f"Fish Audio returned an error payload: {r.text[:200]}")
    if len(r.content) < 1024:
        raise RuntimeError("Fish Audio returned suspiciously few bytes — treating as failure.")

    with open(output_path, "wb") as f:
        f.write(r.content)
    print(f"[VoiceGen] Fish Audio saved {len(r.content)} bytes -> {os.path.basename(output_path)}")
    # No word-level timings from Fish (raw audio bytes); the orchestrator's
    # transcribe_word_timings() runs faster-whisper on this file automatically.
    return output_path, None


OMNIVOICE_MODEL = "k2-fsa/OmniVoice"


def _omnivoice_available() -> bool:
    """True when the `omnivoice` package is importable (no torch import here)."""
    import importlib.util
    return importlib.util.find_spec("omnivoice") is not None


def _parse_omnivoice_voice(voice: str) -> dict:
    """Parse the OmniVoice voice spec into a worker kwargs dict.

    Accepted forms (case-insensitive prefix):
      omni | OmniVoice (Local Free)            -> auto voice
      omni:design:<instruct>                   -> voice design, e.g.
                                                 omni:design:female, low pitch, indian accent
      omni:clone:<ref_audio_path>              -> voice cloning from a wav file
      omni:clone:<ref_audio_path>|<ref_text>   -> ...with manual transcript
    A bare existing .wav/.mp3 path is also treated as a clone reference.
    OMNIVOICE_REF_AUDIO env var is used when the spec is bare "omni".
    """
    v = (voice or "").strip()
    low = v.lower()
    spec = {"mode": "auto", "instruct": None, "ref_audio": None, "ref_text": None}
    if low.startswith("omni:"):
        body = v[5:]
    elif low == "omni" or low.startswith("omnivoice"):
        # Bare "omni" or the UI label "OmniVoice (Local Free)" -> auto voice,
        # unless OMNIVOICE_REF_AUDIO pins a clone reference.
        body = ""
    else:
        body = v

    bl = body.strip().lower()
    if bl.startswith("design:"):
        spec["mode"] = "design"
        spec["instruct"] = body.strip()[7:].strip() or None
    elif bl.startswith("clone:"):
        spec["mode"] = "clone"
        rest = body.strip()[6:].strip()
        if "|" in rest:
            ref, ref_text = rest.split("|", 1)
            spec["ref_audio"] = ref.strip() or None
            spec["ref_text"] = ref_text.strip() or None
        else:
            spec["ref_audio"] = rest or None
    elif body.strip() and os.path.exists(body.strip()):
        spec["mode"] = "clone"
        spec["ref_audio"] = body.strip()
    elif not body.strip():
        env_ref = os.environ.get("OMNIVOICE_REF_AUDIO", "").strip()
        if env_ref:
            spec["mode"] = "clone"
            spec["ref_audio"] = env_ref
    if spec["mode"] == "design" and not spec["instruct"]:
        spec = {"mode": "auto", "instruct": None, "ref_audio": None, "ref_text": None}
    return spec


def _generate_audio_omnivoice(text: str, output_path: str, voice: str = "omni",
                              speed: float = 1.0, language: str = "English",
                              num_step: int = 32):
    """Generate audio via local OmniVoice (k2-fsa/OmniVoice — free, Apache-2.0).

    Runs src/backend/omnivoice_synthesize.py in a subprocess so the web app
    never imports torch; the model loads once per call and VRAM is released
    when the worker exits. Raises RuntimeError on any failure — the caller
    falls back to Edge-TTS.
    """
    import subprocess
    import sys
    import tempfile

    if not _omnivoice_available():
        raise RuntimeError(
            "OmniVoice is not installed. Run `python scripts/install_local.py` "
            "(or install_local.bat on Windows) after pulling — it installs the "
            "`omnivoice` package and pre-downloads the k2-fsa/OmniVoice model.")

    spec = _parse_omnivoice_voice(voice)
    if spec["mode"] == "clone" and spec["ref_audio"] and not os.path.exists(spec["ref_audio"]):
        raise RuntimeError(f"OmniVoice clone reference not found: {spec['ref_audio']}")

    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "omnivoice_synthesize.py")
    tmpdir = tempfile.mkdtemp(prefix="omnivoice_")
    text_file = os.path.join(tmpdir, "input.txt")
    wav_tmp = os.path.join(tmpdir, "out.wav")
    with open(text_file, "w", encoding="utf-8") as fh:
        fh.write(text)

    cmd = [sys.executable, helper,
           "--text-file", text_file,
           "--output", wav_tmp,
           "--model", os.environ.get("OMNIVOICE_MODEL", OMNIVOICE_MODEL),
           "--language", language or "English",
           "--speed", str(speed or 1.0),
           "--num_step", str(num_step or 32)]
    if spec["instruct"]:
        cmd += ["--instruct", spec["instruct"]]
    if spec["ref_audio"]:
        cmd += ["--ref_audio", spec["ref_audio"]]
    if spec["ref_text"]:
        cmd += ["--ref_text", spec["ref_text"]]

    print(f"[VoiceGen] OmniVoice local TTS ({spec['mode']}) — {len(text)} chars...")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1500)
    except subprocess.TimeoutExpired:
        raise RuntimeError("OmniVoice synthesis timed out (25 min) — model may still "
                           "be downloading on first run.")
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-600:]
        raise RuntimeError(f"OmniVoice worker failed (exit {proc.returncode}): {tail}")
    if not os.path.exists(wav_tmp) or os.path.getsize(wav_tmp) < 1024:
        raise RuntimeError("OmniVoice produced no usable audio.")

    if output_path.endswith(".mp3"):
        subprocess.run(
            ["ffmpeg", "-y", "-i", wav_tmp, "-b:a", "192k", output_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
    else:
        import shutil as _sh
        _sh.copyfile(wav_tmp, output_path)
    try:
        import shutil as _sh2
        _sh2.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass
    if not os.path.exists(output_path) or os.path.getsize(output_path) < 1024:
        raise RuntimeError("OmniVoice finished but the output file is missing/empty.")
    print(f"[VoiceGen] OmniVoice saved -> {os.path.basename(output_path)}")
    # No word-level timings from the worker; the orchestrator's
    # transcribe_word_timings() runs faster-whisper on this file automatically.
    return output_path, None


def _generate_audio_elevenlabs(text: str, output_path: str, voice_id: str = "21m00Tcm4TlvDq8ikWAM", api_key: str = None):
    """
    Generate audio via ElevenLabs TTS API and synthesize matching SRT subtitle timings.
    Default voice: Rachel (21m00Tcm4TlvDq8ikWAM).
    """
    import requests
    eleven_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not eleven_key:
        raise ValueError("ELEVENLABS_API_KEY is not configured.")

    # Standard ElevenLabs voice map
    voice_map = {
        "elevenlabs_rachel": "21m00Tcm4TlvDq8ikWAM",
        "elevenlabs_adam": "pNInz6obpgDQGcFmaJgB",
        "elevenlabs_antoni": "ErXwobaYiN019PkySvjV",
        "elevenlabs_bella": "EXAVITQu4vr4xnSDxMaL",
        "elevenlabs_arnold": "VR6AewLTigWG4xSOukaG",
        "rachel": "21m00Tcm4TlvDq8ikWAM",
        "adam": "pNInz6obpgDQGcFmaJgB"
    }
    actual_voice_id = voice_map.get(voice_id.lower(), voice_id)

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{actual_voice_id}"
    headers = {
        "xi-api-key": eleven_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg"
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75
        }
    }

    print(f"[VoiceGen] Calling ElevenLabs API (Voice: {actual_voice_id})...")
    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"ElevenLabs API error ({resp.status_code}): {resp.text[:200]}")

    with open(output_path, "wb") as f:
        f.write(resp.content)

    # Estimate word boundaries for SRT from total audio duration or word count
    words = text.split()
    total_words = len(words)
    # Average speaking speed: ~150 words per minute (0.4s per word)
    w_dur = 400  # ms
    srt_content = ""
    curr_ms = 0
    for i, w in enumerate(words):
        start_t = f"{int(curr_ms/3600000):02d}:{int((curr_ms%3600000)/60000):02d}:{int((curr_ms%60000)/1000):02d},{curr_ms%1000:03d}"
        end_ms = curr_ms + w_dur
        end_t = f"{int(end_ms/3600000):02d}:{int((end_ms%3600000)/60000):02d}:{int((end_ms%60000)/1000):02d},{end_ms%1000:03d}"
        srt_content += f"{i+1}\n{start_t} --> {end_t}\n{w}\n\n"
        curr_ms = end_ms

    srt_path = output_path.replace(".mp3", ".srt")
    with open(srt_path, "w", encoding="utf-8") as srt_file:
        srt_file.write(srt_content)

    return output_path, srt_path


def _generate_audio_kokoro(text: str, output_path: str, voice: str = "af_heart"):
    """
    Generate audio via local Kokoro-82M (ElevenLabs studio rival, 100% free & offline).
    Synthesizes sentence-level and phrase-level SRT subtitles.
    """
    import subprocess
    import soundfile as sf
    import numpy as np
    from kokoro import KPipeline

    voice_clean = voice.lower().replace("kokoro_", "").strip()
    voice_map = {
        "heart": "af_heart",
        "bella": "af_bella",
        "sarah": "af_sarah",
        "adam": "am_adam",
        "michael": "am_michael",
        "eric": "am_eric",
        "female": "af_heart",
        "male": "am_adam",
        "indian_female": "af_heart",
        "indian_male": "am_adam"
    }
    actual_voice = voice_map.get(voice_clean, voice_clean if voice_clean.startswith(("af_", "am_")) else "af_heart")

    print(f"[VoiceGen] Synthesizing speech with Kokoro-82M (Voice: '{actual_voice}')...")
    pipeline = KPipeline(lang_code='a', repo_id='hexgrad/Kokoro-82M')
    generator = pipeline(text, voice=actual_voice, speed=1.0)

    all_audio = []
    srt_entries = []
    cur_time = 0.0

    def fmt_srt(sec):
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int(round((sec - int(sec)) * 1000))
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    for idx, (gs, ps, audio) in enumerate(generator):
        if audio is None or len(audio) == 0:
            continue
        duration = len(audio) / 24000.0
        start_time = cur_time
        end_time = cur_time + duration
        cur_time = end_time
        all_audio.append(audio)
        clean_text = gs.strip()
        if clean_text:
            srt_entries.append(f"{len(srt_entries)+1}\n{fmt_srt(start_time)} --> {fmt_srt(end_time)}\n{clean_text}\n\n")

    if not all_audio:
        raise RuntimeError("Kokoro produced empty audio stream.")

    combined = np.concatenate(all_audio)
    
    # Save WAV or convert to target format
    wav_path = output_path if output_path.endswith(".wav") else output_path.replace(".mp3", ".wav")
    sf.write(wav_path, combined, 24000)

    # Save SRT
    srt_path = output_path.replace(".mp3", ".srt").replace(".wav", ".srt")
    with open(srt_path, "w", encoding="utf-8") as srt_file:
        srt_file.writelines(srt_entries)

    # Convert to MP3 if requested
    if output_path.endswith(".mp3"):
        subprocess.run(
            ["ffmpeg", "-y", "-i", wav_path, "-b:a", "192k", output_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        if os.path.exists(wav_path) and wav_path != output_path:
            try:
                os.remove(wav_path)
            except Exception:
                pass

    return output_path, srt_path


def _resolve_tts_provider(voice: str, provider: str) -> str:
    """Decide which TTS engine renders a request.

    Engines: kokoro | edge-tts | elevenlabs | fish | omnivoice | chatterbox.

    Edge neural voices (e.g. en-IN-PrabhatNeural) ALWAYS go to Edge-TTS —
    Kokoro can't render those voice IDs and would silently swap in af_heart,
    losing the requested accent.
    """
    v = (voice or "").lower()
    p = (provider or "auto").lower()
    if v.startswith("elevenlabs") or p == "elevenlabs":
        return "elevenlabs"
    if v.startswith("fish") or p == "fish":
        return "fish"
    if v.startswith(("omni", "omnivoice")) or p == "omnivoice":
        return "omnivoice"
    if v.startswith("chatterbox") or p == "chatterbox":
        return "chatterbox"
    if v.startswith(("af_", "am_", "kokoro")):
        return "kokoro"
    if "neural" in v:
        return "edge-tts"
    if p in ("kokoro", "default", "auto"):
        return "kokoro"
    return p  # explicit provider choice respected


def generate_audio(text: str, output_path: str = None, voice: str = "af_heart", provider: str = "kokoro", api_key: str = None,
                 speed: float = 1.0, language: str = "English"):
    """
    Generates an audio file from the given text.
    Supports:
      1. Chatterbox: Local, 100% free (resemble-ai/chatterbox, MIT) — human-grade
         voice with zero-shot cloning, prosody controls (exaggeration/cfg_weight),
         [laugh]/[chuckle] tags. PRIMARY for anti-slop narration.
      2. Kokoro-82M: Local, 100% free, ElevenLabs-quality neural voice synthesis with synced SRT.
      3. Edge-TTS: Free, ultra-fast, unlimited Microsoft neural voices.
      4. ElevenLabs: Premium voice cloning (requires ELEVENLABS_API_KEY).
      5. Fish Audio: Free s2.1-pro-free tier (requires FISH_AUDIO_KEY); any
         failure falls back to Edge-TTS automatically.
      6. OmniVoice: Local, 100% free (k2-fsa/OmniVoice, Apache-2.0) — auto
         voice, voice design ("omni:design:<instruct>") and zero-shot voice
         cloning ("omni:clone:<ref.wav>[|<ref_text>]"); any failure falls
         back to Edge-TTS automatically. Install: scripts/install_local.py.
    Saves the output to C:\\AI_project\\output\\ or the specified path.
    Returns (audio_path, srt_path).
    """
    if not text:
        print("Error: Empty text provided for audio generation.")
        return None, None

    if not output_path:
        output_path = os.path.join(OUTPUT_DIR, "audio.mp3")
    else:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # A3 — normalize into spoken form BEFORE any engine speaks: "₹10L" ->
    # "ten lakh rupees", "MBA" -> "M-B-A", no spoken asterisks. The
    # <output>.spoken.txt sidecar records the exact words spoken so the
    # assembler reconciles captions against the voice, never the raw script.
    try:
        from .tts_normalize import normalize_script_for_tts, spoken_sidecar_path
        text = normalize_script_for_tts(text)
        try:
            _sp = spoken_sidecar_path(output_path)
            with open(_sp, "w", encoding="utf-8") as _sf:
                _sf.write(text)
        except Exception:
            pass
    except Exception as _nz_err:
        print(f"[VoiceGen] TTS normalize note: {_nz_err}")

    resolved = _resolve_tts_provider(voice, provider)
    eleven_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "").strip()
    is_eleven = resolved == "elevenlabs" and bool(eleven_key)

    if is_eleven:
        try:
            print(f"[VoiceGen] Attempting ElevenLabs generation for {len(text)} chars...")
            return _generate_audio_elevenlabs(text, output_path, voice_id=voice, api_key=eleven_key)
        except Exception as e:
            print(f"[VoiceGen] ElevenLabs failed ({e}). Gracefully falling back to Kokoro-82M...")

    if resolved == "elevenlabs" and not eleven_key:
        # Asked for ElevenLabs but no key present — Edge-TTS, never a
        # silent voice swap.
        resolved = "edge-tts"

    # Fish Audio (free s2.1-pro-free tier). The free tier is promotional and
    # can 402 / rate-limit / vanish — ANY failure falls back to Edge-TTS so
    # a render never dies on it.
    if resolved == "fish":
        fish_key = (api_key or "").strip() or _fish_api_key()
        if not fish_key:
            print("[VoiceGen] Fish Audio selected but FISH_AUDIO_KEY is not set — "
                  "falling back to Edge-TTS. (Free key: fish.audio → API keys)")
            resolved = "edge-tts"
        else:
            try:
                return _generate_audio_fish(text, output_path, voice=voice, api_key=fish_key)
            except Exception as fe:
                print(f"[VoiceGen] Fish Audio failed ({fe}). Falling back to Edge-TTS...")
                resolved = "edge-tts"

    # OmniVoice (local, free, Apache-2.0). The worker runs in a subprocess so
    # the web app never imports torch; VRAM is released when it exits. ANY
    # failure falls back to Edge-TTS so a render never dies on it.
    if resolved == "omnivoice":
        try:
            return _generate_audio_omnivoice(text, output_path, voice=voice,
                                             speed=speed, language=language)
        except Exception as oe:
            print(f"[VoiceGen] OmniVoice failed ({oe}). Falling back to Edge-TTS...")
            resolved = "edge-tts"

    # Chatterbox (local, free, MIT — the human-grade primary voice). The
    # worker runs in a subprocess so the web app never imports torch; VRAM is
    # released when it exits. ANY failure falls back to Edge-TTS so a render
    # never dies on it.
    if resolved == "chatterbox":
        try:
            return _generate_audio_chatterbox(text, output_path, voice=voice)
        except Exception as ce:
            print(f"[VoiceGen] Chatterbox failed ({ce}). Falling back to Edge-TTS...")
            resolved = "edge-tts"

    # Primary recommendation: Kokoro-82M (ElevenLabs quality, 100% free local)
    is_kokoro = resolved == "kokoro"
    if is_kokoro:
        try:
            return _generate_audio_kokoro(text, output_path, voice=voice)
        except Exception as ke:
            print(f"[VoiceGen] Kokoro-82M failed ({ke}). Gracefully falling back to Edge-TTS neural voice...")

    # Fallback / Default: Edge-TTS
    # Local voice labels must never leak into Edge's voice field — when the
    # resolved provider fell back, pick a real neural voice instead.
    _local_prefixes = ("elevenlabs", "af_", "am_", "kokoro", "omni", "omnivoice",
                       "chatterbox", "fish")
    fallback_voice = (voice if not voice.lower().startswith(_local_prefixes)
                      else "en-IN-PrabhatNeural")
    print(f"[VoiceGen] Generating audio with Edge-TTS voice '{fallback_voice}' to {output_path}...")
    try:
        audio_p, vtt_p = asyncio.run(_generate_audio_async(text, output_path, fallback_voice))
        print(f"[VoiceGen] Successfully generated audio: {audio_p} and subtitles: {vtt_p}")
        return audio_p, vtt_p
    except Exception as e:
        print(f"[VoiceGen] Error generating audio with edge-tts: {e}")
        return None, None


def generate_music_huggingface(prompt: str, output_path: str = None) -> str:
    """
    Generates royalty-free background music via HuggingFace facebook/MusicGen Space.
    100% Free, runs on Hugging Face cloud GPUs using HF_TOKEN.
    """
    import shutil
    import time
    from gradio_client import Client

    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    if not output_path:
        output_path = os.path.join(OUTPUT_DIR, f"music_{int(time.time())}.wav")

    try:
        print(f"[MusicGen] Generating background music for: '{prompt}' via HuggingFace Space...")
        client = Client("facebook/MusicGen", token=token)
        res = client.predict(
            texts=prompt[:200],
            melodies=None,
            api_name="/predict_batched"
        )
        if res and os.path.exists(res):
            shutil.copyfile(res, output_path)
            print(f"[MusicGen] OK: Background music saved to {output_path}")
            return output_path
    except Exception as e:
        print(f"[MusicGen] HuggingFace MusicGen note: {e}")
    return None


if __name__ == "__main__":
    # Test execution
    test_text = "Hello! This is a test of the Edge, Kokoro, and HuggingFace voice implementation."
    test_output = os.path.join(OUTPUT_DIR, "test_audio.mp3")
    generate_audio(test_text, test_output)

