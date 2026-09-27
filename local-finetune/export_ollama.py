#!/usr/bin/env python3
"""
export_ollama.py — merge your LoRA adapter into the base model and
prepare it for Ollama.

Steps:
  1. Reads the base model id from the adapter's adapter_config.json
     (override with --model).
  2. Merges the adapter into fp16 weights on CPU and saves a safetensors
     directory.  NOTE: merging a 4B model needs ~10GB free RAM.
  3. Writes a Modelfile (FROM <dir>) — Ollama imports safetensors
     directories directly and quantizes on import, so the result fits
     your 6GB VRAM.
  4. Prints the `ollama create` / `ollama run` commands.

Usage:
    python export_ollama.py --adapter local-finetune/adapters/my-adapter --name my-model
"""
import argparse
import json
import os
import sys


def main():
    ap = argparse.ArgumentParser(description="Merge LoRA adapter for Ollama.")
    ap.add_argument("--adapter", required=True, help="Adapter dir from train.py")
    ap.add_argument("--model", default=None, help="Base HF id (default: read from adapter_config.json)")
    ap.add_argument("--name", default="my-model", help="Ollama model name to create")
    ap.add_argument("--out", default=None, help="Merged output dir (default: <adapter>-merged)")
    args = ap.parse_args()

    cfg_path = os.path.join(args.adapter, "adapter_config.json")
    if not os.path.exists(cfg_path):
        sys.exit(f"ERROR: {cfg_path} not found — is this a PEFT adapter dir?")
    with open(cfg_path) as f:
        base_id = args.model or json.load(f).get("base_model_name_or_path")
    if not base_id:
        sys.exit("ERROR: could not determine base model. Pass --model explicitly.")
    out_dir = args.out or (args.adapter.rstrip("/\\") + "-merged")
    os.makedirs(out_dir, exist_ok=True)
    print(f"Base model: {base_id}\nMerging into: {out_dir}")
    print("NOTE: merging runs on CPU and needs ~10GB free RAM for a 4B model.\n")

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel

    base = AutoModelForCausalLM.from_pretrained(
        base_id, torch_dtype=torch.float16,
        device_map="cpu", trust_remote_code=True)
    model = PeftModel.from_pretrained(base, args.adapter)
    merged = model.merge_and_unload()
    merged.save_pretrained(out_dir, safe_serialization=True)
    tok = AutoTokenizer.from_pretrained(args.adapter, trust_remote_code=True)
    tok.save_pretrained(out_dir)
    del base, model, merged
    print("Merged weights saved.")

    modelfile = os.path.join(out_dir, "Modelfile")
    with open(modelfile, "w", encoding="utf-8") as f:
        f.write("FROM .\n")
    print(f"Modelfile written to {modelfile}\n")

    print("Import into Ollama (run from the merged dir):")
    print(f"    cd {out_dir}")
    print(f"    ollama create {args.name}")
    print(f"    ollama run {args.name}")
    print("\nOllama imports the safetensors directory directly and quantizes on")
    print("import, so the created model fits your 6GB VRAM.")


if __name__ == "__main__":
    main()
