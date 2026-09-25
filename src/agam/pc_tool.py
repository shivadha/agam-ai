import os
import sys
import time
import socket
import subprocess
import psutil

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class PCToolkit:
    """
    PC Hardware and System Management Toolkit for AGAM.
    Provides direct access to PC vitals, process control, ComfyUI, and file system.
    """

    @staticmethod
    def get_hardware_vitals():
        """Returns real-time hardware telemetry: CPU, RAM, Disk, GPU, and OS stats."""
        # 1. CPU
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_count = psutil.cpu_count(logical=True)
        cpu_freq = psutil.cpu_freq()
        cpu_ghz = round(cpu_freq.current / 1000, 2) if cpu_freq else "N/A"

        # 2. RAM
        ram = psutil.virtual_memory()
        ram_total_gb = round(ram.total / (1024 ** 3), 2)
        ram_used_gb = round(ram.used / (1024 ** 3), 2)
        ram_free_gb = round(ram.available / (1024 ** 3), 2)
        ram_percent = ram.percent

        # 3. Disk
        disk = psutil.disk_usage(BASE_DIR[:3] if os.name == 'nt' else '/')
        disk_total_gb = round(disk.total / (1024 ** 3), 2)
        disk_used_gb = round(disk.used / (1024 ** 3), 2)
        disk_free_gb = round(disk.free / (1024 ** 3), 2)
        disk_percent = disk.percent

        # 4. GPU (NVIDIA RTX 3060 Laptop or others)
        gpu_info = {
            "available": False,
            "name": "None",
            "vram_total_mb": 0,
            "vram_used_mb": 0,
            "vram_free_mb": 0,
            "vram_percent": 0
        }

        if TORCH_AVAILABLE and torch.cuda.is_available():
            try:
                gpu_info["available"] = True
                gpu_info["name"] = torch.cuda.get_device_name(0)
                total_bytes = torch.cuda.get_device_properties(0).total_memory
                allocated_bytes = torch.cuda.memory_allocated(0)
                reserved_bytes = torch.cuda.memory_reserved(0)

                total_mb = round(total_bytes / (1024 ** 2))
                used_mb = round(reserved_bytes / (1024 ** 2))
                free_mb = max(0, total_mb - used_mb)
                vram_pct = round((used_mb / total_mb) * 100, 1) if total_mb > 0 else 0

                gpu_info.update({
                    "vram_total_mb": total_mb,
                    "vram_used_mb": used_mb,
                    "vram_free_mb": free_mb,
                    "vram_percent": vram_pct
                })
            except Exception as e:
                gpu_info["name"] = f"CUDA Error: {e}"
        else:
            # Fallback to nvidia-smi if available
            try:
                res = subprocess.run(
                    ["nvidia-smi", "--query-gpu=gpu_name,memory.total,memory.used,memory.free", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=2
                )
                if res.returncode == 0 and res.stdout.strip():
                    parts = [p.strip() for p in res.stdout.strip().split(",")]
                    gpu_info["available"] = True
                    gpu_info["name"] = parts[0]
                    gpu_info["vram_total_mb"] = int(parts[1])
                    gpu_info["vram_used_mb"] = int(parts[2])
                    gpu_info["vram_free_mb"] = int(parts[3])
                    gpu_info["vram_percent"] = round((gpu_info["vram_used_mb"] / gpu_info["vram_total_mb"]) * 100, 1)
            except Exception:
                pass

        # 5. Services Status
        comfyui_running = PCToolkit.is_port_listening(8188)
        ollama_running = PCToolkit.is_port_listening(11434)

        return {
            "cpu": {
                "usage_percent": cpu_percent,
                "cores": cpu_count,
                "frequency_ghz": cpu_ghz
            },
            "ram": {
                "total_gb": ram_total_gb,
                "used_gb": ram_used_gb,
                "free_gb": ram_free_gb,
                "percent": ram_percent
            },
            "disk": {
                "total_gb": disk_total_gb,
                "used_gb": disk_used_gb,
                "free_gb": disk_free_gb,
                "percent": disk_percent
            },
            "gpu": gpu_info,
            "services": {
                "comfyui": {
                    "running": comfyui_running,
                    "port": 8188,
                    "url": "http://127.0.0.1:8188"
                },
                "ollama": {
                    "running": ollama_running,
                    "port": 11434,
                    "url": "http://127.0.0.1:11434"
                }
            },
            "os": {
                "platform": sys.platform,
                "python_version": sys.version.split()[0],
                "workspace": BASE_DIR
            }
        }

    @staticmethod
    def is_port_listening(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
        """Quick check if a local port is listening."""
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False

    @staticmethod
    def launch_comfyui():
        """Launches ComfyUI in the background if not already running."""
        if PCToolkit.is_port_listening(8188):
            return {"status": "already_running", "message": "ComfyUI is already running on http://127.0.0.1:8188"}

        bat_path = os.path.join(BASE_DIR, "start_comfyui.bat")
        if not os.path.exists(bat_path):
            return {"status": "error", "message": f"Script not found: {bat_path}"}

        try:
            # Spawn in background detached
            if os.name == 'nt':
                subprocess.Popen(
                    ["cmd.exe", "/c", bat_path],
                    cwd=BASE_DIR,
                    creationflags=subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS
                )
            else:
                subprocess.Popen(["bash", bat_path], cwd=BASE_DIR)

            # Wait briefly to check if it started listening
            time.sleep(2)
            is_up = PCToolkit.is_port_listening(8188)
            return {
                "status": "launched",
                "listening": is_up,
                "message": "ComfyUI launch command dispatched successfully! Initializing model engine."
            }
        except Exception as e:
            return {"status": "error", "message": f"Failed to start ComfyUI: {e}"}

    @staticmethod
    def open_in_explorer(relative_or_abs_path: str = ""):
        """Opens a file or directory in Windows File Explorer."""
        if not relative_or_abs_path:
            target = BASE_DIR
        elif os.path.isabs(relative_or_abs_path):
            target = relative_or_abs_path
        else:
            target = os.path.normpath(os.path.join(BASE_DIR, relative_or_abs_path))

        if not os.path.exists(target):
            return {"status": "error", "message": f"Path does not exist: {target}"}

        try:
            if os.name == 'nt':
                os.startfile(target)
            else:
                subprocess.Popen(["xdg-open", target])
            return {"status": "success", "message": f"Opened in File Explorer: {target}", "path": target}
        except Exception as e:
            return {"status": "error", "message": f"Could not open explorer: {e}"}

    @staticmethod
    def get_process_summary():
        """Returns top resource consuming processes."""
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                info = p.info
                if info['name'] and any(k in info['name'].lower() for k in ['python', 'node', 'code', 'comfy', 'ollama', 'chrome', 'msedge']):
                    procs.append({
                        "pid": info['pid'],
                        "name": info['name'],
                        "cpu_percent": round(info['cpu_percent'] or 0, 1),
                        "memory_percent": round(info['memory_percent'] or 0, 1)
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        procs.sort(key=lambda x: x['cpu_percent'], reverse=True)
        return procs[:8]
