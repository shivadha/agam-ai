# Local Fine-Tuning Pipeline (RTX 3060 6GB)

Train a small local model on **your own** Q&A pairs so it learns your coding
patterns, your libraries, and how you like answers formatted. Everything runs
on your machine, free, and the result plugs straight back into Ollama.

**What fine-tuning actually does:** teaches the model *your style and patterns*.
It does **not** add new knowledge or make a 4B model reason like a 70B one.
For IDE work (your queries → your preferred answers), style/pattern learning is
exactly what you want.

**The loop** (not per-query — in batches):
1. **Collect** good pairs over days/weeks → `data/pairs.jsonl`
2. **Train** overnight → `adapters/my-adapter`
3. **Export** → `ollama create my-model`
4. Repeat when you've collected another few hundred pairs.

---

## 1. Install (Windows, one time)

```bat
pip install torch --index-url https://download.pytorch.org/whl/cu126
pip install -r local-finetune/requirements-finetune.txt
```

If `bitsandbytes` misbehaves on Windows, run everything from WSL2 instead.

## 2. Collect data

Aim for **200+ pairs** (500–2000 is ideal). Quality beats quantity — one great
pair is worth twenty sloppy ones.

```bat
:: interactive mode (recommended)
python local-finetune/collect.py add --interactive

:: or single-shot
python local-finetune/collect.py add --instruction "your question" --output "the good answer"

:: check + stats
python local-finetune/collect.py validate
python local-finetune/collect.py stats
```

**What makes a good pair:**
- The `output` is the answer you *wish* the model had given — paste the good
  answer you got (from any model) and clean it up, or write it yourself.
- Keep pairs focused: one task per pair, like your real IDE queries.
- Include your real context in `input` (the code/error you were looking at).
- See `data/examples.jsonl` for the exact format.

## 3. Train (overnight)

```bat
python local-finetune/train.py --data local-finetune/data/pairs.jsonl --model Qwen/Qwen3-4B
```

Defaults are tuned for 6GB VRAM: 4-bit NF4 base, LoRA r=16, seq-len 1024,
batch 1 × 16 grad-accum, gradient checkpointing. Expect a few hours for
~1000 pairs.

- `--model` accepts any HuggingFace causal-LM id. Stick to **≤4B** on 6GB VRAM.
  Bigger models are refused unless you pass `--allow-big-model` (likely OOM).
- If you hit CUDA OOM: `--seq-len 512 --rank 8`, close the browser/Ollama first.
- Useful tweaks: `--epochs 3`, `--lr 1e-4` (safer, slower learning).

## 4. Export to Ollama

```bat
python local-finetune/export_ollama.py --adapter local-finetune/adapters/my-adapter --name my-model
cd local-finetune/adapters/my-adapter-merged
ollama create my-model
ollama run my-model
```

Ollama imports the safetensors directory directly and quantizes on import, so
the result fits your 6GB card. Merging needs ~10GB free system RAM for a 4B model.

## 5. Iterate

Keep collecting pairs as you work. When you have a few hundred new ones,
retrain **from the base model** on the full dataset (old + new) — don't stack
adapters on adapters.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `CUDA out of memory` during training | `--seq-len 512 --rank 8`; close GPU apps; smaller base model |
| Training loss not decreasing | More/better data; raise `--epochs` to 3; check `validate` passes |
| Model repeats itself / degraded | Too many epochs on too little data — add data, lower `--epochs` |
| `bitsandbytes` install fails (Windows) | Use WSL2, or `pip install bitsandbytes --no-cache-dir` |
| Merge step is slow / swaps | Needs ~10GB free RAM; close other apps during export |
