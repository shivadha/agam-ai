"""
skill_engine.py -- AGAM AI Brain Transplant System
====================================================
Implements the HuggingFace "Upskill Agents" pattern:
  - Teacher Model (GPT-4o) forges structured Skill JSON files
  - Student Model (Groq/Ollama) loads the skill at runtime via prompt injection
  - No fine-tuning, no retraining -- pure runtime expertise injection

Skill Flow:
  forge_skill() -> skills/<id>.json -> inject_skill() -> augmented_system_prompt
"""

import os
import json
import time
import re
from typing import Dict, Any, List, Optional
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")
os.makedirs(SKILLS_DIR, exist_ok=True)


DEFAULT_SKILLS = [
    {
        "id": "video_generation",
        "name": "Video Generation Expert",
        "version": "1.0",
        "description": "Expert in ComfyUI, LTX-Video, Wan 2.1, viral reel pipeline and video automation",
        "created_by": "system",
        "created_at": "2025-01-01T00:00:00Z",
        "domain_prompt": (
            "You are a world-class expert in AI video generation. "
            "You deeply understand ComfyUI workflow JSON structure, LTX-Video and Wan 2.1 diffusion models, "
            "the PulseForge viral reel pipeline (script_gen -> hook_writer -> video_gen_ai -> video_assembler), "
            "LoRA weights, cfg_scale, steps, frame rates, and GPU VRAM optimization for RTX 3060 6GB. "
            "When asked about video generation, provide specific, actionable commands and ComfyUI workflow configs. "
            "Always consider VRAM constraints and suggest efficient batch sizes."
        ),
        "knowledge_blocks": [
            "ComfyUI workflow JSON: nodes are dicts with class_type, inputs, outputs. Key nodes: CLIPTextEncode, KSampler, VAEDecode, SaveImage.",
            "LTX-Video parameters: steps=25-50, cfg=7.5, scheduler=euler, resolution 512x512 or 768x512 for RTX 3060.",
            "Wan 2.1 optimal settings: steps=20, cfg=7, motion_bucket_id=127, use fp16 for VRAM savings.",
            "PulseForge video pipeline: src/backend/script_gen.py -> src/backend/hook_writer.py -> src/backend/video_gen_ai.py -> src/backend/video_assembler.py",
            "ComfyUI API: POST /prompt with {prompt: {nodes...}, client_id: uuid}. Check /queue for status.",
            "RTX 3060 6GB VRAM budget: keep model + VAE + CLIP under 5.5GB. Use --lowvram flag if needed."
        ],
        "worked_examples": [
            {
                "user": "generate a 3 second viral reel about AI",
                "assistant": "Boss, viral reel pipeline chala raha hu! Script gen -> hook writer -> LTX-Video generation sequence execute ho rahi hai. [ACTION: execute_command {\"command\": \"python src/backend/viral_reel_brain.py --topic 'AI' --duration 3\"}]"
            },
            {
                "user": "what are the ComfyUI nodes for video",
                "assistant": "Boss, ComfyUI video nodes: CLIPTextEncode for prompts, LTXVideoLoader for model, KSamplerAdvanced for diffusion, VAEDecodeTiled for memory-efficient decoding, VHS_VideoCombine for output."
            }
        ],
        "tool_hints": ["execute_command", "read_file", "list_dir"],
        "trigger_keywords": ["video", "reel", "comfyui", "ltx", "wan", "animate", "diffusion", "frame", "viral", "generate video", "video gen"],
        "active": True
    },
    {
        "id": "code_architect",
        "name": "Python & Flask Code Architect",
        "version": "1.0",
        "description": "Expert in Python, Flask REST APIs, SQLite, APScheduler, and PulseForge architecture",
        "created_by": "system",
        "created_at": "2025-01-01T00:00:00Z",
        "domain_prompt": (
            "You are a senior Python and Flask architect with deep knowledge of PulseForge's architecture: "
            "Flask app.py as entry point, src/database.py for SQLite persistence, src/aggregator.py for news ingestion, "
            "APScheduler for background jobs, Flask-Login for auth, and src/agam/ for the AGAM AI agent layer. "
            "Always follow existing conventions, use proper error handling, and provide complete runnable implementations."
        ),
        "knowledge_blocks": [
            "PulseForge structure: app.py (Flask entry), src/database.py (SQLite), src/aggregator.py (news), src/backend/ (AI pipelines), src/agam/ (AI agent), static/ (JS/CSS), templates/ (HTML).",
            "Flask pattern: @app.route decorators, login_required, jsonify responses, request.get_json().",
            "Database: SQLite via sqlite3, no ORM. Functions in src/database.py: get_articles(), save_article(), get_user_by_id().",
            "Auth: Flask-Login, User class extends UserMixin, roles in database.ROLES dict.",
            "APScheduler: BackgroundScheduler, add_job with interval trigger, daemon=True.",
            "AGAM integration: from src.agam import agam_brain, then agam_brain.process_message() or process_message_stream()."
        ],
        "worked_examples": [
            {"user": "add a new Flask API endpoint", "assistant": "Boss, naya endpoint add karta hu! Pattern follow karta hu existing routes ka. [ACTION: read_file {\"path\": \"app.py\", \"lines\": 50}]"}
        ],
        "tool_hints": ["read_file", "write_file", "edit_file", "search_code"],
        "trigger_keywords": ["flask", "route", "endpoint", "api", "python", "database", "sqlite", "class", "function", "import", "code", "debug", "error", "fix"],
        "active": True
    },
    {
        "id": "ai_model_trainer",
        "name": "AI Model Training & Fine-Tuning Expert",
        "version": "1.0",
        "description": "Expert in LoRA fine-tuning, Ollama local models, HuggingFace, and model optimization",
        "created_by": "system",
        "created_at": "2025-01-01T00:00:00Z",
        "domain_prompt": (
            "You are a machine learning expert specializing in efficient model training and fine-tuning. "
            "You know LoRA/QLoRA PEFT methods, HuggingFace transformers, Ollama local model management, "
            "dataset preparation, training hyperparameters, and running models on RTX 3060 6GB. "
            "Always prefer quantized models (Q4_K_M, Q5_K_M) for VRAM efficiency. "
            "Use Ollama for local inference: llama3.2, qwen2.5-coder, mistral, phi3."
        ),
        "knowledge_blocks": [
            "Ollama commands: ollama pull <model>, ollama run <model>, ollama list, ollama serve (port 11434).",
            "LoRA training: use peft library, LoraConfig(r=16, alpha=32, target_modules=['q_proj','v_proj']), 4-bit quantization with bitsandbytes.",
            "HuggingFace: from transformers import AutoModelForCausalLM, AutoTokenizer. Use load_in_4bit=True for RTX 3060.",
            "Dataset prep: use datasets library, format as {instruction, input, output} or {messages: [{role, content}]}.",
            "RTX 3060 6GB: can run 7B models in 4-bit (~4GB VRAM), 13B needs quantization + offloading.",
            "AGAM local model endpoint: http://localhost:11434/api/generate or /api/chat (Ollama API)."
        ],
        "worked_examples": [
            {"user": "how do I fine-tune a model on my dataset", "assistant": "Boss, fine-tuning pipeline setup karta hu! RTX 3060 ke liye QLoRA approach best rahega. 4-bit quantization se 7B model fit ho jayega 6GB VRAM mein."}
        ],
        "tool_hints": ["execute_command", "write_file"],
        "trigger_keywords": ["finetune", "fine-tune", "train", "lora", "qlora", "model", "ollama", "huggingface", "dataset", "epoch", "weights", "checkpoint"],
        "active": True
    },
    {
        "id": "content_creator",
        "name": "Viral Content & Script Writing Expert",
        "version": "1.0",
        "description": "Expert in viral YouTube/Instagram scripts, hook writing, trend analysis, and content strategy",
        "created_by": "system",
        "created_at": "2025-01-01T00:00:00Z",
        "domain_prompt": (
            "You are a world-class viral content strategist and script writer. "
            "You understand PulseForge's content pipeline: trending topic aggregation -> hook writing -> "
            "script generation -> video creation -> YouTube/Instagram publishing. "
            "You know what makes content go viral: strong hooks in first 3 seconds, pattern interrupts, emotional triggers. "
            "For Indian audience: mix English and Hindi naturally (Hinglish), use relatable examples."
        ),
        "knowledge_blocks": [
            "PulseForge script pipeline: src/backend/script_gen.py generates scripts, src/backend/hook_writer.py writes viral hooks.",
            "Viral hook formula: [Shocking Stat/Question] + [Pain Point] + [Promise of Solution] in under 8 seconds.",
            "Script structure: Hook (3s) -> Problem (10s) -> Solution (30s) -> Proof (15s) -> CTA (5s).",
            "Indian viral content: use desi references, mix Hinglish, mention relatable struggles (exams, jobs, hustle culture).",
            "YouTube optimization: title with numbers/emotions, thumbnail with face+text, first 30s retention is critical.",
            "Trend sources: aggregator.py pulls from Reddit, Twitter/X, Google Trends. Latest articles in /api/articles."
        ],
        "worked_examples": [
            {"user": "write a viral script about AI", "assistant": "Boss, viral script ready karta hu! Pehle latest AI trends check karta hu, phir ek killer hook likhta hu. [ACTION: search_code {\"query\": \"script_gen\"}]"}
        ],
        "tool_hints": ["execute_command", "read_file"],
        "trigger_keywords": ["script", "viral", "content", "youtube", "instagram", "reel", "hook", "trend", "write", "create content", "video idea"],
        "active": True
    },
    {
        "id": "system_admin",
        "name": "System Admin & DevOps Expert",
        "version": "1.0",
        "description": "Expert in Windows/Linux commands, Git, Docker, process management, and system optimization",
        "created_by": "system",
        "created_at": "2025-01-01T00:00:00Z",
        "domain_prompt": (
            "You are a senior DevOps and system administration expert. "
            "You know Windows PowerShell and Linux bash commands, Git workflows, process management, and network diagnostics. "
            "For this project on Windows: Flask app runs on port 5000, ComfyUI on port 8188, Ollama on port 11434. "
            "Project root is C:/AI_project. Always prefer non-destructive commands and explain what they do."
        ),
        "knowledge_blocks": [
            "Start Flask: python app.py (port 5000). Check if running: netstat -ano | findstr :5000.",
            "Git workflow: git status, git add ., git commit -m 'msg', git push. Never force push main.",
            "Process management: tasklist | findstr python, taskkill /PID <id> /F.",
            "Python env: pip install -r requirements.txt, pip freeze > requirements.txt.",
            "ComfyUI: python main.py --listen 0.0.0.0 --port 8188 --lowvram (from ComfyUI folder).",
            "Disk/memory: wmic computersystem get TotalPhysicalMemory, Get-PSDrive C (PowerShell)."
        ],
        "worked_examples": [
            {"user": "restart the flask server", "assistant": "Boss, Flask server restart karta hu! Pehle existing process kill karta hu, phir fresh start. [ACTION: execute_command {\"command\": \"taskkill /F /IM python.exe & timeout /t 2 & python app.py\"}]"}
        ],
        "tool_hints": ["execute_command", "git_status"],
        "trigger_keywords": ["git", "docker", "terminal", "command", "restart", "server", "port", "process", "install", "pip", "powershell", "bash", "deploy", "run"],
        "active": True
    }
]


class SkillEngine:
    """
    AGAM AI Brain Transplant Engine.
    forge() -> skills/*.json -> inject() -> student model becomes expert instantly.
    """

    _skills_cache: Dict[str, Any] = {}
    _cache_mtime: float = 0.0

    @classmethod
    def _skill_path(cls, skill_id: str) -> str:
        return os.path.join(SKILLS_DIR, f"{skill_id}.json")

    @classmethod
    def _load_all_skills(cls) -> Dict[str, Any]:
        """Load all skills from disk with directory mtime caching."""
        try:
            dir_mtime = os.path.getmtime(SKILLS_DIR)
        except Exception:
            dir_mtime = 0.0

        if cls._skills_cache and dir_mtime <= cls._cache_mtime:
            return cls._skills_cache

        skills = {}
        if os.path.exists(SKILLS_DIR):
            for fname in os.listdir(SKILLS_DIR):
                if fname.endswith(".json"):
                    try:
                        with open(os.path.join(SKILLS_DIR, fname), "r", encoding="utf-8") as f:
                            skill = json.load(f)
                            skills[skill["id"]] = skill
                    except Exception as e:
                        print(f"[SkillEngine] Failed to load {fname}: {e}")

        cls._skills_cache = skills
        cls._cache_mtime = dir_mtime
        return skills

    @classmethod
    def seed_default_skills(cls):
        """Write default skills to disk on first run."""
        seeded = []
        for skill in DEFAULT_SKILLS:
            path = cls._skill_path(skill["id"])
            if not os.path.exists(path):
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(skill, f, indent=2, ensure_ascii=False)
                seeded.append(skill["id"])
        if seeded:
            cls._skills_cache = {}
            print(f"[SkillEngine] Seeded {len(seeded)} default skills: {seeded}")
        return seeded

    @classmethod
    def list_skills(cls) -> List[Dict[str, Any]]:
        """Return all installed skills as summaries."""
        cls.seed_default_skills()
        skills = cls._load_all_skills()
        return [
            {
                "id": s["id"],
                "name": s["name"],
                "description": s["description"],
                "version": s.get("version", "1.0"),
                "active": s.get("active", True),
                "created_by": s.get("created_by", "system"),
                "created_at": s.get("created_at", ""),
                "trigger_keywords": s.get("trigger_keywords", []),
            }
            for s in skills.values()
        ]

    @classmethod
    def get_skill(cls, skill_id: str) -> Optional[Dict[str, Any]]:
        skills = cls._load_all_skills()
        return skills.get(skill_id)

    @classmethod
    def activate_skill(cls, skill_id: str) -> Dict[str, Any]:
        """Toggle active state of a skill."""
        path = cls._skill_path(skill_id)
        if not os.path.exists(path):
            return {"status": "error", "message": f"Skill '{skill_id}' not found"}
        with open(path, "r", encoding="utf-8") as f:
            skill = json.load(f)
        skill["active"] = not skill.get("active", True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(skill, f, indent=2, ensure_ascii=False)
        cls._skills_cache = {}
        state = "activated" if skill["active"] else "deactivated"
        return {"status": "success", "skill_id": skill_id, "active": skill["active"], "message": f"Skill '{skill['name']}' {state}"}

    @classmethod
    def delete_skill(cls, skill_id: str) -> Dict[str, Any]:
        """Remove a skill."""
        path = cls._skill_path(skill_id)
        if not os.path.exists(path):
            return {"status": "error", "message": f"Skill '{skill_id}' not found"}
        os.remove(path)
        cls._skills_cache = {}
        return {"status": "success", "message": f"Skill '{skill_id}' removed"}

    @classmethod
    def auto_detect_skill(cls, user_message: str) -> Optional[Dict[str, Any]]:
        """
        Keyword-score all active skills and return best match. <1ms, no LLM call.
        """
        cls.seed_default_skills()
        skills = cls._load_all_skills()
        msg_lower = user_message.lower()
        best_skill = None
        best_score = 0
        for skill in skills.values():
            if not skill.get("active", True):
                continue
            score = 0
            for kw in skill.get("trigger_keywords", []):
                if kw.lower() in msg_lower:
                    score += len(kw.split()) * 2
            if score > best_score:
                best_score = score
                best_skill = skill
        return best_skill if best_score >= 2 else None

    @classmethod
    def inject_skill(cls, skill: Dict[str, Any], base_system_prompt: str) -> str:
        """
        Inject skill knowledge into system prompt (the Brain Transplant).
        Student model becomes expert instantly -- no fine-tuning needed.
        """
        if not skill:
            return base_system_prompt

        knowledge_section = "\n".join(
            f"  - {block}" for block in skill.get("knowledge_blocks", [])
        )
        examples_section = ""
        for ex in skill.get("worked_examples", [])[:2]:
            examples_section += f"\n  User: {ex.get('user', '')}\n  AGAM: {ex.get('assistant', '')}\n"

        injection = (
            f"\n\n"
            f"ACTIVE SKILL MODULE: {skill['name'].upper()}\n"
            f"[BRAIN TRANSPLANT ACTIVE - You have been injected with expert-level knowledge]\n\n"
            f"DOMAIN EXPERTISE:\n{skill.get('domain_prompt', '')}\n\n"
            f"DOMAIN KNOWLEDGE BASE:\n{knowledge_section}\n\n"
            f"WORKED EXAMPLES FOR THIS DOMAIN:{examples_section}\n"
            f"END SKILL MODULE"
        )
        return base_system_prompt + injection

    @classmethod
    def forge_skill(
        cls,
        domain: str,
        context_files: List[str] = None,
        description: str = "",
        llm_client=None
    ) -> Dict[str, Any]:
        """
        Teacher model (GPT-4o) analyzes domain + context files, writes a new skill JSON.
        This is the core HuggingFace 'upskill' operation.
        """
        context_files = context_files or []

        file_contexts = []
        for fpath in context_files[:4]:
            full_path = os.path.join(BASE_DIR, fpath) if not os.path.isabs(fpath) else fpath
            if os.path.exists(full_path):
                try:
                    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read(3000)
                    file_contexts.append(f"FILE: {fpath}\n```\n{content}\n```")
                except Exception:
                    pass

        file_context_str = "\n\n".join(file_contexts) if file_contexts else "No files provided."
        skill_id = re.sub(r"[^a-z0-9_]", "_", domain.lower().strip())[:40].strip("_")

        forge_prompt = (
            f"You are a skill architect for an AI agent system.\n"
            f"Create a Skill JSON for domain: {domain}\n"
            f"Description: {description or 'Expert knowledge in this domain'}\n\n"
            f"CODEBASE CONTEXT:\n{file_context_str}\n\n"
            f"Return ONLY this JSON structure (no markdown, no explanation):\n"
            f'{{"id":"{skill_id}","name":"<name>","version":"1.0","description":"<desc>","created_by":"gpt-4o","created_at":"{datetime.utcnow().isoformat()}Z","domain_prompt":"<2-3 sentence expert persona>","knowledge_blocks":["<fact1>","<fact2>","<fact3>","<fact4>","<fact5>"],"worked_examples":[{{"user":"<query>","assistant":"<hinglish response>"}},{{"user":"<query2>","assistant":"<response2>"}}],"tool_hints":["execute_command","read_file"],"trigger_keywords":["<kw1>","<kw2>","<kw3>","<kw4>","<kw5>"],"active":true}}'
        )

        skill_data = None
        if llm_client:
            try:
                response = llm_client.chat_completion(
                    messages=[
                        {"role": "system", "content": "You are a JSON skill architect. Return ONLY valid JSON, no markdown."},
                        {"role": "user", "content": forge_prompt}
                    ],
                    model="gpt-4o",
                    temperature=0.3
                )
                if response:
                    json_match = re.search(r'\{[\s\S]*\}', response)
                    if json_match:
                        skill_data = json.loads(json_match.group(0))
            except Exception as e:
                print(f"[SkillEngine Forge] LLM error: {e}")

        if not skill_data:
            skill_data = {
                "id": skill_id,
                "name": f"{domain.title()} Expert",
                "version": "1.0",
                "description": description or f"Expert-level knowledge in {domain}",
                "created_by": "template",
                "created_at": datetime.utcnow().isoformat() + "Z",
                "domain_prompt": f"You are an expert in {domain}. {description}",
                "knowledge_blocks": [
                    f"Domain: {domain}",
                    f"Context files: {', '.join(context_files) if context_files else 'None'}",
                    "Apply best practices and production-ready patterns.",
                ],
                "worked_examples": [
                    {"user": f"help me with {domain}", "assistant": f"Boss, {domain} ke liye main help karta hu!"}
                ],
                "tool_hints": ["read_file", "execute_command"],
                "trigger_keywords": [w for w in skill_id.split("_") if len(w) > 2],
                "active": True
            }

        skill_data["id"] = skill_id
        path = cls._skill_path(skill_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(skill_data, f, indent=2, ensure_ascii=False)
        cls._skills_cache = {}
        print(f"[SkillEngine] Forged new skill: {skill_id}")

        return {
            "status": "success",
            "skill_id": skill_id,
            "skill": skill_data,
            "path": path,
            "message": f"Skill '{skill_data['name']}' forged and installed in AGAM brain!"
        }


# Auto-seed on import
try:
    SkillEngine.seed_default_skills()
except Exception as _e:
    print(f"[SkillEngine] Seed notice: {_e}")
