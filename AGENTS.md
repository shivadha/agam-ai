# AGENTS.md — Workspace Guidelines & Learned Knowledge

This file defines project architecture, hardware constraints, coding conventions, and dynamically learned rules for all AI assistants (Antigravity, Gemini, ShivamAI).

---

## 1. System Architecture & Hardware Constraints

- **Local GPU**: NVIDIA GeForce RTX 3060 Laptop (6144 MiB / 6 GB VRAM).
- **RAM**: 16 GB DDR4.
- **LLM Engine**: Local Ollama instance running at `http://localhost:11434`.
- **Primary Local Models**:
  - `shivam-pro` (Qwen 2.5 Coder 7B, 16k context, 4.7 GB — general engineering & architecture).
  - `shivam-coder` (Qwen 2.5 Coder 7B, 16k context, 4.7 GB — coding & testing).
  - `shivam-reasoner` (DeepSeek R1 7B, 5.2 GB — chain-of-thought logic & math).
  - `qwen3:8b` (8.2B, 5.2 GB — general reasoning & tools).
- **Model Constraint**: Never load models >10B parameters into VRAM directly without quantization; prefer 7B Q4 models which fit 100% in 6GB VRAM.

---

## 2. Tech Stack & Coding Standards

- **Backend**: Python 3.11, FastAPI, Uvicorn, SQLite.
- **Frontend**: Vanilla HTML5, CSS3, modern JavaScript (no Tailwind unless explicitly requested).
- **Database**: SQLite (`data/edupulse.db`, `youtube_trends.db`).
- **Code Style**:
  - Clean, modular, type-annotated Python code.
  - Production-ready error handling with try/except blocks and actionable logs.
  - Preserve existing comments, structure, and naming conventions.

---

## 3. Dynamically Learned Rules & Preferences
<!-- DO NOT REMOVE THIS HEADING. Auto-memory logger appends new learned rules below this line. -->
- [2026-09-27] [Coding] Always use UTF-8 encoding when opening files in Python
- [2026-09-27] [System] Initialized AGENTS.md auto-memory system for workspace.
- [2026-09-27] [LLM] Prefer `shivam-pro` for fast offline coding and `shivam-reasoner` for deep logic tasks.
- [2026-09-27] [Hardware] Always check VRAM headroom on the 6GB RTX 3060 before starting heavy background inference.
- [2026-09-28] [Agent] Meta Muse coding agent (`muse`) is installed at `C:\Users\shiva\AppData\Local\Programs\muse`, authenticated, and available for headless coding via `muse exec --yolo --trust-workspace "<prompt>"`.
- [2026-09-28] [Safety/Billing] STRICT ZERO-COST RULE: Never allow any cost on Meta Muse. If Muse ever attempts to incur a paid charge, bill a card, or run out of free tier, immediately block Muse permanently and notify the user.
- [2026-09-29] [Roblox/Git] Whenever pushing or committing changes for Roblox projects/games (projects with default.project.json or .rbxl), automatically execute the build .bat file (build_place.bat / 'rojo build -o WorldCrisisSimulator.rbxl') to ensure the place artifact is synchronized with Luau source code.
