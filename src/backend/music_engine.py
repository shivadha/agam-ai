"""
music_engine.py
---------------
Manages viral background music for YouTube Shorts.

Downloads a curated set of royalty-free tracks from Pixabay (direct MP3 URLs),
organises them into mood categories, and mixes them onto voice audio using ffmpeg.
"""

from __future__ import annotations

import logging
import math
import os
import random
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)

# ---------------------------------------------------------------------------
# Music catalog  (royalty-free Pixabay direct MP3 links)
# ---------------------------------------------------------------------------
MUSIC_CATALOG: dict[str, list[str]] = {
    "futuristic": [
        "https://cdn.pixabay.com/audio/2024/11/12/audio_c1e8f63f5e.mp3",
        "https://cdn.pixabay.com/audio/2024/08/20/audio_d5e4c3b2a1.mp3",
    ],
    "suspense": [
        "https://cdn.pixabay.com/audio/2023/10/30/audio_9b8a7c6d5e.mp3",
        "https://cdn.pixabay.com/audio/2024/01/15/audio_4f3e2d1c0b.mp3",
    ],
    "energetic": [
        "https://cdn.pixabay.com/audio/2024/03/22/audio_7a6b5c4d3e.mp3",
        "https://cdn.pixabay.com/audio/2024/06/10/audio_2f1e0d9c8b.mp3",
    ],
    "upbeat": [
        "https://cdn.pixabay.com/audio/2024/09/05/audio_5d4c3b2a1f.mp3",
        "https://cdn.pixabay.com/audio/2024/12/01/audio_8e7f6a5b4c.mp3",
    ],
    "dramatic": [
        "https://cdn.pixabay.com/audio/2024/02/28/audio_1c0b9a8f7e.mp3",
        "https://cdn.pixabay.com/audio/2024/07/14/audio_6e5d4c3b2a.mp3",
    ],
}

# ---------------------------------------------------------------------------
# Emotion → mood mapping
# ---------------------------------------------------------------------------
EMOTION_TO_MOOD: dict[str, str] = {
    "surprise": "futuristic",
    "shock": "dramatic",
    "fear": "suspense",
    "excitement": "energetic",
    "curiosity": "futuristic",
    "anger": "dramatic",
    "inspiration": "upbeat",
}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_DEFAULT_ASSETS_DIR = r"C:\AI_project\assets\music"

# Browser-like User-Agent to avoid 403s on CDN endpoints
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_DOWNLOAD_TIMEOUT_SECS = 30


def _local_filename(mood: str, url: str) -> str:
    """Derive a deterministic local filename from mood + URL tail."""
    tail = url.rstrip("/").rsplit("/", 1)[-1]  # e.g. audio_c1e8f63f5e.mp3
    return f"{mood}_{tail}"


def _download_track(url: str, dest_path: Path) -> bool:
    """
    Attempt to download *url* to *dest_path*.

    Returns True on success, False on any failure (404, timeout, etc.).
    Does NOT raise.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT_SECS) as resp:
            if resp.status != 200:
                logger.warning("HTTP %s for %s – skipping.", resp.status, url)
                return False
            data = resp.read()
        dest_path.write_bytes(data)
        logger.info("Downloaded %s → %s (%d KB)", url, dest_path, len(data) // 1024)
        return True
    except urllib.error.HTTPError as exc:
        logger.warning("HTTP error %s downloading %s – skipping.", exc.code, url)
    except urllib.error.URLError as exc:
        logger.warning("URL error downloading %s: %s – skipping.", url, exc.reason)
    except OSError as exc:
        logger.warning("IO error saving %s: %s – skipping.", dest_path, exc)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Unexpected error downloading %s: %s – skipping.", url, exc)
    return False


def _ffmpeg_available() -> bool:
    """Return True if ffmpeg is on PATH and responds to --version."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _get_audio_duration(path: str) -> Optional[float]:
    """
    Use ffprobe to get audio duration in seconds.
    Returns None if ffprobe is unavailable or the file is unreadable.
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
        )
        if result.returncode == 0:
            return float(result.stdout.decode().strip())
    except Exception:  # pylint: disable=broad-except
        pass
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ensure_music_assets(assets_dir: str = _DEFAULT_ASSETS_DIR) -> dict[str, list[str]]:
    """
    Download all missing tracks from MUSIC_CATALOG.

    Only fetches files that do not already exist locally, so repeated calls
    are cheap.  If a URL fails (404, network error, etc.) it is silently
    skipped and the rest of the catalog is still processed.

    Returns
    -------
    dict[str, list[str]]
        Mapping of ``{mood: [absolute_local_paths]}`` for every track that
        is successfully present on disk (pre-existing or freshly downloaded).
    """
    root = Path(assets_dir)
    result: dict[str, list[str]] = {mood: [] for mood in MUSIC_CATALOG}

    for mood, urls in MUSIC_CATALOG.items():
        mood_dir = root / mood
        mood_dir.mkdir(parents=True, exist_ok=True)

        for url in urls:
            filename = _local_filename(mood, url)
            dest = mood_dir / filename

            if dest.exists() and dest.stat().st_size > 0:
                logger.info("Already present: %s", dest)
                result[mood].append(str(dest))
                continue

            success = _download_track(url, dest)
            if success:
                result[mood].append(str(dest))
            else:
                # Clean up any zero-byte partial file
                if dest.exists() and dest.stat().st_size == 0:
                    try:
                        dest.unlink()
                    except OSError:
                        pass

    # Log a summary
    total_ok = sum(len(v) for v in result.values())
    total_wanted = sum(len(v) for v in MUSIC_CATALOG.values())
    logger.info(
        "Music assets ready: %d / %d tracks across %d moods.",
        total_ok,
        total_wanted,
        len(MUSIC_CATALOG),
    )
    return result


def get_music_for_emotion(
    emotion: str,
    assets_dir: str = _DEFAULT_ASSETS_DIR,
) -> Optional[str]:
    """
    Return the path to a random local music file matching *emotion*.

    The mood is resolved via EMOTION_TO_MOOD.  Any missing track for that
    mood is downloaded on demand.  If no tracks are available (all downloads
    failed), returns None.

    Parameters
    ----------
    emotion:
        One of the keys in EMOTION_TO_MOOD (case-insensitive).  Unknown
        emotions fall back to the 'upbeat' mood.
    assets_dir:
        Root directory where music files are stored.

    Returns
    -------
    str | None
        Absolute path to a local MP3 file, or None if unavailable.
    """
    emotion_lower = emotion.lower().strip()
    mood = EMOTION_TO_MOOD.get(emotion_lower, "upbeat")
    logger.info("Emotion '%s' mapped to mood '%s'.", emotion, mood)

    root = Path(assets_dir)
    mood_dir = root / mood
    mood_dir.mkdir(parents=True, exist_ok=True)

    # Collect tracks already on disk for this mood
    existing: list[Path] = [
        p for p in mood_dir.glob("*.mp3") if p.stat().st_size > 0
    ]

    if existing:
        chosen = random.choice(existing)
        logger.info("Returning existing track: %s", chosen)
        return str(chosen)

    # Nothing on disk – attempt download for this mood only
    logger.info("No cached tracks for mood '%s' – downloading now…", mood)
    urls = MUSIC_CATALOG.get(mood, [])
    for url in urls:
        filename = _local_filename(mood, url)
        dest = mood_dir / filename
        if _download_track(url, dest):
            return str(dest)

    logger.warning(
        "No tracks available for mood '%s' (emotion '%s').", mood, emotion
    )
    return None


def apply_music_to_video(
    audio_track_path: str,
    music_path: str,
    output_path: str,
    voice_volume: float = 1.0,
    music_volume: float = 0.18,
    fade_in: float = 1.0,
    fade_out: float = 2.0,
) -> str:
    """
    Mix a voice audio track with background music using ffmpeg.

    The output is written as an MP3 file at *output_path*.  The music is
    trimmed / looped to match the voice duration, with the specified fade-in
    and fade-out applied to the music layer only.

    Parameters
    ----------
    audio_track_path:
        Path to the primary voice/narration audio file (MP3 or WAV).
    music_path:
        Path to the background music file (MP3 or WAV).
    output_path:
        Destination path for the mixed output (should end in .mp3).
    voice_volume:
        Amplitude multiplier for the voice track (default 1.0 = 100 %).
    music_volume:
        Amplitude multiplier for the music track (default 0.18 = 18 %).
    fade_in:
        Duration in seconds for the music fade-in at the start.
    fade_out:
        Duration in seconds for the music fade-out at the end.

    Returns
    -------
    str
        The path to the output file.  If ffmpeg is not installed or the mix
        fails, returns *audio_track_path* unchanged (safe fallback).
    """
    if not os.path.isfile(audio_track_path):
        logger.error("Voice track not found: %s", audio_track_path)
        return audio_track_path

    if not os.path.isfile(music_path):
        logger.warning("Music track not found: %s – returning voice only.", music_path)
        return audio_track_path

    if not _ffmpeg_available():
        logger.warning(
            "ffmpeg not found on PATH – returning voice track unchanged: %s",
            audio_track_path,
        )
        return audio_track_path

    # Ensure output directory exists
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # Determine voice duration so we can trim music to match
    voice_duration = _get_audio_duration(audio_track_path)
    if voice_duration is None:
        logger.warning("Could not determine voice duration; music will not be trimmed.")
        voice_duration = 0.0  # ffmpeg will decide

    # Build the ffmpeg filter-graph:
    #
    #  [0:a] → volume=voice_volume → [va]
    #  [1:a] → atrim=0:duration,aloop=-1:size,
    #           volume=music_volume,
    #           afade=in:st=0:d=fade_in,
    #           afade=out:st=(dur-fade_out):d=fade_out → [ma]
    #  [va][ma] → amix=inputs=2:duration=first → out
    #
    # Using `duration=first` ensures output length equals the voice track.

    fade_out_start = max(0.0, voice_duration - fade_out) if voice_duration > 0 else 0.0

    music_chain_parts = [
        f"atrim=0:{voice_duration}" if voice_duration > 0 else "anull",
        "aloop=loop=-1:size=2e+09",           # loop music to cover full duration
        f"volume={music_volume:.4f}",
        f"afade=t=in:st=0:d={fade_in:.3f}",
    ]
    if fade_out_start > 0:
        music_chain_parts.append(
            f"afade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f}"
        )

    music_filter = ",".join(music_chain_parts)

    filter_complex = (
        f"[0:a]volume={voice_volume:.4f}[va];"
        f"[1:a]{music_filter}[ma];"
        f"[va][ma]amix=inputs=2:duration=first:dropout_transition=0[out]"
    )

    cmd = [
        "ffmpeg",
        "-y",                          # overwrite output without asking
        "-i", audio_track_path,        # input 0: voice
        "-i", music_path,              # input 1: music
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:a", "libmp3lame",
        "-q:a", "2",                   # VBR ~190 kbps – good quality
        output_path,
    ]

    logger.info("Running ffmpeg mix command: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )

        if result.returncode == 0:
            logger.info("Mix complete → %s", output_path)
            return output_path
        else:
            stderr_text = result.stderr.decode(errors="replace")
            logger.error(
                "ffmpeg exited with code %d.\nstderr:\n%s",
                result.returncode,
                stderr_text[-2000:],  # last 2 KB to avoid log flooding
            )
            logger.warning("Falling back to voice-only track: %s", audio_track_path)
            return audio_track_path

    except subprocess.TimeoutExpired:
        logger.error("ffmpeg timed out after 120 s – returning voice track.")
        return audio_track_path
    except (FileNotFoundError, OSError) as exc:
        logger.error("Could not run ffmpeg: %s – returning voice track.", exc)
        return audio_track_path
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Unexpected ffmpeg error: %s – returning voice track.", exc)
        return audio_track_path


# ---------------------------------------------------------------------------
# Quick smoke-test (python -m src.backend.music_engine)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    print("=== music_engine smoke test ===")
    print("\n[1] ensure_music_assets()")
    catalog = ensure_music_assets()
    for mood, paths in catalog.items():
        status = f"{len(paths)} track(s) on disk" if paths else "no tracks downloaded"
        print(f"  {mood:12s}: {status}")

    print("\n[2] get_music_for_emotion('excitement')")
    track = get_music_for_emotion("excitement")
    print(f"  → {track!r}")

    print("\n[3] get_music_for_emotion('unknown_emotion')")
    track = get_music_for_emotion("unknown_emotion")
    print(f"  → {track!r}")

    print("\n[4] ffmpeg available:", _ffmpeg_available())
    print("\nDone.")
    sys.exit(0)
