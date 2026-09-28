#!/usr/bin/env python3
"""
Chatterbox synthesis worker (resemble-ai/chatterbox — free, local, MIT).

Runs in its OWN process so the Flask app never imports torch: the model is
loaded once here, every text chunk is synthesized with sentence-level
prosody steering, chunks are stitched with room tone (not digital silence),
loudness-normalized, and a single WAV is written. VRAM is released when
this process exits.

Usage (called from voice_gen._generate_audio_chatterbox, not by hand):
    python chatterbox_synthesize.py --text-file narration.txt --output out.wav
        [--backend turbo|multilingual] [--audio-prompt ref.wav]
        [--exaggeration 0.6] [--cfg-weight 0.4] [--language en]
        [--chunk-chars 300]

Backends:
  * turbo        — ChatterboxTurboTTS (350M, single-step, ~2GB VRAM).
                   Paralinguistic tags render inline: [laugh] [chuckle] [cough]
  * multilingual — ChatterboxMultilingualTTS (500M, 23+ languages, ~3GB VRAM).
                   Use --language hi + --model ResembleAI/Chatterbox-Multilingual-hi
                   for the dedicated Hindi finetune.

The EMOTION IN THE REFERENCE carries into the output: clone an energetic,
conversational 10–30s clip and the narration comes out energetic. A flat
stock voice reference gives a flat reading — pick the reference on purpose.
"""

import argparse
import os
import re
import sys


def split_text_chunks(text: str, max_chars: int = 300):
    """Split narration into sentence-boundary chunks of <= max_chars.

    Chatterbox is autoregressive: resetting per sentence kills the monotone
    drift that long passages develop. Keep chunks SHORT (<=300 chars) so
    each sentence gets fresh prosody instead of one flat read.
    """
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?…])\s+", text)
    chunks, current = [], ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        while len(sentence) > max_chars:
            chunks.append(sentence[:max_chars])
            sentence = sentence[max_chars:].strip()
        if not sentence:
            continue
        if len(current) + len(sentence) + 1 <= max_chars:
            current = (current + " " + sentence).strip()
        else:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Chatterbox batch synthesis worker")
    parser.add_argument("--text-file", required=True, help="UTF-8 text file to synthesize")
    parser.add_argument("--output", required=True, help="Output WAV path")
    parser.add_argument("--backend", default="turbo",
                        choices=["turbo", "multilingual"],
                        help="turbo (350M, fastest) or multilingual (500M, 23+ langs)")
    parser.add_argument("--model", default=None,
                        help="HF repo id override, e.g. ResembleAI/Chatterbox-Multilingual-hi")
    parser.add_argument("--audio-prompt", default=None,
                        help="10–30s reference WAV for voice cloning (energetic narrator)")
    parser.add_argument("--exaggeration", type=float, default=0.6,
                        help="0.0–1.0 prosody intensity; 0.6–0.7 for dramatic Shorts")
    parser.add_argument("--cfg-weight", type=float, default=0.4,
                        help="~0.3 slower/deliberate, ~0.5 neutral; lower compensates high exaggeration")
    parser.add_argument("--language", default="en",
                        help="language_id for multilingual backend (en, hi, ...)")
    parser.add_argument("--chunk-chars", type=int, default=300,
                        help="Max characters per synthesis chunk")
    parser.add_argument("--room-tone-ms", type=int, default=220,
                        help="Room tone between chunks (ms); not digital silence")
    return parser.parse_args(argv)


def _room_tone(n_samples: int, sr: int, rng):
    """Low-level brown-ish noise at ~-58dBFS — reads as room, not silence."""
    # Cheap brown noise: cumulative sum of white noise, normalized.
    white = rng.standard_normal(n_samples)
    brown = white.cumsum()
    brown = brown - brown.mean()
    peak = abs(brown).max() or 1.0
    brown = brown / peak
    return (brown * 0.0012).astype("float32")  # ≈ -58 dBFS peak


def _stitch_with_room_tone(audios, sr: int, room_tone_ms: int):
    """Join chunk audios with room tone between them + light compression.

    Digital-silence gaps and volume jumps between chunks are a dead giveaway
    even when the voice itself is good. Each chunk is peak-normalized to a
    common target and gently limited so the stitch is invisible.
    """
    import numpy as np

    if not audios:
        raise RuntimeError("No audio chunks to stitch.")
    normed = []
    for a in audios:
        a = np.asarray(a, dtype=np.float32).reshape(-1)
        if a.size == 0:
            continue
        # Peak-normalize each chunk to the same target (0.89 ≈ -1 dBFS).
        peak = float(abs(a).max())
        if peak > 1e-6:
            a = a * (0.89 / peak)
        # Gentle soft-clip so nothing slams: tanh knees in at ~0.9.
        a = np.tanh(a / 0.9) * 0.9
        normed.append(a)
    if not normed:
        raise RuntimeError("All audio chunks were empty.")

    rng = np.random.default_rng(1234)
    gap = _room_tone(int(sr * room_tone_ms / 1000), sr, rng)
    pieces = []
    for i, a in enumerate(normed):
        if i:
            pieces.append(gap)
        pieces.append(a)
    return np.concatenate(pieces)


def main(argv=None):
    args = parse_args(argv)

    with open(args.text_file, "r", encoding="utf-8") as fh:
        text = fh.read()
    chunks = split_text_chunks(text, args.chunk_chars)
    if not chunks:
        print("[chatterbox] ERROR: no text to synthesize", file=sys.stderr)
        return 2
    if args.audio_prompt and not os.path.exists(args.audio_prompt):
        print(f"[chatterbox] ERROR: reference audio not found: {args.audio_prompt}",
              file=sys.stderr)
        return 2

    import numpy as np

    if args.backend == "turbo":
        from chatterbox.tts_turbo import ChatterboxTurboTTS
        print(f"[chatterbox] loading Turbo ({args.model or 'default'}) ...", flush=True)
        if args.model:
            model = ChatterboxTurboTTS.from_pretrained(args.model, device="cuda")
        else:
            model = ChatterboxTurboTTS.from_pretrained(device="cuda")
        sr = model.sr
        gen_kwargs = {"exaggeration": args.exaggeration, "cfg_weight": args.cfg_weight}
    else:
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        print(f"[chatterbox] loading Multilingual ({args.model or 'default'}), "
              f"language={args.language} ...", flush=True)
        if args.model:
            model = ChatterboxMultilingualTTS.from_pretrained(args.model, device="cuda")
        else:
            model = ChatterboxMultilingualTTS.from_pretrained(device="cuda")
        sr = model.sr
        gen_kwargs = {"language_id": args.language, "exaggeration": args.exaggeration,
                      "cfg_weight": args.cfg_weight}

    print(f"[chatterbox] chunks={len(chunks)} exaggeration={args.exaggeration} "
          f"cfg_weight={args.cfg_weight} "
          f"ref={'clone:' + os.path.basename(args.audio_prompt) if args.audio_prompt else 'default-voice'}",
          flush=True)

    audios = []
    for i, chunk in enumerate(chunks, 1):
        print(f"[chatterbox] chunk {i}/{len(chunks)} ({len(chunk)} chars) ...", flush=True)
        wav = model.generate(chunk, audio_prompt_path=args.audio_prompt, **gen_kwargs)
        audios.append(np.asarray(wav.detach().cpu().numpy(), dtype=np.float32).reshape(-1))

    stitched = _stitch_with_room_tone(audios, sr, args.room_tone_ms)

    import soundfile as sf
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    sf.write(args.output, stitched, sr)
    print(f"[chatterbox] wrote {args.output} "
          f"({len(stitched) / sr:.1f}s @ {sr}Hz, {len(chunks)} chunks stitched)",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
