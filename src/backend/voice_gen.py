import os
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
        
        
    return output_path, srt_path


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


def generate_audio(text: str, output_path: str = None, voice: str = "af_heart", provider: str = "kokoro", api_key: str = None):
    """
    Generates an audio file from the given text.
    Supports:
      1. Kokoro-82M: Local, 100% free, ElevenLabs-quality neural voice synthesis with synced SRT.
      2. Edge-TTS: Free, ultra-fast, unlimited Microsoft neural voices.
      3. ElevenLabs: Premium voice cloning (requires ELEVENLABS_API_KEY).
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

    eleven_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "").strip()
    is_eleven = (provider == "elevenlabs" or voice.lower().startswith("elevenlabs")) and bool(eleven_key)

    if is_eleven:
        try:
            print(f"[VoiceGen] Attempting ElevenLabs generation for {len(text)} chars...")
            return _generate_audio_elevenlabs(text, output_path, voice_id=voice, api_key=eleven_key)
        except Exception as e:
            print(f"[VoiceGen] ElevenLabs failed ({e}). Gracefully falling back to Kokoro-82M...")

    # Primary recommendation: Kokoro-82M (ElevenLabs quality, 100% free local)
    is_kokoro = (provider in ["kokoro", "auto", "default"]) or voice.lower().startswith(("af_", "am_", "kokoro"))
    if is_kokoro:
        try:
            return _generate_audio_kokoro(text, output_path, voice=voice)
        except Exception as ke:
            print(f"[VoiceGen] Kokoro-82M failed ({ke}). Gracefully falling back to Edge-TTS neural voice...")

    # Fallback / Default: Edge-TTS
    fallback_voice = voice if not voice.lower().startswith(("elevenlabs", "af_", "am_", "kokoro")) else "en-US-ChristopherNeural"
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

