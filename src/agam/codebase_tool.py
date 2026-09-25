import os
import glob
from typing import Dict, Any, List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

IGNORED_DIRS = {
    '.git', '__pycache__', 'node_modules', '.venv', 'venv', 
    '.gemini', '.idea', '.vscode', 'dist', 'build'
}

ALLOWED_EXTENSIONS = {
    '.py', '.js', '.html', '.css', '.json', '.bat', '.ps1', 
    '.md', '.txt', '.env', '.sql', '.yml', '.yaml'
}

class CodebaseToolkit:
    """
    Codebase Intelligence and File Explorer for AGAM.
    Allows AGAM to read, inspect, search, and explain any file in c:\\AI_project.
    """

    @staticmethod
    def get_project_tree(max_depth: int = 3) -> Dict[str, Any]:
        """Generates a hierarchical directory tree of the project."""
        def build_tree(current_path: str, depth: int):
            if depth > max_depth:
                return {"name": os.path.basename(current_path), "type": "dir", "truncated": True}

            items = []
            try:
                for entry in sorted(os.scandir(current_path), key=lambda e: (not e.is_dir(), e.name.lower())):
                    if entry.name in IGNORED_DIRS:
                        continue
                    if entry.is_dir():
                        items.append(build_tree(entry.path, depth + 1))
                    else:
                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext in ALLOWED_EXTENSIONS or entry.name in {'.env', 'requirements.txt'}:
                            items.append({
                                "name": entry.name,
                                "type": "file",
                                "size_bytes": entry.stat().st_size,
                                "path": os.path.relpath(entry.path, BASE_DIR).replace("\\", "/")
                            })
            except PermissionError:
                pass

            return {
                "name": os.path.basename(current_path) or "root",
                "type": "dir",
                "path": os.path.relpath(current_path, BASE_DIR).replace("\\", "/"),
                "children": items
            }

        return build_tree(BASE_DIR, 1)

    @staticmethod
    def read_code_file(relative_path: str, max_lines: int = 300) -> Dict[str, Any]:
        """Safely reads content of a project file."""
        clean_rel = relative_path.replace("/", os.sep).replace("\\", os.sep).lstrip(os.sep)
        full_path = os.path.normpath(os.path.join(BASE_DIR, clean_rel))

        # Security check: ensure path stays inside BASE_DIR
        if not full_path.startswith(BASE_DIR):
            return {"status": "error", "message": "Access denied: Path is outside project directory."}

        if not os.path.exists(full_path):
            return {"status": "error", "message": f"File not found: {clean_rel}"}

        if os.path.isdir(full_path):
            return {"status": "error", "message": f"Path is a directory, not a file: {clean_rel}"}

        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            total_lines = len(lines)
            content = "".join(lines[:max_lines])
            is_truncated = total_lines > max_lines

            return {
                "status": "success",
                "path": clean_rel.replace("\\", "/"),
                "total_lines": total_lines,
                "showing_lines": min(total_lines, max_lines),
                "is_truncated": is_truncated,
                "content": content
            }
        except Exception as e:
            return {"status": "error", "message": f"Error reading file: {e}"}

    @staticmethod
    def analyze_file_semantics(relative_path: str) -> Dict[str, Any]:
        """Deeply inspects file semantics: routes, functions, classes, imports, and purpose."""
        import re
        res = CodebaseToolkit.read_code_file(relative_path, max_lines=1200)
        if res.get("status") != "success":
            return res

        content = res.get("content", "")
        lines = content.splitlines()
        filename = os.path.basename(res.get("path", ""))

        routes = []
        functions = []
        classes = []
        imports = []
        ports = []

        for line in lines:
            line_str = line.strip()
            # Routes
            if "@app.route" in line_str or "@router." in line_str:
                m = re.search(r"['\"](/[^'\"]*)['\"]", line_str)
                if m:
                    routes.append(m.group(1))
            # Classes
            elif line_str.startswith("class ") and ":" in line_str:
                cname = line_str.split("class ")[1].split("(")[0].split(":")[0].strip()
                classes.append(cname)
            # Functions
            elif line_str.startswith("def ") and "(" in line_str:
                fname = line_str.split("def ")[1].split("(")[0].strip()
                if not fname.startswith("__"):
                    functions.append(fname)
            # Imports
            elif line_str.startswith("import ") or line_str.startswith("from "):
                parts = line_str.split()
                if len(parts) > 1:
                    pkg = parts[1].split(".")[0]
                    if pkg not in imports and pkg not in {"os", "sys", "re", "json", "time"}:
                        imports.append(pkg)
            # Ports
            port_match = re.search(r"\b(?:port|PORT)\s*[=:]\s*(\d{4,5})\b", line_str)
            if port_match and port_match.group(1) not in ports:
                ports.append(port_match.group(1))
            # ComfyUI/bat flags
            if "--port" in line_str:
                pm = re.search(r"--port\s+(\d{4,5})", line_str)
                if pm and pm.group(1) not in ports:
                    ports.append(pm.group(1))

        return {
            "status": "success",
            "path": res.get("path"),
            "filename": filename,
            "total_lines": res.get("total_lines"),
            "routes": routes[:15],
            "functions": functions[:15],
            "classes": classes[:10],
            "key_imports": imports[:10],
            "ports_detected": ports,
            "sample_content": content[:2000]
        }

    @staticmethod
    def search_codebase(query: str, max_results: int = 25) -> List[Dict[str, Any]]:
        """Searches across project source files for a given keyword or pattern."""
        results = []
        q_lower = query.lower()

        for root, dirs, files in os.walk(BASE_DIR):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext not in ALLOWED_EXTENSIONS:
                    continue

                filepath = os.path.join(root, file)
                rel_path = os.path.relpath(filepath, BASE_DIR).replace("\\", "/")

                try:
                    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                        for line_idx, line in enumerate(f, start=1):
                            if q_lower in line.lower():
                                results.append({
                                    "file": rel_path,
                                    "line": line_idx,
                                    "snippet": line.strip()[:160]
                                })
                                if len(results) >= max_results:
                                    return results
                except Exception:
                    continue

        return results

    @staticmethod
    def list_directory(relative_path: str = ".") -> Dict[str, Any]:
        """Lists files and folders inside a specific directory."""
        clean_rel = relative_path.replace("/", os.sep).replace("\\", os.sep).strip(os.sep)
        full_path = os.path.normpath(os.path.join(BASE_DIR, clean_rel)) if clean_rel and clean_rel != "." else BASE_DIR

        if not full_path.startswith(BASE_DIR):
            return {"status": "error", "message": "Access denied: Path is outside project directory."}

        if not os.path.exists(full_path):
            return {"status": "error", "message": f"Directory not found: {clean_rel}"}

        if not os.path.isdir(full_path):
            return {"status": "error", "message": f"Path is not a directory: {clean_rel}"}

        try:
            entries = []
            for e in sorted(os.scandir(full_path), key=lambda x: (not x.is_dir(), x.name.lower())):
                if e.name in IGNORED_DIRS:
                    continue
                entries.append({
                    "name": e.name,
                    "is_dir": e.is_dir(),
                    "size_bytes": e.stat().st_size if not e.is_dir() else None,
                    "path": os.path.relpath(e.path, BASE_DIR).replace("\\", "/")
                })
            return {
                "status": "success",
                "path": clean_rel.replace("\\", "/") or "root",
                "count": len(entries),
                "items": entries
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @staticmethod
    def write_code_file(relative_path: str, content: str, overwrite: bool = True) -> Dict[str, Any]:
        """Creates or updates a file in the project workspace."""
        clean_rel = relative_path.replace("/", os.sep).replace("\\", os.sep).lstrip(os.sep)
        full_path = os.path.normpath(os.path.join(BASE_DIR, clean_rel))

        if not full_path.startswith(BASE_DIR):
            return {"status": "error", "message": "Access denied: Path is outside project directory."}

        if os.path.exists(full_path) and not overwrite:
            return {"status": "error", "message": f"File already exists and overwrite is False: {clean_rel}"}

        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8", errors="replace") as f:
                f.write(content)
            return {
                "status": "success",
                "path": clean_rel.replace("\\", "/"),
                "bytes_written": len(content.encode("utf-8")),
                "lines": len(content.splitlines()),
                "message": f"Successfully wrote {len(content.splitlines())} lines to {clean_rel}."
            }
        except Exception as e:
            return {"status": "error", "message": f"Failed to write file: {e}"}

    @staticmethod
    def edit_code_file(relative_path: str, target_content: str, replacement_content: str) -> Dict[str, Any]:
        """Replaces target_content with replacement_content in a file."""
        clean_rel = relative_path.replace("/", os.sep).replace("\\", os.sep).lstrip(os.sep)
        full_path = os.path.normpath(os.path.join(BASE_DIR, clean_rel))

        if not full_path.startswith(BASE_DIR):
            return {"status": "error", "message": "Access denied: Path is outside project directory."}

        if not os.path.exists(full_path):
            return {"status": "error", "message": f"File not found: {clean_rel}"}

        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                existing = f.read()

            if target_content not in existing:
                return {
                    "status": "error",
                    "message": f"Target content not found in {clean_rel}. Ensure exact match."
                }

            count = existing.count(target_content)
            new_content = existing.replace(target_content, replacement_content, 1)

            with open(full_path, "w", encoding="utf-8", errors="replace") as f:
                f.write(new_content)

            return {
                "status": "success",
                "path": clean_rel.replace("\\", "/"),
                "occurrences_matched": count,
                "message": f"Successfully updated {clean_rel}."
            }
        except Exception as e:
            return {"status": "error", "message": f"Failed to edit file: {e}"}

    @staticmethod
    def execute_terminal_command(command: str, timeout: int = 30) -> Dict[str, Any]:
        """Safely executes a PowerShell or CMD command in the project workspace."""
        import subprocess

        # Basic guard against catastrophic accidental format commands
        dangerous = ["format c:", "del /f /s /q c:\\", "rmdir /s /q c:\\windows", "rd /s /q c:\\"]
        for d in dangerous:
            if d in command.lower():
                return {"status": "error", "message": "Command blocked by AGAM safety guardrail."}

        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace"
            )
            stdout = proc.stdout.strip()[:4000] if proc.stdout else ""
            stderr = proc.stderr.strip()[:2000] if proc.stderr else ""
            return {
                "status": "success" if proc.returncode == 0 else "error",
                "returncode": proc.returncode,
                "command": command,
                "stdout": stdout,
                "stderr": stderr,
                "output": stdout if stdout else (stderr if stderr else "(command completed with no output)")
            }
        except subprocess.TimeoutExpired:
            return {"status": "error", "message": f"Command timed out after {timeout} seconds."}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @staticmethod
    def get_git_status() -> Dict[str, Any]:
        """Returns current git branch and status."""
        return CodebaseToolkit.execute_terminal_command("git status --short; git branch --show-current", timeout=10)

    @staticmethod
    def get_codebase_summary() -> Dict[str, Any]:
        """Provides an architectural overview of PulseForge AI and its modules."""
        return {
            "project_name": "PulseForge AI",
            "description": "Autonomous AI Vertical Video & YouTube Automation Engine with DAG Workflow Orchestrator and ComfyUI/Diffusers pipelines.",
            "core_modules": [
                {
                    "name": "Flask App (app.py)",
                    "role": "Web UI, REST APIs, authentication, trend scrapers, and workflow execution endpoints."
                },
                {
                    "name": "Workflow Engine (src/engine/orchestrator.py)",
                    "role": "Topological DAG executor running article triggers, viral hook generation, script synthesis, TTS, ComfyUI video rendering, and assembly."
                },
                {
                    "name": "Script & Viral Brain (src/backend/script_gen.py, viral_reel_brain.py)",
                    "role": "Crafts high-retention 9:16 scripts, retention loops, image prompts, and motion directives using Frontier LLMs."
                },
                {
                    "name": "ComfyUI & Diffusers (ComfyUI/, src/backend/video_gen_ai.py)",
                    "role": "Local AI generation using NVIDIA RTX 3060 6GB with Wan 2.1 & LTX-Video models on port 8188."
                },
                {
                    "name": "Voice & Audio (src/backend/voice_gen.py, music_engine.py, sfx_engine.py)",
                    "role": "Synthesizes multi-lingual neural speech (Edge-TTS) with dynamic subtitle timing (.srt/.vtt) and cinematic soundtrack mixing."
                },
                {
                    "name": "Video Assembler (src/backend/video_assembler.py)",
                    "role": "Final composition with MoviePy/FFmpeg, burn-in kinetic subtitles, transition zooms, sound effects, and 1080x1920 export."
                },
                {
                    "name": "YouTube Syndication (src/backend/youtube_upload.py, youtube_automator.py)",
                    "role": "OAuth2 authenticated video upload with automated titles, descriptions, and hashtags."
                }
            ],
            "hardware_target": "NVIDIA GeForce RTX 3060 Laptop GPU (6GB VRAM), Local Windows Machine"
        }
