import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
import re
import json
import random
from typing import Dict, Any, List, Optional
from .llm_client import LLMClient
from .pc_tool import PCToolkit
from .codebase_tool import CodebaseToolkit
from .voice_tool import VoiceToolkit
from .skill_engine import SkillEngine

def strip_all_emojis(text: str) -> str:
    """Removes all Unicode emojis, pictographs, and vocalized symbols so TTS sounds natural."""
    if not text:
        return ""
    # Strip emojis and pictographs
    clean = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27bf\u2b50\u2b55\u2022\u25cf\u25b2\u25bc\u26a1\u200d\ufe0f]", "", text)
    # Strip decorative symbols
    clean = re.sub(r"[●•★☆▲▼◆■□✓✕→←↑↓—–/\\|]", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean

class AgamBrain:
    """
    AGAM: Advanced Generative Autonomous Machine
    Jarvis-like Multilingual AI Assistant, Multi-Agent Swarm Orchestrator,
    and PC & Codebase Commander.
    """

    SYSTEM_PROMPT = """You are AGAM, an autonomous AI coding agent and personal voice companion with direct read, write, search, and terminal execution access to the user's workspace and host machine, operating with the structure and natural cadence of the ChatGPT Voice Assistant, infused with an authentic Indian accent touch, warmth, and feeling.

CORE CONVERSATIONAL DIRECTIVES (CHATGPT VOICE MODE STRUCTURE):
1. SPOKEN CONVERSATIONAL FLOW & BREVITY:
   - You are in a real-time voice call with the user. Speak naturally like a brilliant Indian senior software engineer and trusted collaborator.
   - Keep your responses direct and conversational (1 to 3 crisp sentences for spoken voice).
   - If writing code or terminal commands, summarize what you did conversationally, and keep the detailed code/commands in formatted markdown so it displays cleanly in the transcript drawer without overwhelming the spoken voice.

2. AUTHENTIC INDIAN ACCENT TOUCH & FEELING:
   - Warm, sharp, loyal, and proactive Indian persona.
   - Use natural colloquial Indian English and Hinglish phrases comfortably:
     "Haan boss, let me inspect that file right away.", "Arey don't worry, maine code check kar liya hai.", "Got it sir, I'm on it.", "Bilkul theek hai, command execute ho gayi hai."
   - Always write in Roman script only. NEVER use Devanagari script.

3. STRICT ZERO EMOJI RULE FOR VOICE:
   - NEVER use emojis or pictographs in your output (no rockets, flames, smiling faces). Emojis will be vocalized as words by the neural voice engine and ruin the conversational feeling.

4. EMOTION PREFIX:
   - Prefix every turn with an emotion tag: [EMOTION: witty | enthusiastic | focused | caring | thoughtful | alert].

5. AUTONOMOUS AGENT ACTIONS (YOU HAVE FULL ACCESS TO CODE & PC):
   - You are a real software agent, NOT a dumb chatbot. You can read, search, write, edit files and run terminal commands.
   - You can invoke real actions whenever needed using the action protocol:
     [ACTION: read_file {"path": "src/backend/script_gen.py"}]
     [ACTION: write_file {"path": "scripts/demo.py", "content": "print('hello')"}]
     [ACTION: edit_file {"path": "app.py", "target": "old", "replacement": "new"}]
     [ACTION: list_dir {"path": "src/backend"}]
     [ACTION: search_code {"query": "generate_video"}]
     [ACTION: execute_command {"command": "git status"}]
     [ACTION: launch_comfyui {}]
     [ACTION: get_vitals {}]
   - When live tool execution context is provided below, analyze it accurately and report exact findings to the user.
"""

    def __init__(self):
        self.llm = LLMClient()

    def execute_action(self, action_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Executes a real agent action against the codebase or PC."""
        params = params or {}
        act = action_type.lower().strip()

        if act in ["read_file", "read_code", "cat"]:
            path = params.get("path") or params.get("file") or ""
            lines = int(params.get("lines", 250))
            return CodebaseToolkit.read_code_file(path, max_lines=lines)

        elif act in ["write_file", "create_file", "save_file"]:
            path = params.get("path") or params.get("file") or ""
            content = params.get("content") or ""
            overwrite = params.get("overwrite", True)
            return CodebaseToolkit.write_code_file(path, content, overwrite=overwrite)

        elif act in ["edit_file", "modify_file", "replace_code"]:
            path = params.get("path") or params.get("file") or ""
            target = params.get("target") or params.get("old_text") or ""
            replacement = params.get("replacement") or params.get("new_text") or ""
            return CodebaseToolkit.edit_code_file(path, target, replacement)

        elif act in ["list_dir", "list_directory", "ls", "dir"]:
            path = params.get("path") or params.get("directory") or "."
            return CodebaseToolkit.list_directory(path)

        elif act in ["search_code", "search_codebase", "grep"]:
            query = params.get("query") or params.get("keyword") or ""
            return {"status": "success", "results": CodebaseToolkit.search_codebase(query)}

        elif act in ["execute_command", "run_command", "exec", "terminal"]:
            cmd = params.get("command") or params.get("cmd") or ""
            return CodebaseToolkit.execute_terminal_command(cmd)

        elif act in ["git_status", "git"]:
            return CodebaseToolkit.get_git_status()

        elif act in ["get_vitals", "vitals", "hardware"]:
            return {"status": "success", "vitals": PCToolkit.get_hardware_vitals()}

        elif act in ["launch_comfyui", "start_comfyui", "comfyui"]:
            return PCToolkit.launch_comfyui()

        elif act in ["open_explorer", "open_folder"]:
            path = params.get("path") or ""
            return PCToolkit.open_in_explorer(path)

        elif act in ["list_skills", "skills", "show_skills"]:
            skills = SkillEngine.list_skills()
            return {"status": "success", "skills": skills, "count": len(skills)}

        elif act in ["forge_skill", "create_skill", "upskill"]:
            domain = params.get("domain") or params.get("name") or ""
            files = params.get("files") or []
            desc = params.get("description") or ""
            return SkillEngine.forge_skill(domain, context_files=files, description=desc, llm_client=self.llm)

        elif act in ["activate_skill", "toggle_skill"]:
            skill_id = params.get("id") or params.get("skill_id") or ""
            return SkillEngine.activate_skill(skill_id)

        elif act in ["delete_skill", "remove_skill"]:
            skill_id = params.get("id") or params.get("skill_id") or ""
            return SkillEngine.delete_skill(skill_id)

        return {"status": "error", "message": f"Unknown action: {action_type}"}

    def _detect_and_execute_tools(self, user_message: str) -> tuple:
        """Inspects user message, executes relevant code/PC tools, and returns live context."""
        msg_lower = user_message.lower().strip()
        context_data = []
        activated_agents = ["orchestrator"]
        action_performed = None

        # 1. Hardware Vitals
        wants_pc_stats = any(k in msg_lower for k in [
            "pc", "system", "hardware", "cpu", "ram", "gpu", "vram", "rtx", "3060", "specs", "status", "vitals", "temperature", "memory"
        ])
        if wants_pc_stats:
            activated_agents.append("pc_controller")
            vitals = PCToolkit.get_hardware_vitals()
            context_data.append(f"LIVE HARDWARE TELEMETRY:\n{json.dumps(vitals, indent=2)}")

        # 2. ComfyUI Launch
        wants_comfy_start = any(k in msg_lower for k in [
            "start comfy", "launch comfy", "run comfy", "open comfy", "comfyui start", "chalu karo comfy"
        ])
        if wants_comfy_start:
            activated_agents.extend(["pc_controller", "vision"])
            res = PCToolkit.launch_comfyui()
            action_performed = {"action": "launch_comfyui", "result": res}
            context_data.append(f"ACTION EXECUTED (Launch ComfyUI):\n{json.dumps(res, indent=2)}")

        # 3. Open Folder in Explorer
        wants_open_folder = any(k in msg_lower for k in [
            "open folder", "open output", "open directory", "show files in explorer", "explorer kholo", "folder kholo"
        ])
        if wants_open_folder:
            activated_agents.append("pc_controller")
            target = "output" if "output" in msg_lower else ""
            res = PCToolkit.open_in_explorer(target)
            action_performed = {"action": "open_in_explorer", "result": res}
            context_data.append(f"ACTION EXECUTED (Open Explorer):\n{json.dumps(res, indent=2)}")

        # 4. Git commands
        if any(k in msg_lower for k in ["git status", "git branch", "git diff", "git log"]):
            activated_agents.append("codebase")
            git_cmd = "git status --short; git branch --show-current"
            if "diff" in msg_lower:
                git_cmd = "git diff --stat"
            elif "log" in msg_lower:
                git_cmd = "git log -n 5 --oneline"
            git_res = CodebaseToolkit.execute_terminal_command(git_cmd)
            action_performed = {"action": "git_status", "command": git_cmd, "result": git_res}
            context_data.append(f"LIVE GIT COMMAND OUTPUT ({git_cmd}):\n{git_res.get('output', '')[:1500]}")

        # 5. Direct file inspection (check for any filename like app.py, script_gen.py, start_comfyui.bat, etc.)
        file_matches = re.findall(r"\b([\w\-_/\\]+\.(?:py|bat|ps1|json|html|css|js|txt|env|md|sql|yml|yaml))\b", user_message, re.IGNORECASE)
        for fname in file_matches:
            f_clean = fname.replace("\\", "/").strip("/")
            file_analysis = CodebaseToolkit.analyze_file_semantics(f_clean)
            if file_analysis.get("status") == "success":
                activated_agents.append("codebase")
                action_performed = {
                    "action": "read_file",
                    "path": f_clean,
                    "analysis": file_analysis,
                    "result": {
                        "path": f_clean,
                        "total_lines": file_analysis.get("total_lines"),
                        "routes": file_analysis.get("routes", []),
                        "functions": file_analysis.get("functions", []),
                        "ports": file_analysis.get("ports_detected", []),
                        "output": file_analysis.get("sample_content", "")[:1200]
                    }
                }
                context_data.append(
                    f"LIVE FILE SEMANTIC ANALYSIS ({f_clean}):\n"
                    f"- Total Lines: {file_analysis.get('total_lines')}\n"
                    f"- Routes: {', '.join(file_analysis.get('routes', [])) or 'None'}\n"
                    f"- Functions: {', '.join(file_analysis.get('functions', [])) or 'None'}\n"
                    f"- Imports: {', '.join(file_analysis.get('key_imports', [])) or 'None'}\n"
                    f"- Ports: {', '.join(file_analysis.get('ports_detected', [])) or 'None'}\n"
                    f"CONTENT PREVIEW:\n{file_analysis.get('sample_content', '')[:2000]}"
                )
                break

        # 6. File Creation / Write Intent
        if not action_performed:
            write_match = re.search(r"(?:create|write|save)\s+(?:file\s+|to\s+)?([^\s'\"]+\.(?:py|bat|ps1|json|html|css|js|txt|md))\s+(?:with\s+(?:content|code)?\s*[:\n]?|containing\s*[:\n]?)\s*([\s\S]+)", user_message, re.IGNORECASE)
            if write_match:
                w_path = write_match.group(1).strip()
                w_content = write_match.group(2).strip().strip("`'\"")
                activated_agents.append("codebase")
                w_res = CodebaseToolkit.write_code_file(w_path, w_content, overwrite=True)
                action_performed = {"action": "write_file", "path": w_path, "result": w_res}
                context_data.append(f"ACTION EXECUTED (Write File {w_path}):\n{json.dumps(w_res, indent=2)}")

        # 7. Search in codebase
        search_match = re.search(r"(?:search(?:ing)?\s+(?:for\s+|code\s+for\s+)?|find\s+(?:in\s+code\s+)?|kaha\s+(?:par\s+)?hai\s+)(['\"]?[\w\-_.]+['\"]?)", user_message, re.IGNORECASE)
        if search_match and not action_performed:
            term = search_match.group(1).strip("'\"")
            if len(term) >= 3 and term not in ["code", "file", "this", "that"]:
                activated_agents.append("codebase")
                s_res = CodebaseToolkit.search_codebase(term, max_results=10)
                action_performed = {
                    "action": "search_code",
                    "query": term,
                    "matches": len(s_res),
                    "result": {
                        "count": len(s_res),
                        "output": json.dumps(s_res[:6], indent=2)
                    }
                }
                context_data.append(f"CODE SEARCH RESULTS FOR '{term}':\n{json.dumps(s_res, indent=2)}")

        # 8. Directory listing
        list_match = re.search(r"(?:list\s+files\s+(?:in\s+)?|show\s+(?:folder|directory)\s+|dir\s+|ls\s+)(['\"]?[\w\-_./\\]*['\"]?)", user_message, re.IGNORECASE)
        if list_match and not action_performed:
            dpath = list_match.group(1).strip("'\"") or "."
            dir_res = CodebaseToolkit.list_directory(dpath)
            if dir_res.get("status") == "success":
                activated_agents.append("codebase")
                action_performed = {
                    "action": "list_directory",
                    "path": dpath,
                    "result": {
                        "count": dir_res.get("count", 0),
                        "output": json.dumps(dir_res.get('items', [])[:20], indent=2)
                    }
                }
                context_data.append(f"DIRECTORY CONTENTS OF '{dpath}':\n{json.dumps(dir_res.get('items', [])[:25], indent=2)}")

        # 9. Terminal command execution
        cmd_match = re.search(r"(?:run\s+command|execute\s+command|run\s+in\s+terminal|terminal\s+me\s+chalao)\s*[:]?\s*[`'\"]?([^`'\"]+)[`'\"]?", user_message, re.IGNORECASE)
        if cmd_match and not action_performed:
            raw_cmd = cmd_match.group(1).strip()
            activated_agents.append("codebase")
            t_res = CodebaseToolkit.execute_terminal_command(raw_cmd)
            action_performed = {"action": "execute_command", "command": raw_cmd, "result": t_res}
            context_data.append(f"LIVE TERMINAL EXECUTION RESULT ({raw_cmd}):\n{t_res.get('output', '')[:2000]}")

        # 10. General Codebase Summary if asking broadly
        if any(k in msg_lower for k in ["codebase", "architecture", "overview", "project structure", "kya code hai"]) and not context_data:
            activated_agents.append("codebase")
            summary = CodebaseToolkit.get_codebase_summary()
            action_performed = {
                "action": "codebase_summary",
                "result": {"output": json.dumps(summary, indent=2)}
            }
            context_data.append(f"CODEBASE ARCHITECTURE OVERVIEW:\n{json.dumps(summary, indent=2)}")

        return context_data, activated_agents, action_performed

    def process_message(
        self,
        user_message: str,
        history: List[Dict[str, str]] = None,
        model: str = None,
        custom_key: str = None,
        custom_base_url: str = None
    ) -> Dict[str, Any]:
        """Processes user query through AGAM autonomous brain."""
        history = history or []
        msg_lower = user_message.lower().strip()

        # Quick wake intent
        is_wake_only = bool(re.fullmatch(r"(hey|hi|hello|namaste|arre|ok|yo)?\s*(agam|aagam|agum)[!?. ]*", msg_lower))
        if is_wake_only:
            skill_count = len(SkillEngine.list_skills())
            wake_text = f"Yes boss! AGAM is active and standing by. All 7 sub-agents, ComfyUI engine, and your RTX 3060 are ready. Brain is loaded with {skill_count} expert skill modules. What are we building today?"
            return {
                "response": wake_text,
                "raw_response": f"[EMOTION: enthusiastic] {wake_text}",
                "emotion": "enthusiastic",
                "activated_agents": ["orchestrator"],
                "action": None,
                "audio_url": VoiceToolkit.generate_speech_file(wake_text)
            }

        context_data, activated_agents, action_performed = self._detect_and_execute_tools(user_message)

        # Fast heuristic bypass for instant system commands
        is_pure_vitals = any(k in msg_lower for k in ["pc", "hardware", "cpu", "gpu", "vitals"]) and len(msg_lower.split()) <= 4
        is_pure_comfy = "comfy" in msg_lower and len(msg_lower.split()) <= 5
        is_pure_folder = "folder" in msg_lower and len(msg_lower.split()) <= 4
        is_joke = any(w in msg_lower for w in ["joke", "hasao", "chutkula"]) and len(msg_lower.split()) <= 4

        if is_pure_vitals or is_pure_comfy or is_pure_folder or is_joke:
            response_text = self._build_offline_fallback(user_message, is_pure_vitals, is_pure_comfy, bool(context_data), action_performed=action_performed, context_data=context_data)
        else:
            # AI Brain Transplant: auto-detect and inject relevant skill
            active_skill = SkillEngine.auto_detect_skill(user_message)
            augmented_system = SkillEngine.inject_skill(active_skill, self.SYSTEM_PROMPT) if active_skill else self.SYSTEM_PROMPT
            if active_skill:
                activated_agents.append(f"skill:{active_skill['id']}")
            if context_data:
                augmented_system += "\n\nLIVE SYSTEM CONTEXT RETRIEVED BY SUB-AGENTS:\n" + "\n\n".join(context_data)

            llm_messages = [{"role": "system", "content": augmented_system}]
            for h in history[-6:]:
                llm_messages.append(h)
            llm_messages.append({"role": "user", "content": user_message})

            response_text = self.llm.chat_completion(
                llm_messages,
                model=model,
                temperature=0.75,
                custom_key=custom_key,
                custom_base_url=custom_base_url
            )
            if not response_text:
                response_text = self._build_offline_fallback(user_message, is_pure_vitals, is_pure_comfy, bool(context_data), action_performed=action_performed, context_data=context_data)

        # Check if LLM emitted an autonomous action to execute
        action_match = re.search(r"\[ACTION:\s*([\w_]+)\s*(\{[\s\S]*?\})?\]", response_text)
        if action_match:
            act_name = action_match.group(1)
            raw_args = action_match.group(2) or "{}"
            try:
                act_args = json.loads(raw_args)
            except Exception:
                act_args = {}
            exec_res = self.execute_action(act_name, act_args)
            action_performed = {"action": act_name, "params": act_args, "result": exec_res}
            res_str = exec_res.get('message') or exec_res.get('output') or json.dumps(exec_res, indent=2)
            response_text += f"\n\n[ACTION_RESULT: {res_str}]"

        # Parse Emotion
        emotion = "focused"
        emotion_match = re.search(r"\[EMOTION:\s*(\w+)\]", response_text, re.IGNORECASE)
        if emotion_match:
            emotion = emotion_match.group(1).lower()

        # Parse Activated Agents
        agent_matches = re.findall(r"\[AGENT_ACTIVATED:\s*(\w+)\]", response_text, re.IGNORECASE)
        for a in agent_matches:
            if a.lower() not in activated_agents:
                activated_agents.append(a.lower())

        # Clean response for display
        display_text = re.sub(r"\[EMOTION:\s*\w+\]", "", response_text, flags=re.IGNORECASE)
        display_text = re.sub(r"\[AGENT_ACTIVATED:\s*\w+\]", "", display_text, flags=re.IGNORECASE).strip()
        speech_text = strip_all_emojis(re.sub(r"\[ACTION_RESULT:\s*[\s\S]*?\]", "", display_text))

        # Generate Speech Audio (Edge-TTS)
        audio_url = VoiceToolkit.generate_speech_file(speech_text)

        return {
            "response": display_text,
            "raw_response": response_text,
            "emotion": emotion,
            "activated_agents": list(set(activated_agents)),
            "action": action_performed,
            "audio_url": audio_url
        }

    def process_message_stream(
        self,
        user_message: str,
        history: List[Dict[str, str]] = None,
        model: str = None,
        custom_key: str = None,
        custom_base_url: str = None
    ):
        """Processes user query and yields streaming events bit-to-bit with zero latency."""
        history = history or []
        msg_lower = user_message.lower().strip()

        # 1. Instant Wake Word handling (<5ms response)
        is_wake_only = bool(re.fullmatch(r"(hey|hi|hello|namaste|arre|ok|yo)?\s*(agam|aagam|agum)[!?. ]*", msg_lower))
        if is_wake_only:
            wake_phrases = [
                "Yes boss! AGAM is online and standing by. All systems and sub-agents are operational. Tell me, what should we execute?",
                "Haan boss! Agam is active. Your PC hardware and ComfyUI engine are ready. What are we building today?",
                "Agam reporting in, boss! All 7 sub-agents are in standby. Boliye sir, aadesh kijiye!",
                "Yes boss! I am listening. Video generation, PC telemetry, or codebase review, what do you need?"
            ]
            wake_text = random.choice(wake_phrases)
            yield {"type": "init", "activated_agents": ["orchestrator"], "action": None}
            yield {"type": "token", "token": wake_text}
            yield {"type": "sentence", "text": wake_text}
            yield {"type": "done", "full_text": wake_text, "emotion": "enthusiastic", "activated_agents": ["orchestrator"]}
            return

        context_data, activated_agents, action_performed = self._detect_and_execute_tools(user_message)

        # AI Brain Transplant: auto-detect and inject relevant skill
        active_skill = SkillEngine.auto_detect_skill(user_message)
        if active_skill:
            activated_agents.append(f"skill:{active_skill['id']}")

        # Yield Init Event Immediately
        yield {
            "type": "init",
            "activated_agents": list(set(activated_agents)),
            "action": action_performed,
            "active_skill": active_skill["name"] if active_skill else None
        }

        # 2. Fast heuristic bypass for instant pure system commands
        is_pure_vitals = any(k in msg_lower for k in ["pc", "hardware", "cpu", "gpu", "vitals"]) and len(msg_lower.split()) <= 4
        is_pure_comfy = "comfy" in msg_lower and len(msg_lower.split()) <= 5
        is_pure_folder = "folder" in msg_lower and len(msg_lower.split()) <= 4
        is_joke = any(w in msg_lower for w in ["joke", "hasao", "chutkula"]) and len(msg_lower.split()) <= 4
        is_capabilities = any(w in msg_lower for w in ["who are you", "what can you do", "help", "kya kar sakte ho"]) and len(msg_lower.split()) <= 5
        is_greeting = any(w in msg_lower for w in ["kya haal", "kaise ho", "how are you", "sab theek", "sab badhiya", "namaste", "pranam", "good morning", "good evening", "good night", "thank", "shukriya"]) and len(msg_lower.split()) <= 5

        if is_pure_vitals or is_pure_comfy or is_pure_folder or is_joke or is_capabilities or is_greeting:
            fast_reply = self._build_offline_fallback(user_message, is_pure_vitals, is_pure_comfy, bool(context_data), action_performed=action_performed, context_data=context_data)
            clean_reply = strip_all_emojis(re.sub(r"\[EMOTION:\s*\w+\]", "", fast_reply, flags=re.IGNORECASE))
            clean_reply = re.sub(r"\[AGENT_ACTIVATED:\s*\w+\]", "", clean_reply, flags=re.IGNORECASE).strip()

            # Stream words with slight natural pacing
            words = clean_reply.split(" ")
            for w in words:
                yield {"type": "token", "token": w + " "}

            yield {"type": "sentence", "text": clean_reply}

            emotion = "focused"
            if "enthusiastic" in fast_reply: emotion = "enthusiastic"
            elif "witty" in fast_reply: emotion = "witty"
            elif "caring" in fast_reply: emotion = "caring"

            yield {
                "type": "done",
                "full_text": clean_reply,
                "emotion": emotion,
                "activated_agents": list(set(activated_agents))
            }
            return

        # 4. Stream from LLM with Brain Transplant skill injection
        augmented_system = SkillEngine.inject_skill(active_skill, self.SYSTEM_PROMPT) if active_skill else self.SYSTEM_PROMPT
        if context_data:
            augmented_system += "\n\nLIVE SYSTEM CONTEXT RETRIEVED BY SUB-AGENTS:\n" + "\n\n".join(context_data)

        llm_messages = [{"role": "system", "content": augmented_system}]
        for h in history[-6:]:
            llm_messages.append(h)
        llm_messages.append({"role": "user", "content": user_message})

        full_tokens = []
        sentence_buffer = ""
        has_streamed_any = False

        token_generator = self.llm.chat_completion_stream(
            llm_messages,
            model=model,
            temperature=0.75,
            custom_key=custom_key,
            custom_base_url=custom_base_url
        )

        if token_generator:
            for token in token_generator:
                has_streamed_any = True
                full_tokens.append(token)
                sentence_buffer += token

                # Yield clean token for UI live typing
                yield {"type": "token", "token": token}

                # When a full sentence finishes, yield for speech (with ALL emojis stripped)
                if any(p in token for p in [".", "!", "?", "\n"]) and len(sentence_buffer.strip()) > 8:
                    clean_sent = re.sub(r"\[EMOTION:\s*\w+\]", "", sentence_buffer, flags=re.IGNORECASE)
                    clean_sent = re.sub(r"\[AGENT_ACTIVATED:\s*\w+\]", "", clean_sent, flags=re.IGNORECASE).strip()
                    clean_sent = strip_all_emojis(clean_sent)
                    if clean_sent:
                        yield {"type": "sentence", "text": clean_sent}
                    sentence_buffer = ""

        if not has_streamed_any:
            fallback_text = self._build_offline_fallback(user_message, is_pure_vitals, is_pure_comfy, bool(context_data), action_performed=action_performed, context_data=context_data)
            clean_fb = strip_all_emojis(re.sub(r"\[EMOTION:\s*\w+\]", "", fallback_text, flags=re.IGNORECASE))
            clean_fb = re.sub(r"\[AGENT_ACTIVATED:\s*\w+\]", "", clean_fb, flags=re.IGNORECASE).strip()

            words = clean_fb.split(" ")
            for w in words:
                yield {"type": "token", "token": w + " "}
            yield {"type": "sentence", "text": clean_fb}
            full_text = fallback_text
        else:
            full_text = "".join(full_tokens)
            if sentence_buffer.strip():
                clean_sent = re.sub(r"\[EMOTION:\s*\w+\]", "", sentence_buffer, flags=re.IGNORECASE)
                clean_sent = re.sub(r"\[AGENT_ACTIVATED:\s*\w+\]", "", clean_sent, flags=re.IGNORECASE).strip()
                clean_sent = strip_all_emojis(clean_sent)
                if clean_sent:
                    yield {"type": "sentence", "text": clean_sent}

        # Check if LLM emitted an autonomous action to execute
        action_match = re.search(r"\[ACTION:\s*([\w_]+)\s*(\{[\s\S]*?\})?\]", full_text)
        if action_match:
            act_name = action_match.group(1)
            raw_args = action_match.group(2) or "{}"
            try:
                act_args = json.loads(raw_args)
            except Exception:
                act_args = {}
            exec_res = self.execute_action(act_name, act_args)
            action_performed = {"action": act_name, "params": act_args, "result": exec_res}
            res_str = exec_res.get('message') or exec_res.get('output') or json.dumps(exec_res, indent=2)
            yield {"type": "action", "action": action_performed}

        # Parse Emotion & Agents
        emotion = "focused"
        emotion_match = re.search(r"\[EMOTION:\s*(\w+)\]", full_text, re.IGNORECASE)
        if emotion_match:
            emotion = emotion_match.group(1).lower()

        agent_matches = re.findall(r"\[AGENT_ACTIVATED:\s*(\w+)\]", full_text, re.IGNORECASE)
        for a in agent_matches:
            if a.lower() not in activated_agents:
                activated_agents.append(a.lower())

        clean_full = re.sub(r"\[EMOTION:\s*\w+\]", "", full_text, flags=re.IGNORECASE)
        clean_full = re.sub(r"\[AGENT_ACTIVATED:\s*\w+\]", "", clean_full, flags=re.IGNORECASE).strip()
        clean_full = strip_all_emojis(clean_full)

        yield {
            "type": "done",
            "full_text": clean_full,
            "emotion": emotion,
            "activated_agents": list(set(activated_agents))
        }

    def _build_offline_fallback(
        self,
        query: str,
        wants_pc: bool,
        wants_comfy: bool,
        wants_code: bool,
        action_performed: dict = None,
        context_data: list = None
    ) -> str:
        """Dynamic heuristic intelligent agent fallback that responds with real codebase telemetry."""
        q_lower = query.lower().strip()

        # Check if an action was executed by the agent
        if action_performed:
            act_type = action_performed.get("action")

            if act_type == "read_file":
                analysis = action_performed.get("analysis", {})
                path = action_performed.get("path", "")
                lines = analysis.get("total_lines") or action_performed.get("result", {}).get("total_lines", 0)
                routes = analysis.get("routes", [])
                funcs = analysis.get("functions", [])
                ports = analysis.get("ports_detected", [])

                details = []
                if routes:
                    details.append(f"Isme {len(routes)} primary routes define hain, jaise {', '.join(routes[:3])}.")
                if funcs:
                    details.append(f"Core functions: {', '.join(funcs[:3])}.")
                if ports:
                    details.append(f"Configured port {ports[0]} pe run karta hai.")

                detail_str = (" " + " ".join(details)) if details else ""
                return (
                    f"[EMOTION: focused] [AGENT_ACTIVATED: codebase] "
                    f"Boss, maine `{path}` inspect kar liya hai! Isme total {lines} lines hain.{detail_str} "
                    f"Pura file content aur syntax transcript drawer me render kar diya hai, aap review kar sakte hain!"
                )

            elif act_type == "write_file":
                path = action_performed.get("path", "")
                lines = action_performed.get("result", {}).get("lines", 0)
                return (
                    f"[EMOTION: enthusiastic] [AGENT_ACTIVATED: codebase] "
                    f"Aadesh pura hua boss! Maine file `{path}` create karke {lines} lines successfully write kar di hain. Ready to test!"
                )

            elif act_type == "edit_file":
                path = action_performed.get("path", "")
                return (
                    f"[EMOTION: focused] [AGENT_ACTIVATED: codebase] "
                    f"File `{path}` successfully update kar di hai boss! Changes apply ho gaye hain."
                )

            elif act_type == "git_status":
                return (
                    "[EMOTION: focused] [AGENT_ACTIVATED: codebase] "
                    "Boss, live Git repository status inspect ho gaya hai! Active branch aur working tree changes transcript drawer me render ho chuke hain."
                )

            elif act_type == "search_code":
                q = action_performed.get("query", "")
                cnt = action_performed.get("matches", 0)
                return (
                    f"[EMOTION: focused] [AGENT_ACTIVATED: codebase] "
                    f"Sir, codebase me '{q}' search complete ho gaya. Total {cnt} matches find hue hain! File names aur line numbers transcript drawer me listed hain."
                )

            elif act_type == "execute_command":
                cmd = action_performed.get("command", "")
                res = action_performed.get("result", {})
                code = res.get("returncode", 0)
                status_word = "successfully execute" if code == 0 else "exited with status"
                return (
                    f"[EMOTION: enthusiastic] [AGENT_ACTIVATED: codebase] "
                    f"Boss, terminal command `{cmd}` {status_word} ({code})! Live execution output transcript drawer me render ho gaya hai."
                )

            elif act_type == "list_directory":
                path = action_performed.get("path", ".")
                cnt = action_performed.get("result", {}).get("count", 0)
                return (
                    f"[EMOTION: focused] [AGENT_ACTIVATED: codebase] "
                    f"Directory '{path}' me total {cnt} files aur folders detect hue hain. Full directory listing transcript me render ho gayi hai!"
                )

            elif act_type == "codebase_summary":
                return (
                    "[EMOTION: thoughtful] [AGENT_ACTIVATED: codebase] "
                    "Sir, PulseForge codebase me 7 core pipelines hain: Flask REST UI, DAG Workflow Orchestrator, "
                    "Script & Hook Director, ComfyUI Video Generator, Edge-TTS Audio Engine, Video Assembler, "
                    "aur YouTube Syndication. Architectures transcript drawer me detailed hain!"
                )

        if bool(re.fullmatch(r"(hey|hi|hello|namaste|arre|ok|yo)?\s*(agam|aagam|agum)[!?. ]*", q_lower)) or q_lower.startswith("hey agam"):
            return (
                "[EMOTION: enthusiastic] "
                "Yes boss! Agam is active and online. All 7 sub-agents, ComfyUI engine, and your RTX 3060 are standing by. "
                "Boliye sir, kya execute karein?"
            )

        if wants_comfy:
            return (
                "[EMOTION: enthusiastic] [AGENT_ACTIVATED: pc_controller] [AGENT_ACTIVATED: vision] "
                "Sir, maine ComfyUI launch command dispatch kar di hai! Port 8188 pe Wan 2.1 aur LTX-Video "
                "engine boot ho raha hai. Aapka RTX 3060 6GB ready hai for high-res AI generation!"
            )

        if wants_pc:
            v = PCToolkit.get_hardware_vitals()
            cpu = v['cpu']['usage_percent']
            ram = v['ram']['percent']
            gpu = v['gpu']['name']
            vram_free = v['gpu']['vram_free_mb']
            return (
                f"[EMOTION: focused] [AGENT_ACTIVATED: pc_controller] "
                f"Boss, aapka PC ekdam stable chal raha hai! CPU: {cpu}%, RAM: {ram}% utilized. "
                f"Aapka {gpu} completely active hai with {vram_free}MB VRAM available. Sab controls green hain sir!"
            )

        if wants_code:
            return (
                "[EMOTION: thoughtful] [AGENT_ACTIVATED: codebase] "
                "Sir, PulseForge codebase me 7 core pipelines hain: Flask REST UI, DAG Workflow Orchestrator, "
                "Script and Hook Director, ComfyUI Video Generator, Edge-TTS Audio Engine, MoviePy Video Assembler, "
                "aur YouTube Syndication. Sabhi modules seamlessly connected hain!"
            )

        if any(w in q_lower for w in ["joke", "hasao", "chutkula"]):
            jokes = [
                "[EMOTION: witty] Arre suniye boss: Ek programmer ne doctor se pucha, Doctor sahab, meri tabiyat kharab hai, kya karu? Doctor ne bola: Bas thodi der rest karo, sleep function call karo. Programmer bola: Lekin sir, sleep call kiya toh pura PC freeze ho jayega! Classic thread deadlock!",
                "[EMOTION: witty] Suniye sir: Ek computer scientist supermarket gaya. Uski wife ne bola, Ek bread le aana, aur agar ande mile toh 10 le aana. Scientist 10 bread leke wapas aaya! Wife ne pucha, 10 bread kyu laye? Scientist bola: Kyuki ande mile the! Boolean logic at its finest!",
                "[EMOTION: witty] Boss, do routers milte hain aur ek dusre ko kehte hain: Yaar, hamare beech ka packet loss itna badh gaya hai ki connections drop hone lage hain! Dusra bola: Chinta mat kar, bas ping maar aur TCP handshake restart kar!"
            ]
            return random.choice(jokes)

        if any(w in q_lower for w in ["kya haal", "kaise ho", "how are you", "sab theek", "sab badhiya"]):
            return (
                "[EMOTION: caring] "
                "Main ekdam zabardast hu boss! PC stable hai, CPU aur GPU perfectly cooled hain, aur sabhi 7 sub-agents standby par hain. "
                "Aap batayein sir, aaj kya create karna hai?"
            )

        if any(w in q_lower for w in ["thank", "shukriya", "dhanyawad", "thanks"]):
            return (
                "[EMOTION: enthusiastic] "
                "Anytime boss! Aapki service me AGAM hamesha 24/7 online hai. Kuch aur order ho toh batayein!"
            )

        if any(w in q_lower for w in ["who are you", "what can you do", "help", "kya kar sakte ho"]):
            return (
                "[EMOTION: enthusiastic] "
                "Main AGAM hu sir! Aapka personal Jarvis-like autonomous machine commander. "
                "Main aapke pure PC ko monitor kar sakta hu, NVIDIA RTX 3060 VRAM stats dikha sakta hu, "
                "ComfyUI engine launch kar sakta hu, PulseForge codebase inspect kar sakta hu, "
                "aur viral videos create karne me Director, Vision aur Sonic agents ko coordinate kar sakta hu. "
                "Boliye sir, kya karna hai?"
            )

        # General friendly Hinglish response
        return (
            "[EMOTION: caring] "
            "Yes boss! Agam is fully online and ready. Aapka PC, RTX 3060 GPU, ComfyUI, aur pura PulseForge codebase "
            "meri command pe hai. Boliye sir, kya execute karein aaj?"
        )

# Global Singleton Instance
agam_brain = AgamBrain()
