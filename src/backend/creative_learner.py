"""
creative_learner.py — PulseForge Local Creative AI Learning Engine
===================================================================
A self-contained local AI agent that learns and adapts video editing, transition
sequencing, prompt styling, camera angles, pacing, and audio balancing over time.

Persists learned parameters in `data/creative_brain.json`.
"""

import os
import json
import time
import random
import logging

logger = logging.getLogger("CreativeLearner")
logging.basicConfig(level=logging.INFO)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BRAIN_FILE = os.path.join(BASE_DIR, "data", "creative_brain.json")

CAMERA_ANGLES = [
    "cinematic wide establishing shot, anamorphic lens flare",
    "extreme dynamic low-angle hero shot, dramatic rim lighting",
    "macro close-up with shallow depth of field and sharp focal point",
    "overhead bird's-eye perspective, geometric symmetry",
    "Dutch tilt dramatic angle, high tension, volumetric god rays",
    "isometric cinematic framing, 85mm portrait compression",
    "dynamic tracking perspective with subtle motion blur on edges"
]

CINEMATIC_MODIFIERS = [
    "hyper-detailed 8k, Unreal Engine 5 render, raytraced lighting, photorealistic color grading",
    "award-winning National Geographic cinematography, crisp textures, natural volumetric light",
    "dark atmospheric mood, Cyberpunk neon accents, Hasselblad medium format color science",
    "high-fashion dramatic editorial lighting, bold contrasts, masterwork visual composition"
]

DEFAULT_BRAIN = {
    "version": "1.0",
    "total_videos_learned": 0,
    "transition_scores": {
        "speed_ramp": 1.4,
        "zoom_burst_in": 1.5,
        "zoom_burst_out": 1.2,
        "whip_pan_left": 1.3,
        "whip_pan_right": 1.3,
        "motion_blur_push": 1.4,
        "glitch_flash": 1.1,
        "crossfade": 0.9
    },
    "pacing_target_wps": 2.6,        # Words per second for fast-paced viral retention
    "optimal_scene_duration": 3.2,   # Seconds per scene
    "audio_mix": {
        "voice": 1.0,
        "music": 0.18,
        "sfx": 0.38
    },
    "successful_prompt_tokens": [
        "cinematic lighting",
        "dramatic rim light",
        "anamorphic 8k",
        "volumetric rays",
        "sharp focus",
        "hyperrealistic texture"
    ],
    "history": []
}

class CreativeLearner:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CreativeLearner, cls).__new__(cls)
            cls._instance._load_brain()
        return cls._instance

    def _load_brain(self):
        self.brain = dict(DEFAULT_BRAIN)
        if os.path.exists(BRAIN_FILE):
            try:
                with open(BRAIN_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.brain.update(data)
                logger.info(f"[CreativeLearner] Loaded brain with {self.brain.get('total_videos_learned', 0)} learned sessions.")
            except Exception as e:
                logger.warning(f"[CreativeLearner] Failed to load brain, using defaults: {e}")
        else:
            self._save_brain()

    def _save_brain(self):
        try:
            os.makedirs(os.path.dirname(BRAIN_FILE), exist_ok=True)
            with open(BRAIN_FILE, "w", encoding="utf-8") as f:
                json.dump(self.brain, f, indent=2)
        except Exception as e:
            logger.error(f"[CreativeLearner] Failed to save brain: {e}")

    def enhance_scene_prompt(self, base_prompt: str, scene_index: int, total_scenes: int, visual_style: str = "Cinematic") -> str:
        """
        Enhances scene prompt with camera angle variety and learned aesthetic modifiers,
        guaranteeing unique imagery across every scene.
        """
        angle = CAMERA_ANGLES[scene_index % len(CAMERA_ANGLES)]
        learned_tokens = random.sample(self.brain["successful_prompt_tokens"], min(2, len(self.brain["successful_prompt_tokens"])))
        modifier = random.choice(CINEMATIC_MODIFIERS)
        
        # Build composite non-duplicate prompt
        enhanced = (
            f"{base_prompt.strip()}. "
            f"Perspective: {angle}. "
            f"Style: {visual_style}, {', '.join(learned_tokens)}, {modifier}. "
            f"Scene {scene_index+1} of {total_scenes} sequence."
        )
        return enhanced

    def select_transitions_for_scenes(self, scene_count: int, emotion: str = "curiosity") -> list[str]:
        """
        Intelligently generates a diverse, non-repeating sequence of cinematic transitions
        weighted by the AI's learned performance scores.
        """
        available = list(self.brain["transition_scores"].keys())
        weights = [self.brain["transition_scores"][t] for t in available]
        
        # High impact opening transition
        sequence = ["zoom_burst_in"]
        last_transition = "zoom_burst_in"
        
        for i in range(1, scene_count):
            # Exclude last transition to enforce variety (no back-to-back same transition)
            choices = [t for t in available if t != last_transition]
            sub_weights = [self.brain["transition_scores"][t] for t in choices]
            
            # Emotion-specific weighting
            if emotion in ["shock", "fear", "anger"] and "glitch_flash" in choices:
                idx = choices.index("glitch_flash")
                sub_weights[idx] *= 1.8
            elif emotion in ["excitement", "surprise"] and "speed_ramp" in choices:
                idx = choices.index("speed_ramp")
                sub_weights[idx] *= 1.6

            chosen = random.choices(choices, weights=sub_weights, k=1)[0]
            sequence.append(chosen)
            last_transition = chosen
            
        return sequence

    def get_audio_mix(self, emotion: str = "curiosity") -> dict:
        """Returns learned audio volume balancing for voice, music, and SFX."""
        mix = dict(self.brain["audio_mix"])
        if emotion in ["suspense", "fear"]:
            mix["music"] = 0.14  # Lower music for intense suspense
            mix["sfx"] = 0.42    # Louder impacts
        elif emotion in ["excitement", "inspiration"]:
            mix["music"] = 0.22
            mix["sfx"] = 0.35
        return mix

    def record_learning_session(self, video_id: str, topic: str, viral_score: float, transitions_used: list[str], visual_style: str):
        """
        Incorporates feedback from completed video renders into the creative brain.
        Higher viral score increases weights for used transitions and styles.
        """
        self.brain["total_videos_learned"] = self.brain.get("total_videos_learned", 0) + 1
        
        reward_factor = max(0.8, min(1.3, viral_score / 75.0 if viral_score else 1.0))
        
        for t in transitions_used:
            if t in self.brain["transition_scores"]:
                current = self.brain["transition_scores"][t]
                # Soft learning update (moving average with momentum)
                self.brain["transition_scores"][t] = round(current * 0.9 + (current * reward_factor) * 0.1, 3)

        # Log to history
        self.brain["history"].append({
            "timestamp": int(time.time()),
            "video_id": video_id,
            "topic": topic,
            "viral_score": viral_score,
            "visual_style": visual_style,
            "transitions_used": transitions_used
        })
        # Keep last 50 entries
        self.brain["history"] = self.brain["history"][-50:]
        
        self._save_brain()
        logger.info(f"[CreativeLearner] Brain updated. Total learned videos: {self.brain['total_videos_learned']}")

def get_creative_brain() -> CreativeLearner:
    return CreativeLearner()
