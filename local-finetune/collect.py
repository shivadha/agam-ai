#!/usr/bin/env python3
"""
collect.py — build your fine-tuning dataset, one good Q&A at a time.

The dataset is a JSONL file. Each line:
    {"instruction": "...", "input": "...", "output": "..."}
  - instruction: the task / question (required)
  - input:      optional extra context (code, error log, ...)
  - output:     the GOOD answer — the one you want the model to learn (required)

Commands:
    python collect.py add --instruction "..." --output "..." [--input "..."]
    python collect.py add --interactive
    python collect.py validate
    python collect.py stats
"""
import argparse
import json
import os
import sys

DEFAULT_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "pairs.jsonl")


def _ensure_parent(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)


def cmd_add(args):
    _ensure_parent(args.data)
    if args.interactive:
        print("Enter pairs interactively. Empty instruction = done.\n")
        added = 0
        while True:
            instr = input("instruction> ").strip()
            if not instr:
                break
            inp = input("input (optional)> ").strip()
            print("output (end with a single '.' on its own line)>")
            lines = []
            while True:
                ln = input()
                if ln.strip() == ".":
                    break
                lines.append(ln)
            out = "\n".join(lines).strip()
            if not out:
                print("  skipped (empty output)\n")
                continue
            _append(args.data, instr, inp, out)
            added += 1
            print(f"  saved ({added} this session)\n")
        print(f"Done. {added} pair(s) added to {args.data}")
        return
    if not args.instruction or not args.output:
        sys.exit("Need --instruction and --output (or use --interactive).")
    _append(args.data, args.instruction, args.input or "", args.output)
    print(f"Saved to {args.data}")


def _append(path, instruction, input_, output):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"instruction": instruction, "input": input_,
                             "output": output}, ensure_ascii=False) + "\n")


def _iter_rows(path):
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield i, json.loads(line)
            except json.JSONDecodeError as e:
                yield i, {"__error__": str(e)}


def cmd_validate(args):
    bad = 0
    n = 0
    for i, obj in _iter_rows(args.data):
        n += 1
        if "__error__" in obj:
            print(f"  line {i}: invalid JSON ({obj['__error__']})")
            bad += 1
            continue
        if not str(obj.get("instruction", "")).strip() or not str(obj.get("output", "")).strip():
            print(f"  line {i}: missing instruction or output")
            bad += 1
    print(f"{n} rows checked, {bad} bad." + (" Fix the bad rows before training." if bad else " All good."))
    sys.exit(1 if bad else 0)


def cmd_stats(args):
    n = 0
    in_tok = out_tok = 0
    for _, obj in _iter_rows(args.data):
        if "__error__" in obj:
            continue
        n += 1
        in_tok += len(str(obj.get("instruction", "")).split()) + len(str(obj.get("input", "")).split())
        out_tok += len(str(obj.get("output", "")).split())
    print(f"pairs: {n}")
    if n:
        print(f"avg input words: {in_tok / n:.0f}   avg output words: {out_tok / n:.0f}")
        if n < 200:
            print("Tip: aim for 200+ pairs (500-2000 is ideal) before training.")


def main():
    ap = argparse.ArgumentParser(description="Build your fine-tuning dataset.")
    ap.add_argument("--data", default=DEFAULT_DATA)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="Add one Q&A pair.")
    p_add.add_argument("--instruction"); p_add.add_argument("--input", default="")
    p_add.add_argument("--output"); p_add.add_argument("--interactive", action="store_true")

    sub.add_parser("validate", help="Check the JSONL file for bad rows.")
    sub.add_parser("stats", help="Show dataset stats.")
    args = ap.parse_args()
    {"add": cmd_add, "validate": cmd_validate, "stats": cmd_stats}[args.cmd](args)


if __name__ == "__main__":
    main()
