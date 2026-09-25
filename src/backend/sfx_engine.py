"""
sfx_engine.py
-------------
Generates and manages sound effects (SFX) for YouTube Shorts videos.

All SFX are synthesised procedurally using only Python's built-in ``wave``
and ``math`` modules – no external audio libraries required.

Generated files
---------------
  pop.wav     – text pop:   fast sine burst at 800 Hz, 0.08 s
  whoosh.wav  – transition: frequency sweep 200→2000 Hz over 0.5 s
  impact.wav  – hit:        sub-bass thud at 60 Hz, exponential decay 0.6 s
  rise.wav    – reveal:     ascending sine 200→1200 Hz over 1.0 s
  glitch.wav  – glitch:     random noise bursts, 0.3 s total
  chime.wav   – success:    pure sine at 1047 Hz (C6), 0.4 s decay
"""

from __future__ import annotations

import logging
import math
import os
import random
import struct
import wave
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
# Constants
# ---------------------------------------------------------------------------
_DEFAULT_ASSETS_DIR = r"C:\AI_project\assets\sfx"
_SAMPLE_RATE = 44100          # Hz
_NUM_CHANNELS = 1             # mono
_SAMPLE_WIDTH = 2             # bytes (16-bit PCM)
_MAX_AMPLITUDE = 32767        # 2^15 - 1

# Minimum gap (seconds) between SFX events on a timeline
_MIN_SFX_INTERVAL = 2.0

# ---------------------------------------------------------------------------
# Waveform utilities
# ---------------------------------------------------------------------------


def _clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _to_pcm_bytes(samples: list[float]) -> bytes:
    """Convert normalised float samples (−1.0 … 1.0) to 16-bit PCM bytes."""
    return struct.pack(f"<{len(samples)}h", *[
        int(_clamp(s) * _MAX_AMPLITUDE) for s in samples
    ])


def _write_wav(path: Path, samples: list[float], sample_rate: int = _SAMPLE_RATE) -> None:
    """Write a list of float samples to *path* as a 16-bit mono WAV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = _to_pcm_bytes(samples)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(_NUM_CHANNELS)
        wf.setsampwidth(_SAMPLE_WIDTH)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    logger.info("SFX written: %s  (%d samples, %.3f s)", path, len(samples), len(samples) / sample_rate)


# ---------------------------------------------------------------------------
# SFX synthesisers
# ---------------------------------------------------------------------------


def _gen_pop(sr: int = _SAMPLE_RATE) -> list[float]:
    """
    pop.wav – fast sine burst at 800 Hz, 0.08 s duration.
    Attack: first 10 % of samples ramp up; decay: remaining 90 % ramp down.
    """
    duration = 0.08
    freq = 800.0
    n = int(sr * duration)
    attack_end = int(n * 0.10)
    samples: list[float] = []
    for i in range(n):
        # envelope
        if i < attack_end:
            env = i / attack_end                          # fast attack
        else:
            env = 1.0 - (i - attack_end) / (n - attack_end)  # decay to 0
        sine = math.sin(2 * math.pi * freq * i / sr)
        samples.append(env * sine * 0.85)
    return samples


def _gen_whoosh(sr: int = _SAMPLE_RATE) -> list[float]:
    """
    whoosh.wav – frequency sweep 200→2000 Hz over 0.5 s.
    Envelope: ramp up first 20 %, sustain, ramp down last 20 %.
    """
    duration = 0.5
    freq_start = 200.0
    freq_end = 2000.0
    n = int(sr * duration)
    attack_samples = int(n * 0.20)
    release_samples = int(n * 0.20)
    phase = 0.0
    samples: list[float] = []
    for i in range(n):
        t = i / n                                    # 0 → 1
        freq = freq_start + (freq_end - freq_start) * t  # linear sweep

        if i < attack_samples:
            env = i / attack_samples
        elif i >= n - release_samples:
            env = (n - i) / release_samples
        else:
            env = 1.0

        sine = math.sin(phase)
        samples.append(env * sine * 0.75)
        phase += 2 * math.pi * freq / sr

    return samples


def _gen_impact(sr: int = _SAMPLE_RATE) -> list[float]:
    """
    impact.wav – sub-bass thud at 60 Hz, exponential decay over 0.6 s.
    A short click transient at t=0 is blended in for punch.
    """
    duration = 0.6
    freq = 60.0
    decay = 8.0     # exponential decay coefficient
    n = int(sr * duration)
    samples: list[float] = []
    for i in range(n):
        t = i / sr
        env = math.exp(-decay * t)
        sine = math.sin(2 * math.pi * freq * t)
        # Add a short transient click in the first 3 ms
        click = math.exp(-500 * t) * (1.0 if t < 0.003 else 0.0)
        samples.append((env * sine + click * 0.4) * 0.90)
    return samples


def _gen_rise(sr: int = _SAMPLE_RATE) -> list[float]:
    """
    rise.wav – ascending sine from 200→1200 Hz over 1.0 s.
    Soft bell-shaped envelope (sin²).
    """
    duration = 1.0
    freq_start = 200.0
    freq_end = 1200.0
    n = int(sr * duration)
    phase = 0.0
    samples: list[float] = []
    for i in range(n):
        t = i / n                                          # 0 → 1
        freq = freq_start + (freq_end - freq_start) * (t ** 1.5)  # accelerating sweep
        env = math.sin(math.pi * t) ** 2                  # smooth bell shape
        sine = math.sin(phase)
        samples.append(env * sine * 0.70)
        phase += 2 * math.pi * freq / sr

    return samples


def _gen_glitch(sr: int = _SAMPLE_RATE) -> list[float]:
    """
    glitch.wav – random noise bursts, 0.3 s total.
    Alternating short bursts of band-limited noise and silence.
    """
    duration = 0.3
    n = int(sr * duration)
    # burst rhythm: 15 ms burst / 10 ms silence
    burst_len = int(sr * 0.015)
    gap_len = int(sr * 0.010)
    cycle = burst_len + gap_len

    samples: list[float] = []
    rng = random.Random(42)          # deterministic seed for reproducibility

    for i in range(n):
        pos_in_cycle = i % cycle
        if pos_in_cycle < burst_len:
            # white noise, amplitude shaped by triangular envelope within burst
            t_burst = pos_in_cycle / burst_len
            env = 1.0 - abs(2 * t_burst - 1.0)   # triangle 0→1→0
            noise = rng.uniform(-1.0, 1.0)
            samples.append(env * noise * 0.65)
        else:
            samples.append(0.0)

    return samples


def _gen_chime(sr: int = _SAMPLE_RATE) -> list[float]:
    """
    chime.wav – pure sine at 1047 Hz (C6), 0.4 s, exponential decay.
    A slight second harmonic (2094 Hz) is added for warmth.
    """
    duration = 0.4
    freq_fundamental = 1047.0
    freq_harmonic = freq_fundamental * 2.0
    decay = 6.0
    n = int(sr * duration)
    samples: list[float] = []
    for i in range(n):
        t = i / sr
        env = math.exp(-decay * t)
        fundamental = math.sin(2 * math.pi * freq_fundamental * t)
        harmonic = math.sin(2 * math.pi * freq_harmonic * t) * 0.25
        samples.append(env * (fundamental + harmonic) * 0.80)
    return samples


# ---------------------------------------------------------------------------
# SFX registry  (name → generator function)
# ---------------------------------------------------------------------------

_SFX_GENERATORS: dict[str, callable] = {
    "pop":    _gen_pop,
    "whoosh": _gen_whoosh,
    "impact": _gen_impact,
    "rise":   _gen_rise,
    "glitch": _gen_glitch,
    "chime":  _gen_chime,
}

# Default volumes used when building timelines
_SFX_DEFAULT_VOLUMES: dict[str, float] = {
    "pop":    0.70,
    "whoosh": 0.65,
    "impact": 0.85,
    "rise":   0.60,
    "glitch": 0.55,
    "chime":  0.75,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ensure_sfx_assets(assets_dir: str = _DEFAULT_ASSETS_DIR) -> dict[str, str]:
    """
    Generate all missing SFX WAV files and return a mapping of
    ``{sfx_name: absolute_path}``.

    Files are generated once and reused on subsequent calls (no re-synthesis
    if the file already exists and is non-empty).

    Parameters
    ----------
    assets_dir:
        Directory where SFX WAV files will be stored.

    Returns
    -------
    dict[str, str]
        ``{'pop': '/path/pop.wav', 'whoosh': '/path/whoosh.wav', ...}``
    """
    root = Path(assets_dir)
    root.mkdir(parents=True, exist_ok=True)
    result: dict[str, str] = {}

    for name, generator in _SFX_GENERATORS.items():
        dest = root / f"{name}.wav"

        if dest.exists() and dest.stat().st_size > 0:
            logger.info("SFX already present: %s", dest)
            result[name] = str(dest)
            continue

        try:
            samples = generator(_SAMPLE_RATE)
            _write_wav(dest, samples)
            result[name] = str(dest)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Failed to generate SFX '%s': %s", name, exc)
            # Leave it out of the result dict so callers know it's unavailable

    logger.info(
        "SFX assets ready: %d / %d effects.",
        len(result),
        len(_SFX_GENERATORS),
    )
    return result


def get_sfx_path(
    sfx_name: str,
    assets_dir: str = _DEFAULT_ASSETS_DIR,
) -> Optional[str]:
    """
    Return the absolute path to a named SFX WAV file.

    If the file does not exist it is synthesised on the fly.  Returns None
    only if synthesis itself fails.

    Parameters
    ----------
    sfx_name:
        One of: 'pop', 'whoosh', 'impact', 'rise', 'glitch', 'chime'.
        Name is matched case-insensitively.
    assets_dir:
        Directory where SFX WAV files are stored.

    Returns
    -------
    str | None
        Absolute path to the WAV file, or None on failure.
    """
    name = sfx_name.lower().strip()

    if name not in _SFX_GENERATORS:
        logger.warning(
            "Unknown SFX name '%s'. Valid names: %s",
            sfx_name,
            ", ".join(sorted(_SFX_GENERATORS)),
        )
        return None

    root = Path(assets_dir)
    dest = root / f"{name}.wav"

    if dest.exists() and dest.stat().st_size > 0:
        return str(dest)

    # Synthesise on demand
    root.mkdir(parents=True, exist_ok=True)
    try:
        samples = _SFX_GENERATORS[name](_SAMPLE_RATE)
        _write_wav(dest, samples)
        return str(dest)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Failed to synthesise SFX '%s': %s", name, exc)
        return None


def build_sfx_timeline(
    scenes: list[dict],
    total_duration: float,
) -> list[dict]:
    """
    Build an ordered SFX timeline from a list of scene descriptors.

    Each entry in *scenes* may contain an ``'sfx'`` key with a string (single
    SFX name) or a list of SFX names, plus a ``'start_time'`` float indicating
    when the scene begins.

    A hard rule of **at most one SFX per 2 seconds** is enforced: if two
    events would fall within 2 s of each other, the later one is dropped.

    Parameters
    ----------
    scenes:
        List of scene dicts.  Expected structure::

            [
                {'start_time': 0.0, 'sfx': 'pop', ...},
                {'start_time': 2.5, 'sfx': ['whoosh', 'rise'], ...},
                ...
            ]

        ``'start_time'`` defaults to 0.0 if absent.
        ``'sfx'`` may be absent, None, an empty string, or a list.

    total_duration:
        Total video duration in seconds.  SFX events beyond this timestamp
        are excluded.

    Returns
    -------
    list[dict]
        Ordered list of SFX events::

            [
                {'time': 0.0,  'path': '/path/pop.wav',    'volume': 0.70},
                {'time': 2.5,  'path': '/path/whoosh.wav', 'volume': 0.65},
                ...
            ]
    """
    events: list[tuple[float, str]] = []   # (time, sfx_name)

    for scene in scenes:
        raw_start = scene.get("start_time", 0.0)
        try:
            start_time = float(raw_start)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid start_time '%s' in scene – defaulting to 0.0.", raw_start
            )
            start_time = 0.0

        sfx_field = scene.get("sfx")
        if not sfx_field:
            continue

        # Normalise to list
        if isinstance(sfx_field, str):
            sfx_names = [sfx_field]
        elif isinstance(sfx_field, (list, tuple)):
            sfx_names = [str(s) for s in sfx_field]
        else:
            logger.warning("Unexpected sfx value type %s – skipping.", type(sfx_field))
            continue

        for sfx_name in sfx_names:
            name = sfx_name.lower().strip()
            if name and name in _SFX_GENERATORS:
                events.append((start_time, name))
            else:
                logger.warning("Ignoring unknown SFX name '%s'.", sfx_name)

    # Sort chronologically
    events.sort(key=lambda e: e[0])

    # Enforce max-1-SFX-per-2-seconds rule
    timeline: list[dict] = []
    last_time: float = -_MIN_SFX_INTERVAL  # allow first event at t=0

    for time, sfx_name in events:
        if time > total_duration:
            logger.debug(
                "SFX '%s' at t=%.2f exceeds total_duration=%.2f – skipped.",
                sfx_name, time, total_duration,
            )
            continue

        if time - last_time < _MIN_SFX_INTERVAL:
            logger.debug(
                "SFX '%s' at t=%.2f too close to previous event (t=%.2f) – dropped.",
                sfx_name, time, last_time,
            )
            continue

        path = get_sfx_path(sfx_name)
        if path is None:
            logger.warning(
                "Could not obtain path for SFX '%s' – skipping event at t=%.2f.",
                sfx_name, time,
            )
            continue

        volume = _SFX_DEFAULT_VOLUMES.get(sfx_name, 0.65)
        timeline.append({"time": time, "path": path, "volume": volume})
        last_time = time

    logger.info(
        "SFX timeline built: %d events (%.1f s total).", len(timeline), total_duration
    )
    return timeline


# ---------------------------------------------------------------------------
# Quick smoke-test  (python -m src.backend.sfx_engine)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    print("=== sfx_engine smoke test ===")

    print("\n[1] ensure_sfx_assets()")
    assets = ensure_sfx_assets()
    for name, path in assets.items():
        size_kb = os.path.getsize(path) / 1024
        print(f"  {name:8s}: {path}  ({size_kb:.1f} KB)")

    print("\n[2] get_sfx_path('chime')")
    p = get_sfx_path("chime")
    print(f"  => {p!r}")

    print("\n[3] get_sfx_path('unknown')")
    p = get_sfx_path("unknown")
    print(f"  => {p!r}")

    print("\n[4] build_sfx_timeline()")
    demo_scenes = [
        {"start_time": 0.0,  "sfx": "pop"},
        {"start_time": 0.5,  "sfx": "impact"},    # too close → should be dropped
        {"start_time": 2.0,  "sfx": "whoosh"},
        {"start_time": 4.5,  "sfx": ["rise", "chime"]},
        {"start_time": 7.0,  "sfx": "glitch"},
        {"start_time": 99.0, "sfx": "chime"},     # beyond duration → dropped
    ]
    tl = build_sfx_timeline(demo_scenes, total_duration=10.0)
    for event in tl:
        print(f"  t={event['time']:.1f}s  vol={event['volume']}  {event['path']}")

    print("\nDone.")
    sys.exit(0)
