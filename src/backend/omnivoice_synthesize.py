#!/usr/bin/env python3
"""
OmniVoice synthesis worker (k2-fsa/OmniVoice — free, local, Apache-2.0).

Runs in its OWN process so the Flask app never imports torch: the model is
loaded once here, every text chunk is synthesized, chunks are concatenated,
and a single WAV is written. VRAM is released when this process exits.

Usage (called from voice_gen._generate_audio_omnivoice, not by hand):
    python omnivoice_synthesize.py --text-file narration.txt --output out.wav
        [--model k2-fsa/OmniVoice] [--ref_audio ref.wav] [--ref_text "..."]
        [--instruct "female, low pitch"] [--language English] [--speed 1.0]
        [--chunk-chars 600]

Voice modes (same as the official omnivoice-infer CLI):
  * auto         — no ref audio / instruct  (model picks a voice)
  * clone        — --ref_audio (+ optional --ref_text; Whisper auto-transcribes
                   the ref clip when --ref_text is omitted)
  * design       — --instruct "female, low pitch, british accent"
"""

import argparse
import os
import re
import sys


def split_text_chunks(text: str, max_chars: int = 600):
    """Split narration into sentence-boundary chunks of <= max_chars.

    A single over-long sentence is hard-split so no chunk ever exceeds the
    limit. Empty fragments are dropped.
    """
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        return []
    # Split on sentence-ending punctuation, keeping the delimiter.
    sentences = re.split(r"(?<=[.!?…])\s+", text)
    chunks, current = [], ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        # Hard-split a pathological single sentence.
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
    parser = argparse.ArgumentParser(description="OmniVoice batch synthesis worker")
    parser.add_argument("--text-file", required=True, help="UTF-8 text file to synthesize")
    parser.add_argument("--output", required=True, help="Output WAV path")
    parser.add_argument("--model", default="k2-fsa/OmniVoice",
                        help="HF repo id or local checkpoint dir")
    parser.add_argument("--ref_audio", default=None, help="Reference WAV for voice cloning")
    parser.add_argument("--ref_text", default=None, help="Transcript of --ref_audio (optional)")
    parser.add_argument("--instruct", default=None, help="Voice-design instruction, e.g. 'female, low pitch'")
    parser.add_argument("--language", default="English", help="Language name or code, e.g. English / en")
    parser.add_argument("--speed", type=float, default=1.0, help="Speed factor")
    parser.add_argument("--num_step", type=int, default=32, help="Diffusion steps (16 = faster)")
    parser.add_argument("--chunk-chars", type=int, default=600,
                        help="Max characters per synthesis chunk")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    with open(args.text_file, "r", encoding="utf-8") as fh:
        text = fh.read()
    chunks = split_text_chunks(text, args.chunk_chars)
    if not chunks:
        print("[omnivoice] ERROR: no text to synthesize", file=sys.stderr)
        return 2
    if args.ref_audio and not os.path.exists(args.ref_audio):
        print(f"[omnivoice] ERROR: ref audio not found: {args.ref_audio}", file=sys.stderr)
        return 2

    import torch
    from omnivoice import OmniVoice
    from omnivoice.utils.common import get_best_device

    device = get_best_device()
    print(f"[omnivoice] loading {args.model} on {device} ...", flush=True)
    model = OmniVoice.from_pretrained(args.model, device_map=device, dtype=torch.float16)

    mode = "auto"
    if args.ref_audio:
        mode = "clone"
    elif args.instruct:
        mode = "design"
    print(f"[omnivoice] mode={mode} chunks={len(chunks)} speed={args.speed}", flush=True)

    import numpy as np

    audios = []
    for i, chunk in enumerate(chunks, 1):
        print(f"[omnivoice] chunk {i}/{len(chunks)} ({len(chunk)} chars) ...", flush=True)
        out = model.generate(
            text=chunk,
            language=args.language,
            ref_audio=args.ref_audio,
            ref_text=args.ref_text,
            instruct=args.instruct,
            speed=args.speed,
            num_step=args.num_step,
        )
        audios.append(np.asarray(out[0]).reshape(-1))

    import soundfile as sf

    wav = np.concatenate(audios) if len(audios) > 1 else audios[0]
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    sf.write(args.output, wav, model.sampling_rate)
    print(f"[omnivoice] wrote {args.output} "
          f"({len(wav) / model.sampling_rate:.1f}s @ {model.sampling_rate}Hz)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
