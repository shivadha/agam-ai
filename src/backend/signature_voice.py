"""
AGAM — Channel voice identity: named voice presets + optional local cloning.

Presets are stored as JSON at assets/voice_presets.json (repo-local user
data — NOT /tmp, so they survive restarts). A preset pins the provider /
voice / rate / pitch a channel uses so every video sounds like the same
narrator.

  save_preset(name, provider, voice_id, rate=1.0, pitch=0) -> preset dict
  list_presets()  -> [{name, provider, voice_id, rate, pitch}]
  get_preset(name) -> preset dict (RuntimeError if missing)
  delete_preset(name) -> True (RuntimeError if missing)

  clone_with_chatterbox(text, ref_audio_path, out_path) -> out_path
      Real Chatterbox TTS voice cloning (Resemble AI, open weights).
      If the package is missing it raises RuntimeError with install
      instructions instead of faking output. Needs ~4GB free VRAM;
      CPU works but is slow.
"""

import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STORE_PATH = os.path.join(BASE_DIR, "assets", "voice_presets.json")


def _load_store():
    try:
        with open(STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_store(data):
    os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
    tmp = STORE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, STORE_PATH)


def save_preset(name, provider, voice_id, rate=1.0, pitch=0):
    """Create/update a voice preset. Returns the preset dict."""
    name = (name or "").strip()
    if not name:
        raise RuntimeError("Preset name is required.")
    preset = {
        "name": name,
        "provider": provider or "edge-tts",
        "voice_id": voice_id or "",
        "rate": float(rate or 1.0),
        "pitch": int(pitch or 0),
    }
    data = _load_store()
    data[name] = preset
    _save_store(data)
    print(f"[voice] Preset saved: {name}")
    return preset


def list_presets():
    """Return all presets, sorted by name. JSON-serializable."""
    return [ _load_store()[k] for k in sorted(_load_store()) ]


def get_preset(name):
    """Return one preset; RuntimeError if it doesn't exist."""
    preset = _load_store().get((name or "").strip())
    if not preset:
        raise RuntimeError(
            f"Voice preset '{name}' not found. Create it first via POST /api/voice/presets."
        )
    return preset


def delete_preset(name):
    """Delete a preset; RuntimeError if it doesn't exist. Returns True."""
    data = _load_store()
    key = (name or "").strip()
    if key not in data:
        raise RuntimeError(f"Voice preset '{name}' not found — nothing to delete.")
    del data[key]
    _save_store(data)
    print(f"[voice] Preset deleted: {key}")
    return True


def _chatterbox_device():
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def clone_with_chatterbox(text, ref_audio_path, out_path):
    """Clone a voice from a reference clip and synthesize text with it.

    Real implementation via chatterbox-tts. Raises RuntimeError (never
    silent garbage) when the package is missing or generation fails.
    """
    try:
        from chatterbox.tts import ChatterboxTTS
    except ImportError:
        raise RuntimeError(
            "Chatterbox is not installed. Install with: pip install chatterbox-tts "
            "(needs ~4GB free VRAM; CPU works but is slow). Voice cloning is "
            "unavailable until then."
        )

    text = (text or "").strip()
    if not text:
        raise RuntimeError("No text provided for voice cloning.")
    if not ref_audio_path or not os.path.exists(ref_audio_path):
        raise RuntimeError(f"Reference audio not found: {ref_audio_path}")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    try:
        device = _chatterbox_device()
        print(f"[voice] Loading Chatterbox on {device} (first run downloads weights)...")
        model = ChatterboxTTS.from_pretrained(device=device)

        # Chatterbox handles ~40s per call; chunk long scripts on sentences.
        import re
        chunks, cur = [], ""
        for sent in re.split(r"(?<=[.!?])\s+", text):
            if len(cur) + len(sent) + 1 > 400:
                if cur:
                    chunks.append(cur)
                cur = sent
            else:
                cur = (cur + " " + sent).strip()
        if cur:
            chunks.append(cur)

        import torch
        import torchaudio as ta
        wavs = [model.generate(c, audio_prompt_path=ref_audio_path) for c in chunks]
        wav = torch.cat(wavs, dim=-1) if len(wavs) > 1 else wavs[0]
        ta.save(out_path, wav, model.sr)
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Chatterbox generation failed: {e}")

    if not os.path.exists(out_path) or os.path.getsize(out_path) < 1000:
        raise RuntimeError("Chatterbox produced no audio output.")
    print(f"[voice] Cloned voiceover -> {out_path}")
    return out_path
