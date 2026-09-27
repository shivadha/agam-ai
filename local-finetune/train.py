#!/usr/bin/env python3
"""
train.py — QLoRA fine-tune a HuggingFace causal LM on your own Q&A pairs.

Defaults are tuned for a 6GB VRAM card (RTX 3060):
  4-bit NF4 base, LoRA r=16, seq_len=1024, batch=1, grad-accum=16,
  gradient checkpointing, paged 8-bit optimizer.

Usage:
    python train.py --data local-finetune/data/pairs.jsonl --model Qwen/Qwen3-4B
    python train.py --model <any-hf-id> --allow-big-model   # >6B params, likely OOM on 6GB

Needs: torch (CUDA), transformers, peft, trl, bitsandbytes, datasets, accelerate.
See requirements-finetune.txt and README.md.
"""
import argparse
import json
import os
import sys


def load_pairs(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            instr = str(obj.get("instruction", "")).strip()
            out = str(obj.get("output", "")).strip()
            if not instr or not out:
                print(f"  [skip] line {i}: needs 'instruction' + 'output'")
                continue
            inp = str(obj.get("input", "")).strip()
            user = instr + (f"\n\nContext:\n{inp}" if inp else "")
            rows.append({"user": user, "assistant": out})
    return rows


def main():
    ap = argparse.ArgumentParser(description="QLoRA fine-tune on your Q&A pairs.")
    ap.add_argument("--data", default=os.path.join("local-finetune", "data", "pairs.jsonl"))
    ap.add_argument("--model", default="Qwen/Qwen3-4B",
                    help="Any HuggingFace causal-LM id.")
    ap.add_argument("--out", default=os.path.join("local-finetune", "adapters", "my-adapter"))
    ap.add_argument("--epochs", type=float, default=2)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--seq-len", type=int, default=1024)
    ap.add_argument("--grad-accum", type=int, default=16)
    ap.add_argument("--allow-big-model", action="store_true",
                    help="Allow training >6B-param models (likely OOM on 6GB VRAM).")
    args = ap.parse_args()

    import torch
    if not torch.cuda.is_available():
        sys.exit("ERROR: no CUDA GPU detected. This script needs an NVIDIA GPU.")
    vram = torch.cuda.get_device_properties(0).total_memory / 1e9
    print(f"GPU: {torch.cuda.get_device_name(0)} ({vram:.1f} GB VRAM)")

    rows = load_pairs(args.data)
    print(f"Loaded {len(rows)} training pairs from {args.data}")
    if len(rows) < 50:
        print("WARNING: very few examples — expect weak results. Aim for 200+.")
    if not rows:
        sys.exit("No usable training data. Add pairs with collect.py first.")

    from datasets import Dataset
    from transformers import (AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig)
    from peft import LoraConfig, prepare_model_for_kbit_training

    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "right"

    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.model, quantization_config=bnb,
        device_map="auto", trust_remote_code=True,
        attn_implementation="sdpa",
    )
    n_params = model.num_parameters()
    print(f"Model parameters: {n_params / 1e9:.2f}B")
    if n_params > 6e9 and not args.allow_big_model:
        sys.exit(
            f"ERROR: {n_params/1e9:.1f}B params will almost certainly OOM on 6GB VRAM.\n"
            "Use a <=4B model (e.g. Qwen/Qwen3-4B), or pass --allow-big-model "
            "with --seq-len 512 --rank 8 and hope.")

    model = prepare_model_for_kbit_training(model)
    model.config.use_cache = False

    peft_cfg = LoraConfig(
        r=args.rank, lora_alpha=args.rank * 2, lora_dropout=0.05,
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )

    def to_text(ex):
        return tok.apply_chat_template(
            [{"role": "user", "content": ex["user"]},
             {"role": "assistant", "content": ex["assistant"]}],
            tokenize=False, add_generation_prompt=False)

    full = Dataset.from_list([{"text": to_text(r)} for r in rows])
    split = full.train_test_split(test_size=0.05, seed=42) if len(full) >= 100 else None
    train_ds = split["train"] if split else full
    eval_ds = split["test"] if split else None
    print(f"train: {len(train_ds)}" + (f"   eval: {len(eval_ds)}" if eval_ds is not None else ""))

    common = dict(
        output_dir=args.out,
        per_device_train_batch_size=1,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=args.grad_accum,
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        optim="paged_adamw_8bit",
        bf16=True,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        logging_steps=10,
        save_strategy="epoch",
        save_total_limit=1,
        eval_strategy="epoch" if eval_ds is not None else "no",
        dataloader_num_workers=0,      # Windows-safe
        report_to="none",
        seed=42,
    )
    try:
        from trl import SFTConfig, SFTTrainer
        targs = SFTConfig(max_seq_length=args.seq_len, **common)
        trainer = SFTTrainer(model=model, args=targs,
                             train_dataset=train_ds, eval_dataset=eval_ds,
                             peft_config=peft_cfg)
    except ImportError:
        from transformers import TrainingArguments
        from trl import SFTTrainer
        targs = TrainingArguments(**common)
        trainer = SFTTrainer(model=model, args=targs,
                             train_dataset=train_ds, eval_dataset=eval_ds,
                             peft_config=peft_cfg, max_seq_length=args.seq_len)

    print("Training started — grab a coffee. This takes a while on 6GB VRAM.")
    trainer.train()
    trainer.save_model(args.out)
    tok.save_pretrained(args.out)
    print(f"\nAdapter saved to {args.out}")
    print(f"Next: python export_ollama.py --adapter {args.out} --name my-model")


if __name__ == "__main__":
    main()
