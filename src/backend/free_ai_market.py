"""
free_ai_market.py — PulseForge Dynamic Free AI Market Engine
=============================================================
Continuously discovers, health-checks, and routes to zero-cost, free-tier AI
generation endpoints for text-to-image and image-to-video pipelines.

Supports:
  - Hugging Face Serverless Inference API (FLUX.1-schnell, SDXL-Lightning, SD 2.1, AnimateDiff, SVD)
  - Pollinations.ai (Zero-auth, multi-model: flux, turbo, sdxl, anime)
  - Free OpenRouter tier models
  - Procedural Motion Engine (Always active, 100% free offline fallback)
"""

import os
import time
import json
import logging
import requests
import threading

logger = logging.getLogger("FreeAIMarket")
logging.basicConfig(level=logging.INFO)

# Market registry file
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MARKET_CACHE_FILE = os.path.join(BASE_DIR, "data", "ai_market_cache.json")

FREE_IMAGE_PROVIDERS = [
    {
        "id": "pollinations_flux",
        "name": "Pollinations FLUX",
        "type": "image",
        "model": "flux",
        "auth_required": False,
        "endpoint": "https://image.pollinations.ai/prompt/{prompt}?model=flux&width={width}&height={height}&seed={seed}&nologo=true",
        "priority": 1,
        "status": "unknown",
        "last_checked": 0,
        "latency_ms": 0,
    },
    {
        "id": "pollinations_turbo",
        "name": "Pollinations Turbo (SDXL)",
        "type": "image",
        "model": "turbo",
        "auth_required": False,
        "endpoint": "https://image.pollinations.ai/prompt/{prompt}?model=turbo&width={width}&height={height}&seed={seed}&nologo=true",
        "priority": 2,
        "status": "unknown",
        "last_checked": 0,
        "latency_ms": 0,
    },
    {
        "id": "hf_flux_schnell",
        "name": "HuggingFace Serverless FLUX.1-schnell",
        "type": "image",
        "model": "black-forest-labs/FLUX.1-schnell",
        "auth_required": True,
        "env_key": "HF_TOKEN",
        "endpoint": "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell",
        "priority": 3,
        "status": "unknown",
        "last_checked": 0,
        "latency_ms": 0,
    },
    {
        "id": "hf_sdxl_lightning",
        "name": "HuggingFace ByteDance SDXL-Lightning",
        "type": "image",
        "model": "ByteDance/SDXL-Lightning",
        "auth_required": True,
        "env_key": "HF_TOKEN",
        "endpoint": "https://api-inference.huggingface.co/models/ByteDance/SDXL-Lightning",
        "priority": 4,
        "status": "unknown",
        "last_checked": 0,
        "latency_ms": 0,
    }
]

FREE_VIDEO_PROVIDERS = [
    {
        "id": "motion_engine_cinematic",
        "name": "PulseForge Motion Engine (Always Free)",
        "type": "video",
        "model": "procedural_cinematic",
        "auth_required": False,
        "priority": 1,
        "status": "online",
        "last_checked": 0,
        "latency_ms": 10,
    },
    {
        "id": "hf_svd",
        "name": "HuggingFace Stable Video Diffusion",
        "type": "video",
        "model": "stabilityai/stable-video-diffusion-img2vid-xt",
        "auth_required": True,
        "env_key": "HF_TOKEN",
        "endpoint": "https://api-inference.huggingface.co/models/stabilityai/stable-video-diffusion-img2vid-xt",
        "priority": 2,
        "status": "unknown",
        "last_checked": 0,
        "latency_ms": 0,
    }
]

class FreeAIMarket:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(FreeAIMarket, cls).__new__(cls)
                cls._instance._init_market()
            return cls._instance

    def _init_market(self):
        self.image_providers = list(FREE_IMAGE_PROVIDERS)
        self.video_providers = list(FREE_VIDEO_PROVIDERS)
        self.last_scan_time = 0
        self.load_cache()
        # Scan in background on initialization
        threading.Thread(target=self.scan_market, daemon=True).start()

    def load_cache(self):
        try:
            if os.path.exists(MARKET_CACHE_FILE):
                with open(MARKET_CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.image_providers = data.get("image_providers", self.image_providers)
                    self.video_providers = data.get("video_providers", self.video_providers)
                    self.last_scan_time = data.get("last_scan_time", 0)
        except Exception as e:
            logger.warning(f"Could not load AI market cache: {e}")

    def save_cache(self):
        try:
            os.makedirs(os.path.dirname(MARKET_CACHE_FILE), exist_ok=True)
            with open(MARKET_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "image_providers": self.image_providers,
                    "video_providers": self.video_providers,
                    "last_scan_time": self.last_scan_time
                }, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save AI market cache: {e}")

    def test_provider(self, prov: dict) -> bool:
        t0 = time.time()
        prov_id = prov["id"]
        try:
            if "pollinations" in prov_id:
                # Fast head or probe check
                url = "https://image.pollinations.ai/prompt/test?model=turbo&width=64&height=64&nologo=true"
                r = requests.get(url, timeout=6)
                if r.status_code == 200:
                    prov["status"] = "online"
                    prov["latency_ms"] = int((time.time() - t0) * 1000)
                    prov["last_checked"] = int(time.time())
                    return True
            elif "hf_" in prov_id:
                token = os.environ.get(prov.get("env_key", "HF_TOKEN"), "")
                if not token:
                    prov["status"] = "unconfigured_key"
                    prov["last_checked"] = int(time.time())
                    return False
                headers = {"Authorization": f"Bearer {token}"}
                r = requests.get(prov["endpoint"], headers=headers, timeout=6)
                # 200 or 503 (model loading) means active endpoint
                if r.status_code in [200, 503, 400]:
                    prov["status"] = "online"
                    prov["latency_ms"] = int((time.time() - t0) * 1000)
                    prov["last_checked"] = int(time.time())
                    return True
                else:
                    prov["status"] = f"error_{r.status_code}"
            elif prov_id == "motion_engine_cinematic":
                prov["status"] = "online"
                prov["latency_ms"] = 5
                prov["last_checked"] = int(time.time())
                return True
        except Exception as e:
            prov["status"] = "offline"
            prov["last_checked"] = int(time.time())
            return False
            
        prov["status"] = "offline"
        prov["last_checked"] = int(time.time())
        return False

    def scan_market(self):
        logger.info("[FreeAIMarket] Probing free AI market generation endpoints...")
        for p in self.image_providers:
            self.test_provider(p)
        for p in self.video_providers:
            self.test_provider(p)
        self.last_scan_time = int(time.time())
        self.save_cache()
        logger.info(f"[FreeAIMarket] Market scan complete. Online image providers: {[p['name'] for p in self.image_providers if p['status'] == 'online']}")

    def get_best_image_provider(self, custom_model_hint: str = None) -> dict:
        """Returns the highest-priority online free image provider."""
        # Refresh if scan is older than 30 mins
        if time.time() - self.last_scan_time > 1800:
            threading.Thread(target=self.scan_market, daemon=True).start()

        # Check if user requested a specific provider
        if custom_model_hint:
            hint = custom_model_hint.lower()
            for p in self.image_providers:
                if (hint in p["id"].lower() or hint in p["name"].lower()) and p["status"] == "online":
                    return p

        # Fallback to highest priority online provider
        online_providers = [p for p in self.image_providers if p["status"] == "online"]
        if online_providers:
            online_providers.sort(key=lambda x: (x["priority"], x["latency_ms"]))
            return online_providers[0]
            
        # Default to Pollinations Turbo
        return self.image_providers[0]

    def get_best_video_provider(self) -> dict:
        """Returns the highest-priority online free image-to-video provider."""
        online_providers = [p for p in self.video_providers if p["status"] == "online"]
        if online_providers:
            online_providers.sort(key=lambda x: x["priority"])
            return online_providers[0]
        return self.video_providers[0]

    def get_market_status(self) -> dict:
        return {
            "last_scan": self.last_scan_time,
            "image_providers": self.image_providers,
            "video_providers": self.video_providers,
            "recommended_image": self.get_best_image_provider()["name"],
            "recommended_video": self.get_best_video_provider()["name"]
        }

def get_free_ai_market() -> FreeAIMarket:
    return FreeAIMarket()

def check_market() -> dict:
    return get_free_ai_market().get_market_status()
