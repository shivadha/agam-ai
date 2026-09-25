"""
AGAM — Translation + Hindi dubbing (English stays the primary audio).

Pipeline:
  1. translate node  -> translates scene narrations via the free Google
     Translate endpoint (no key) with LLM fallback; stores `narration_hi`.
  2. tts node        -> optional `hindi_dub` toggle generates a Hindi
     voiceover with Edge-TTS (hi-IN-SwaraNeural, free & unlimited).
  3. video-assembler -> muxes the Hindi voiceover as a SECOND audio track
     (English default track first). YouTube surfaces multi-track audio as
     "Audio track" language options — the professional way to do dubs.

Everything is best-effort: dubbing never fails the render.
"""

import os
import subprocess

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "output")

LANG_CODES = {
    "hindi": "hi", "spanish": "es", "french": "fr", "german": "de",
    "japanese": "ja", "portuguese": "pt", "tamil": "ta", "telugu": "te",
}

HINDI_VOICES = ["hi-IN-SwaraNeural", "hi-IN-MadhurNeural"]


def _ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def translate_text(text, target="hi", source="en"):
    """Translate via the free Google Translate endpoint (no key). Chunked."""
    if not text or not text.strip():
        return text
    import requests

    target = LANG_CODES.get((target or "hi").lower(), target or "hi")
    chunks, out = [], []
    # Keep chunks small; the endpoint handles ~5k chars but smaller is safer.
    words, cur = text.split(), ""
    for w in words:
        if len(cur) + len(w) + 1 > 1500:
            chunks.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        chunks.append(cur)

    for ch in chunks:
        try:
            r = requests.get(
                "https://translate.googleapis.com/translate_a/single",
                params={"client": "gtx", "sl": source, "tl": target, "dt": "t", "q": ch},
                timeout=25,
            )
            r.raise_for_status()
            data = r.json()
            out.append("".join(seg[0] for seg in data[0] if seg and seg[0]))
        except Exception as e:
            print(f"[dubbing] translate chunk failed ({e}) — keeping original text.")
            out.append(ch)
    return " ".join(out)


def translate_scenes(scenes, target="hi"):
    """Add `narration_<lang>` to each scene. Returns the scenes list."""
    code = LANG_CODES.get((target or "hindi").lower(), "hi")
    key = f"narration_{code}"
    for sc in scenes or []:
        narration = sc.get("narration") or ""
        if narration and not sc.get(key):
            try:
                sc[key] = translate_text(narration, target=code)
            except Exception as e:
                print(f"[dubbing] scene translation note: {e}")
                sc[key] = narration
    return scenes


def generate_hindi_voiceover(text_hi, output_path, voice=None):
    """Render Hindi TTS via Edge-TTS (free, unlimited). Returns path or None."""
    import asyncio
    import edge_tts

    voice = voice or HINDI_VOICES[0]
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    async def _run():
        communicate = edge_tts.Communicate(text_hi, voice)
        with open(output_path, "wb") as f:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])

    try:
        asyncio.run(_run())
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            print(f"[dubbing] Hindi voiceover saved -> {output_path}")
            return output_path
    except Exception as e:
        print(f"[dubbing] Hindi TTS failed ({e})")
    return None


def mux_second_audio_track(video_path, hindi_audio_path, output_path=None):
    """Mux Hindi as 2nd audio track (English stays default track 0).

    Returns the new video path, or None on failure (original kept).
    """
    if not (video_path and os.path.exists(video_path)
            and hindi_audio_path and os.path.exists(hindi_audio_path)):
        return None
    if output_path is None:
        base, ext = os.path.splitext(video_path)
        output_path = f"{base}_dual-audio{ext}"

    cmd = [
        _ffmpeg_exe(), "-y",
        "-i", video_path,
        "-i", hindi_audio_path,
        "-map", "0:v:0", "-map", "0:a:0", "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "160k",
        "-metadata:s:a:0", "language=eng", "-metadata:s:a:0", "title=English",
        "-metadata:s:a:1", "language=hin", "-metadata:s:a:1", "title=Hindi",
        "-disposition:a:0", "default", "-disposition:a:1", "0",
        "-shortest",
        output_path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode == 0 and os.path.exists(output_path):
            print(f"[dubbing] Dual-audio video saved -> {output_path}")
            return output_path
        print(f"[dubbing] ffmpeg mux failed: {proc.stderr[-500:]}")
    except Exception as e:
        print(f"[dubbing] mux error: {e}")
    return None
