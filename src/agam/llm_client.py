import os
import json
import re
import time
import requests
from dotenv import load_dotenv

load_dotenv()

class LLMClient:
    """
    Unified High-Speed LLM Client for AGAM.
    Supports:
    1. Groq (Free, ultra-fast 800 tokens/sec: llama-3.3-70b-versatile, llama-3.1-8b-instant)
    2. Agent Router (New API / One API OpenAI-compatible endpoint)
    3. OpenRouter (Free models: llama-3.3-70b, gemini-2.0-flash, qwen)
    4. Experiential Labs / Astra (auto-disabled if 429 quota error)
    5. Local Ollama (offline fast stream)
    """

    def __init__(self):
        self.astra_disabled = False
        self.ollama_disabled = False
        self.last_ollama_check = 0
        self.load_config()

    def load_config(self):
        self.openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.groq_key = os.environ.get("GROQ_API_KEY", "").strip()
        self.agent_router_key = os.environ.get("AGENT_ROUTER_API_KEY", "").strip()
        self.agent_router_base_url = os.environ.get("AGENT_ROUTER_BASE_URL", "https://api.agentrouter.org/v1").rstrip("/")
        self.astra_key = (os.environ.get("ASTRA_API_KEY", "") or os.environ.get("EXPERIENTIAL_API_KEY", "")).strip()
        self.openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        self.default_model = os.environ.get("AGAM_MODEL", "gpt-4o").strip()

    def chat_completion(self, messages, model=None, temperature=0.7, custom_key=None, custom_base_url=None):
        """
        Sends chat completion to available provider with low latency timeouts.
        """
        self.load_config()
        model_name = model or self.default_model

        key = (custom_key or "").strip()

        # 1. Official OpenAI (sk-proj-)
        openai_cooldown = time.time() - getattr(self, 'openai_quota_exhausted', 0)
        if (key.startswith("sk-proj-") or (self.openai_key and self.openai_key.startswith("sk-proj-"))) and openai_cooldown > 180:
            oai_key = key if key.startswith("sk-proj-") else self.openai_key
            oai_model = "gpt-4o-mini" if "mini" in model_name else "gpt-4o"
            print(f"[AGAM LLM] Routing to OpenAI ({oai_model})...")
            res = self._call_openai_compat("https://api.openai.com/v1", oai_key, oai_model, messages, temperature)
            if res:
                return res
            elif getattr(self, '_last_status', 0) == 429:
                self.openai_quota_exhausted = time.time()

        # 2. Custom Key or Groq Key
        if key.startswith("gsk_") or self.groq_key:
            groq_key = key if key.startswith("gsk_") else self.groq_key
            groq_model = "llama-3.3-70b-versatile"
            print(f"[AGAM LLM] Routing to ultra-fast Groq ({groq_model})...")
            res = self._call_openai_compat("https://api.groq.com/openai/v1", groq_key, groq_model, messages, temperature)
            if res:
                return res

        # 2. Agent Router / Custom OpenAI-compatible endpoint
        ar_key = key or self.agent_router_key
        ar_base = custom_base_url or self.agent_router_base_url
        if ar_key and not ar_key.startswith("xpl_") and not ar_key.startswith("gsk_"):
            print(f"[AGAM LLM] Attempting Agent Router at {ar_base} with model {model_name}...")
            res = self._call_openai_compat(ar_base, ar_key, model_name, messages, temperature)
            if res:
                return res

        # 3. OpenRouter
        if self.openrouter_key:
            print(f"[AGAM LLM] Routing to OpenRouter with model {model_name}...")
            res = self._call_openai_compat("https://openrouter.ai/api/v1", self.openrouter_key, model_name, messages, temperature)
            if res:
                return res

        # 4. Astra (only if not blacklisted for 429)
        astra_key = (key if key.startswith("xpl_") else None) or self.astra_key
        if astra_key and not self.astra_disabled:
            print("[AGAM LLM] Routing to Experiential Labs Astra (gpt-6-astra)...")
            res = self._call_astra(astra_key, messages, temperature)
            if res:
                return res

        # 5. Local Ollama fallback
        if not self.ollama_disabled or (time.time() - self.last_ollama_check > 60):
            print(f"[AGAM LLM] Falling back to local Ollama...")
            res = self._call_ollama(model_name, messages, temperature)
            if res:
                return res

        return None

    def chat_completion_stream(self, messages, model=None, temperature=0.7, custom_key=None, custom_base_url=None):
        """
        Streams chat completion tokens in real-time.
        Yields string tokens one by one as they arrive from the model.
        """
        self.load_config()
        model_name = model or self.default_model

        key = (custom_key or "").strip()

        # 1. Official OpenAI Streaming (sk-proj-)
        openai_cooldown = time.time() - getattr(self, 'openai_quota_exhausted', 0)
        if (key.startswith("sk-proj-") or (self.openai_key and self.openai_key.startswith("sk-proj-"))) and openai_cooldown > 180:
            oai_key = key if key.startswith("sk-proj-") else self.openai_key
            oai_model = "gpt-4o-mini" if "mini" in model_name else "gpt-4o"
            print(f"[AGAM LLM Stream] Connecting to OpenAI ({oai_model})...")
            try:
                endpoint = "https://api.openai.com/v1/chat/completions"
                headers = {"Authorization": f"Bearer {oai_key}", "Content-Type": "application/json"}
                payload = {"model": oai_model, "messages": messages, "temperature": temperature, "stream": True}
                resp = requests.post(endpoint, headers=headers, json=payload, timeout=(3.0, 30.0), stream=True)
                if resp.status_code == 200:
                    for line in resp.iter_lines(decode_unicode=True):
                        if line and line.startswith("data: "):
                            raw = line[6:].strip()
                            if raw == "[DONE]":
                                break
                            try:
                                chunk = json.loads(raw)
                                delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                if delta:
                                    yield delta
                            except Exception:
                                continue
                    return
                elif resp.status_code == 429:
                    self.openai_quota_exhausted = time.time()
                    print(f"[AGAM LLM Stream] OpenAI credits exhausted ({resp.status_code}), caching cooldown and falling back.")
            except Exception as e:
                print(f"[AGAM LLM Stream] OpenAI error: {e}")

        # 2. Custom Key or Groq Key (Ultra-fast, ~100ms first token!)
        if key.startswith("gsk_") or self.groq_key:
            groq_key = key if key.startswith("gsk_") else self.groq_key
            groq_model = "llama-3.3-70b-versatile"
            print(f"[AGAM LLM Stream] Connecting to ultra-fast Groq API ({groq_model})...")
            try:
                endpoint = "https://api.groq.com/openai/v1/chat/completions"
                headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
                payload = {"model": groq_model, "messages": messages, "temperature": temperature, "stream": True}
                resp = requests.post(endpoint, headers=headers, json=payload, timeout=(3.0, 30.0), stream=True)
                if resp.status_code == 200:
                    for line in resp.iter_lines(decode_unicode=True):
                        if line and line.startswith("data: "):
                            raw = line[6:].strip()
                            if raw == "[DONE]":
                                break
                            try:
                                chunk = json.loads(raw)
                                delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                if delta:
                                    yield delta
                            except Exception:
                                continue
                    return
            except Exception as e:
                print(f"[AGAM LLM Stream] Groq error: {e}")

        # 2. Agent Router / Custom OpenAI-compatible endpoint
        ar_key = key or self.agent_router_key
        ar_base = custom_base_url or self.agent_router_base_url
        if ar_key and not ar_key.startswith("xpl_") and not ar_key.startswith("gsk_"):
            print(f"[AGAM LLM Stream] Connecting to Agent Router at {ar_base}...")
            try:
                endpoint = f"{ar_base}/chat/completions" if not ar_base.endswith("/chat/completions") else ar_base
                headers = {"Authorization": f"Bearer {ar_key}", "Content-Type": "application/json"}
                payload = {"model": model_name, "messages": messages, "temperature": temperature, "stream": True}
                resp = requests.post(endpoint, headers=headers, json=payload, timeout=(3.0, 30.0), stream=True)
                if resp.status_code == 200:
                    for line in resp.iter_lines(decode_unicode=True):
                        if line and line.startswith("data: "):
                            raw = line[6:].strip()
                            if raw == "[DONE]":
                                break
                            try:
                                chunk = json.loads(raw)
                                delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                if delta:
                                    yield delta
                            except Exception:
                                continue
                    return
                else:
                    print(f"[AGAM LLM Stream] Agent Router returned {resp.status_code}")
            except Exception as e:
                print(f"[AGAM LLM Stream] Agent Router error: {e}")

        # 3. Experiential Labs / Astra (skip if disabled or 429)
        astra_key = (key if key.startswith("xpl_") else None) or self.astra_key
        if astra_key and not self.astra_disabled:
            print("[AGAM LLM Stream] Connecting to Astra...")
            try:
                headers = {"Authorization": f"Bearer {astra_key.strip().rstrip('|')}", "Content-Type": "application/json"}
                payload = {"model": "gpt-6-astra", "messages": messages, "temperature": temperature, "stream": True}
                resp = requests.post("https://api.experientiallabs.ai/v1/chat/completions", headers=headers, json=payload, timeout=(2.0, 15.0), stream=True)
                if resp.status_code == 200:
                    for line in resp.iter_lines(decode_unicode=True):
                        if line and line.startswith("data: "):
                            raw = line[6:].strip()
                            if raw == "[DONE]":
                                break
                            try:
                                chunk = json.loads(raw)
                                delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                if delta:
                                    yield delta
                            except Exception:
                                continue
                    return
                elif resp.status_code in [401, 403, 429]:
                    print(f"[AGAM LLM Stream] Astra disabled (status {resp.status_code}: card or quota required)")
                    self.astra_disabled = True
            except Exception as e:
                print(f"[AGAM LLM Stream] Astra error: {e}")
                self.astra_disabled = True

        # 4. Local Ollama Streaming (check connection quickly)
        if not self.ollama_disabled or (time.time() - self.last_ollama_check > 60):
            print("[AGAM LLM Stream] Trying local Ollama stream...")
            ollama_model = "qwen2.5-coder:7b"
            if "deepseek" in model_name.lower():
                ollama_model = "deepseek-r1:latest"
            elif "qwen" in model_name.lower():
                ollama_model = "qwen2.5-coder:7b"

            system_content = ""
            chat_msgs = []
            for m in messages:
                if m.get("role") == "system":
                    system_content += m.get("content", "") + "\n"
                else:
                    chat_msgs.append(m)

            try:
                payload = {
                    "model": ollama_model,
                    "messages": ([{"role": "system", "content": system_content.strip()}] if system_content else []) + chat_msgs,
                    "options": {"temperature": temperature},
                    "stream": True
                }
                resp = requests.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=(2.0, 30.0), stream=True)
                if resp.status_code == 200:
                    self.ollama_disabled = False
                    inside_think = False
                    for line in resp.iter_lines(decode_unicode=True):
                        if line:
                            try:
                                data = json.loads(line)
                                chunk = data.get("message", {}).get("content", "")
                                if "<think>" in chunk:
                                    inside_think = True
                                if "</think>" in chunk:
                                    inside_think = False
                                    chunk = chunk.split("</think>")[-1]
                                if not inside_think and chunk:
                                    yield chunk
                                if data.get("done"):
                                    break
                            except Exception:
                                continue
                    return
                else:
                    print(f"[AGAM LLM Stream] Ollama returned status {resp.status_code}")
            except Exception as e:
                print(f"[AGAM LLM Stream] Ollama connection failed: {e}")
                self.ollama_disabled = True
                self.last_ollama_check = time.time()

    def _call_openai_compat(self, base_url, api_key, model, messages, temperature):
        endpoint = f"{base_url}/chat/completions" if not base_url.endswith("/chat/completions") else base_url
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature
        }
        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=(3.0, 30.0))
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return content
            else:
                self._last_status = resp.status_code
                print(f"[AGAM LLM] OpenAI-compat failed ({resp.status_code}): {resp.text[:200]}")
        except Exception as e:
            print(f"[AGAM LLM] OpenAI-compat connection error: {e}")
        return None

    def _call_astra(self, api_key, messages, temperature):
        if self.astra_disabled:
            return None
        headers = {
            "Authorization": f"Bearer {api_key.strip().rstrip('|')}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "gpt-6-astra",
            "messages": messages,
            "temperature": temperature
        }
        try:
            resp = requests.post("https://api.experientiallabs.ai/v1/chat/completions", headers=headers, json=payload, timeout=(2.0, 15.0))
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            elif resp.status_code in [401, 403, 429]:
                print(f"[AGAM LLM] Astra disabled (status {resp.status_code})")
                self.astra_disabled = True
        except Exception as e:
            print(f"[AGAM LLM] Astra connection error: {e}")
            self.astra_disabled = True
        return None

    def _call_ollama(self, model, messages, temperature):
        ollama_model = "qwen2.5-coder:7b"
        if "deepseek" in model.lower():
            ollama_model = "deepseek-r1:latest"
        elif "qwen" in model.lower():
            ollama_model = "qwen2.5-coder:7b"

        system_content = ""
        chat_msgs = []
        for m in messages:
            if m.get("role") == "system":
                system_content += m.get("content", "") + "\n"
            else:
                chat_msgs.append(m)

        try:
            payload = {
                "model": ollama_model,
                "messages": ([{"role": "system", "content": system_content.strip()}] if system_content else []) + chat_msgs,
                "options": {"temperature": temperature},
                "stream": False
            }
            resp = requests.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=(2.0, 10.0))
            if resp.status_code == 200:
                self.ollama_disabled = False
                data = resp.json()
                content = data.get("message", {}).get("content", "")
                if "<think>" in content:
                    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                return content
        except Exception as e:
            print(f"[AGAM LLM] Ollama call failed: {e}")
            self.ollama_disabled = True
            self.last_ollama_check = time.time()
        return None
