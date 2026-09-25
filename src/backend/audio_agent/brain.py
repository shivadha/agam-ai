"""
audio_agent/brain.py

The decision-making brain of the Audio Intelligence Agent.
Given a scene or video context, it selects the optimal sound from the library.
Uses multi-factor scoring: emotion match, energy match, viral score, diversity, past performance.
"""
import os
import random
import json
from .library import AudioLibrary

# Emotion-to-music-category mapping
EMOTION_MUSIC_MAP = {
    "energetic":   ["phonk", "electronic", "pop", "upbeat"],
    "suspense":    ["cinematic", "ambient", "sting", "dramatic"],
    "shock":       ["dramatic", "impact", "cinematic"],
    "fear":        ["horror", "ambient", "sting"],
    "funny":       ["comedy", "meme", "internet-meme"],
    "inspiration": ["orchestral", "corporate", "upbeat"],
    "futuristic":  ["synthwave", "electronic", "ambient"],
    "calm":        ["lo-fi", "ambient", "acoustic"],
    "curiosity":   ["synthwave", "cinematic", "lo-fi"],
    "surprise":    ["futuristic", "electronic", "cinematic"],
    "anger":       ["phonk", "dramatic", "electronic"],
}

# SFX hint to emotion mapping
SFX_HINT_MAP = {
    "whoosh":  ["transition", "swoosh", "movement"],
    "impact":  ["impact", "boom", "hit", "bass"],
    "pop":     ["pop", "notification", "alert"],
    "rise":    ["suspense", "rise", "reveal"],
    "glitch":  ["glitch", "digital", "error", "corrupt"],
    "chime":   ["success", "achievement", "win", "ding"],
    "none":    [],
}

# Default energy levels per transition type
TRANSITION_ENERGY = {
    "speed_ramp": 9, "whip": 8, "zoom": 7, "motion_blur": 6,
    "push": 5, "flash": 8, "glitch": 8, "camera_shake": 7,
    "spin": 6, "parallax": 5, "punch_zoom": 9, "none": 3,
}


class AudioBrain:
    """
    The intelligent selector that acts like an AI music director.
    
    It reasons about:
    - What emotion does this scene need?
    - What energy level matches the pacing?
    - What's currently viral and trending?
    - What has worked best for this creator?
    - How to avoid repeating the same sound twice?
    """

    def __init__(self, library: AudioLibrary = None):
        self.lib = library or AudioLibrary()
        self._used_in_session = []  # Track sounds used in current video to enforce diversity

    def reset_session(self):
        """Call before processing a new video to reset diversity tracking."""
        self._used_in_session = []

    # ──────────────────────────────────────────────────────
    # MAIN API: Select background music for a video
    # ──────────────────────────────────────────────────────
    def select_background_music(self, emotion: str, energy_level: int = 7,
                                duration_s: float = 45.0) -> dict | None:
        """
        Select the best background music track for a video.
        
        Args:
            emotion: Video's dominant emotion from viral_angle.py
            energy_level: 1-10 desired energy 
            duration_s: Video duration in seconds
            
        Returns:
            Sound record dict with local_path, or None if nothing available
        """
        self.lib.log("brain_select_music", f"emotion={emotion}, energy={energy_level}")
        
        # Get candidates by emotion
        candidates = self.lib.find_by_emotion(emotion, category="music", limit=20)
        
        # Fallback: try similar emotions
        if len(candidates) < 3:
            fallback_emotions = self._get_similar_emotions(emotion)
            for fallback_emotion in fallback_emotions:
                more = self.lib.find_by_emotion(fallback_emotion, category="music", limit=10)
                candidates.extend(more)

        if not candidates:
            print(f"[AudioBrain] No music found for emotion '{emotion}' — using any available")
            candidates = self.lib.browse(category="music", downloaded_only=True, per_page=20)["sounds"]

        if not candidates:
            return None

        # Score and rank candidates
        scored = self._score_music(candidates, emotion, energy_level)
        if not scored:
            return None

        # Apply diversity: penalize recently used sounds
        for item in scored:
            if item["sound"]["id"] in self._used_in_session:
                item["score"] *= 0.3

        scored.sort(key=lambda x: x["score"], reverse=True)
        best = scored[0]["sound"]
        
        # Track for diversity
        self._used_in_session.append(best["id"])
        
        print(f"[AudioBrain] Selected music: '{best['name']}' (score={scored[0]['score']:.2f})")
        return best

    # ──────────────────────────────────────────────────────
    # MAIN API: Select SFX for a single scene
    # ──────────────────────────────────────────────────────
    def select_sfx_for_scene(self, scene: dict, scene_index: int, total_scenes: int) -> dict | None:
        """
        Select the best SFX sound for a specific scene.
        
        Args:
            scene: Scene dict from script_gen (has emotion, transition_type, sfx hint, etc.)
            scene_index: 0-based scene index
            total_scenes: Total number of scenes in video
            
        Returns:
            Sound record dict or None
        """
        sfx_hint = scene.get("sfx", "none").lower()
        emotion = scene.get("emotion", "energetic").lower()
        transition = scene.get("transition_type", "none").lower()
        
        if sfx_hint == "none" and transition == "none":
            return None

        # Build tag search list from hint
        search_tags = SFX_HINT_MAP.get(sfx_hint, []) + [emotion, transition]
        
        # Try tag-based search first
        candidates = self.lib.find_by_tags(search_tags, limit=10)
        
        # Fallback to emotion-based
        if not candidates:
            candidates = self.lib.find_by_emotion(emotion, category="sfx", limit=5)
        if not candidates:
            candidates = self.lib.find_by_emotion(emotion, category="meme", limit=5)

        if not candidates:
            return None

        # Apply diversity: don't use the same SFX twice in a row
        candidates = [c for c in candidates if c["id"] not in self._used_in_session[-2:]]
        if not candidates:
            return None

        # Pick best scored
        scored = self._score_sfx(candidates, sfx_hint, emotion, scene_index, total_scenes)
        if not scored:
            return None

        scored.sort(key=lambda x: x["score"], reverse=True)
        best = scored[0]["sound"]
        self._used_in_session.append(best["id"])
        
        print(f"[AudioBrain] SFX scene {scene_index+1}: '{best['name']}'")
        return best

    # ──────────────────────────────────────────────────────
    # MAIN API: Process entire video — select music + all SFX
    # ──────────────────────────────────────────────────────
    def process_video(self, viral_angle_data: dict, scenes: list, duration_s: float = 45.0) -> dict:
        """
        Full video audio selection.
        Called by the orchestrator's 'audio-agent' node.
        
        Returns:
            {
                "background_music": {...sound record...} | None,
                "sfx_timeline": [{"time": float, "sound": {...}, "volume": float}],
                "selection_log": [...reasoning...]
            }
        """
        self.reset_session()
        
        emotion = viral_angle_data.get("emotion", "energetic")
        energy_hint = self._emotion_to_energy(emotion)
        
        result = {
            "background_music": None,
            "sfx_timeline": [],
            "selection_log": [],
            "emotion": emotion,
        }

        # 1. Select background music
        music = self.select_background_music(emotion, energy_hint, duration_s)
        if music:
            result["background_music"] = music
            result["selection_log"].append(
                f"Music: '{music['name']}' selected for emotion '{emotion}'"
            )

        # 2. Select SFX for each scene
        current_time = 0.0
        last_sfx_time = -2.0  # enforce 2s gap
        total = len(scenes)

        for i, scene in enumerate(scenes):
            scene_duration = float(scene.get("duration", 3.0))
            
            # Only add SFX if enough time has passed
            if (current_time - last_sfx_time) >= 2.0:
                sfx = self.select_sfx_for_scene(scene, i, total)
                if sfx and sfx.get("local_path"):
                    result["sfx_timeline"].append({
                        "time": round(current_time, 2),
                        "sound": sfx,
                        "volume": 0.35,
                        "scene_index": i
                    })
                    last_sfx_time = current_time
                    result["selection_log"].append(
                        f"SFX @{current_time:.1f}s: '{sfx['name']}' for scene {i+1}"
                    )
            
            current_time += scene_duration

        print(f"[AudioBrain] Video processed: music={'yes' if music else 'no'}, "
              f"sfx={len(result['sfx_timeline'])} events")
        return result

    # ──────────────────────────────────────────────────────
    # SCORING FUNCTIONS
    # ──────────────────────────────────────────────────────
    def _score_music(self, candidates: list, emotion: str, target_energy: int) -> list:
        scored = []
        for sound in candidates:
            if not sound.get("local_path") or not os.path.exists(sound.get("local_path", "")):
                continue
            
            score = 0.0
            
            # Emotion match (40%)
            if sound.get("emotion") == emotion:
                score += 4.0
            elif sound.get("emotion") in self._get_similar_emotions(emotion):
                score += 2.0
            
            # Energy match (20%)
            sound_energy = sound.get("energy_level", 5)
            energy_diff = abs(sound_energy - target_energy)
            score += max(0, 2.0 - energy_diff * 0.4)
            
            # Viral score (25%)
            score += sound.get("viral_score", 5.0) * 0.25
            
            # Success rate (15%)
            score += sound.get("success_rate", 0.5) * 1.5

            # Small random jitter for variety
            score += random.uniform(0, 0.3)
            
            scored.append({"sound": sound, "score": score})
        return scored

    def _score_sfx(self, candidates: list, sfx_hint: str, emotion: str,
                   scene_index: int, total_scenes: int) -> list:
        scored = []
        hint_tags = SFX_HINT_MAP.get(sfx_hint, [])
        
        for sound in candidates:
            if not sound.get("local_path") or not os.path.exists(sound.get("local_path", "")):
                continue
            
            score = 0.0
            sound_tags = json.loads(sound.get("tags", "[]"))
            
            # Tag overlap (50%)
            overlap = len(set(hint_tags) & set(sound_tags))
            score += overlap * 1.5
            
            # Emotion match (25%)
            if sound.get("emotion") == emotion:
                score += 2.5
            
            # Viral score (15%)
            score += sound.get("viral_score", 5.0) * 0.15
            
            # Position-aware: first and last scenes get high-energy SFX
            is_edge_scene = (scene_index == 0 or scene_index == total_scenes - 1)
            if is_edge_scene and sound.get("energy_level", 5) >= 7:
                score += 1.0
            
            score += random.uniform(0, 0.2)
            scored.append({"sound": sound, "score": score})
        return scored

    # ──────────────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────────────
    def _get_similar_emotions(self, emotion: str) -> list:
        similarity_map = {
            "energetic":   ["shock", "anger"],
            "suspense":    ["fear", "curiosity"],
            "shock":       ["energetic", "anger"],
            "fear":        ["suspense"],
            "funny":       ["energetic"],
            "inspiration": ["energetic", "energetic"],
            "futuristic":  ["curiosity", "suspense"],
            "calm":        ["curiosity"],
            "curiosity":   ["futuristic", "suspense"],
            "surprise":    ["shock", "energetic"],
            "anger":       ["shock", "energetic"],
        }
        return similarity_map.get(emotion, ["energetic"])

    def _emotion_to_energy(self, emotion: str) -> int:
        energy_map = {
            "energetic": 8, "shock": 9, "anger": 9,
            "inspiration": 8, "suspense": 6, "fear": 7,
            "funny": 6, "futuristic": 7, "curiosity": 5,
            "calm": 3, "surprise": 8,
        }
        return energy_map.get(emotion, 6)
