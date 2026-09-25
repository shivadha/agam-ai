"""
viral_reel_brain.py — PulseForge Viral Reel Intelligence & Editing Brain
========================================================================
Analyzes any topic or keyword against trending internet formats (YouTube Shorts,
Instagram Reels, TikTok) to dynamically determine the optimal viral editing blueprint:
- Pacing & cut duration (1.5s - 3.5s per scene)
- Camera motion & visual art direction
- Multi-transition sequencing (whip pans, zoom bursts, speed ramps, glitch flashes)
- Sound design & audio ducking profile (dark phonk, orchestral tension, hype trap)
- Kinetic caption aesthetic (Hormozi yellow, neon cyan, cinematic clean, meme bounce)
- Retention loop engineering (seamless end-to-beginning audio/visual loop)
"""

import os
import re
import json
import time
import urllib.request
import urllib.parse
from typing import Dict, Any, List

# ── 5 Core Viral Editing Blueprints ──────────────────────────────────────────
VIRAL_BLUEPRINTS = {
    "cinematic_noir": {
        "id": "cinematic_noir",
        "name": "Cinematic Noir & Suspense",
        "description": "MagnatesMedia / Christopher Nolan style — brooding atmosphere, deep tension risers, slow push-in zoom, moody chiaroscuro lighting.",
        "pacing_cut_s": 3.2,
        "hook_type": "mystery_reveal",
        "transitions": ["zoom_burst_in", "whip_pan", "glitch_flash", "crossfade", "motion_blur_push", "white_flash"],
        "camera_motion": "slow_dolly_push",
        "bgm_genre": "cinematic_ambient_orchestral",
        "ducking_db": -16,
        "caption_color": "#FFFFFF",
        "caption_accent": "#F59E0B",
        "caption_style": "cinematic_clean",
        "sfx_recipe": ["sub_bass_drop", "tension_riser", "impact_hit", "deep_whoosh", "cinematic_boom"],
        "color_grade": "teal_orange_noir",
        "topics_match": ["batman", "superhero", "crime", "mystery", "history", "war", "noir", "dark", "investigation", "secret", "mafia", "scandal"]
    },
    "kinetic_viral": {
        "id": "kinetic_viral",
        "name": "Fast-Paced Kinetic Viral",
        "description": "Alex Hormozi / MrBeast style — high-velocity 1.8s cuts, aggressive snap zooms, neon text bounce, whoosh/boom on every cut.",
        "pacing_cut_s": 1.8,
        "hook_type": "shock_metric",
        "transitions": ["whip_pan", "glitch_flash", "zoom_burst_in", "speed_ramp", "motion_blur_push", "whip_pan"],
        "camera_motion": "dynamic_snap_zoom",
        "bgm_genre": "dark_phonk",
        "ducking_db": -14,
        "caption_color": "#FFE600",
        "caption_accent": "#00FFAA",
        "caption_style": "yellow_bold_kinetic",
        "sfx_recipe": ["vine_boom", "whip_whoosh", "glitch_hit", "bass_drop", "digital_bell"],
        "color_grade": "high_contrast_neon",
        "topics_match": ["ai", "tech", "money", "crypto", "business", "coding", "fast", "future", "startup", "millionaire", "hack", "tools"]
    },
    "vox_documentary": {
        "id": "vox_documentary",
        "name": "Vox Deep-Dive & Data Story",
        "description": "Vox / Johnny Harris style — sophisticated narrative flow, parallax motion, minimalist aesthetic, curiosity-gap hooks.",
        "pacing_cut_s": 2.6,
        "hook_type": "curiosity_gap",
        "transitions": ["parallax_slide", "crossfade", "zoom_burst_in", "motion_blur_push", "whip_pan"],
        "camera_motion": "gentle_parallax_drift",
        "bgm_genre": "lofi_ambient_electronic",
        "ducking_db": -18,
        "caption_color": "#F8FAFC",
        "caption_accent": "#38BDF8",
        "caption_style": "minimalist_editorial",
        "sfx_recipe": ["paper_slide", "camera_shutter", "subtle_pop", "chime", "woosh_soft"],
        "color_grade": "editorial_matte",
        "topics_match": ["science", "space", "geography", "economics", "health", "psychology", "earth", "philosophy", "evolution", "facts"]
    },
    "meme_pop_culture": {
        "id": "meme_pop_culture",
        "name": "Pop Culture & Meme Banger",
        "description": "Reels / TikTok viral culture — punchy comedic cuts, reaction sound effects, vibrant saturation, elastic bounce text.",
        "pacing_cut_s": 2.0,
        "hook_type": "contrarian_question",
        "transitions": ["speed_ramp", "glitch_flash", "whip_pan", "zoom_burst_in"],
        "camera_motion": "punch_zoom_elastic",
        "bgm_genre": "upbeat_trap_banger",
        "ducking_db": -12,
        "caption_color": "#FFFFFF",
        "caption_accent": "#EC4899",
        "caption_style": "meme_bold_outline",
        "sfx_recipe": ["bruh", "record_scratch", "bell_ding", "fail_trombone", "impact_hit"],
        "color_grade": "vibrant_hyper_saturated",
        "topics_match": ["gaming", "anime", "celebrity", "movie", "gta", "fortnite", "marvel", "trending", "comedy", "funny", "tiktok"]
    },
    "retention_loop": {
        "id": "retention_loop",
        "name": "Hypnotic Infinite Retention Loop",
        "description": "Infinite loop architecture — ending dialogue and visual flow seamlessly merges into the first second for 100%+ replay rate.",
        "pacing_cut_s": 2.4,
        "hook_type": "infinite_loop_paradox",
        "transitions": ["motion_blur_push", "zoom_burst_in", "whip_pan", "crossfade"],
        "camera_motion": "seamless_continuous_orbit",
        "bgm_genre": "hypnotic_synth_pulse",
        "ducking_db": -15,
        "caption_color": "#00FFAA",
        "caption_accent": "#FFFFFF",
        "caption_style": "cyber_glowing",
        "sfx_recipe": ["reversed_whoosh", "bass_pulse", "frequency_rise", "impact_hit"],
        "color_grade": "hypnotic_deep_glow",
        "topics_match": ["paradox", "loop", "time", "mind", "riddle", "simulation", "matrix", "infinity", "universe"]
    }
}


class ViralReelBrain:
    """
    Intelligent brain that searches topic context and determines the best
    viral editing blueprint, sound design, and pacing for video assembly.
    """

    def __init__(self):
        self.cached_analyses = {}

    def analyze_topic(self, topic: str, custom_style: str = "auto") -> Dict[str, Any]:
        """
        Analyzes a topic to select or customize the optimal viral reel blueprint.
        Searches topic keywords, tone, and audience expectations.
        """
        clean_topic = (topic or "").strip()
        cache_key = f"{clean_topic.lower()}_{custom_style}"
        if cache_key in self.cached_analyses:
            return self.cached_analyses[cache_key]

        # Explicit user selection override
        if custom_style in VIRAL_BLUEPRINTS:
            bp = VIRAL_BLUEPRINTS[custom_style].copy()
            bp["match_reason"] = f"User explicitly selected {bp['name']}"
            return bp

        topic_lower = clean_topic.lower()

        # Check keyword matches across blueprints
        best_match = None
        best_score = 0

        for bp_id, bp in VIRAL_BLUEPRINTS.items():
            score = 0
            for kw in bp["topics_match"]:
                if re.search(r'\b' + re.escape(kw) + r'\b', topic_lower):
                    score += 15
                elif kw in topic_lower:
                    score += 8
            if score > best_score:
                best_score = score
                best_match = bp_id

        # Contextual topic intelligence defaults
        if not best_match or best_score == 0:
            if any(w in topic_lower for w in ["batman", "superman", "joker", "gotham", "dark knight", "spiderman", "avengers"]):
                best_match = "cinematic_noir"
            elif any(w in topic_lower for w in ["ai", "robot", "software", "nvidia", "deepseek", "sora", "gpt", "model"]):
                best_match = "kinetic_viral"
            elif any(w in topic_lower for w in ["how", "why", "explained", "history", "origins", "truth", "science", "secret"]):
                best_match = "vox_documentary"
            elif any(w in topic_lower for w in ["game", "meme", "funny", "trailer", "reaction", "crazy"]):
                best_match = "meme_pop_culture"
            else:
                best_match = "cinematic_noir" if any(w in topic_lower for w in ["dark", "night", "kill", "war", "blood"]) else "kinetic_viral"

        blueprint = VIRAL_BLUEPRINTS[best_match].copy()
        blueprint["topic"] = clean_topic
        blueprint["match_reason"] = f"Automatically matched '{clean_topic}' to trending {blueprint['name']} format (Score: {max(best_score, 10)})"
        
        # Calculate optimal scene count & duration for 30s-45s vertical short
        target_duration = 35.0
        blueprint["target_duration_s"] = target_duration
        blueprint["recommended_scenes"] = max(5, int(target_duration / blueprint["pacing_cut_s"]))
        
        self.cached_analyses[cache_key] = blueprint
        return blueprint

    def generate_topic_scene_prompts(self, topic: str, scene_count: int = 6, visual_style: str = "") -> List[Dict[str, str]]:
        """
        Generates highly specific, narrative-driven scene image prompts for the topic.
        Guarantees that topics like Batman produce ONLY dark Gotham/Batman cinematic imagery,
        NEVER generic or unrelated photos.
        """
        bp = self.analyze_topic(topic, custom_style=visual_style if visual_style in VIRAL_BLUEPRINTS else "auto")
        topic_clean = topic.strip()
        style_desc = bp["name"]

        # Topic-tailored visual themes
        is_batman = any(w in topic.lower() for w in ["batman", "dark knight", "gotham", "bruce wayne", "joker"])
        is_tech_ai = any(w in topic.lower() for w in ["ai", "robot", "cyber", "coding", "neural", "future", "algorithm"])
        is_space_sci = any(w in topic.lower() for w in ["space", "mars", "quantum", "planet", "galaxy", "telescope"])

        scenes = []
        for i in range(scene_count):
            scene_num = i + 1
            trans = bp["transitions"][i % len(bp["transitions"])]
            sfx = bp["sfx_recipe"][i % len(bp["sfx_recipe"])]

            if is_batman:
                batman_prompts = [
                    f"Cinematic ultra-realistic 8k shot of Batman standing atop a dark rain-drenched gothic gargoyle overlooking Gotham City skyline at midnight, dark cape flowing in storm wind, volumetric fog, dramatic amber and cyan rim lighting, 9:16 vertical",
                    f"Interior of the secret underground Batcave, massive glowing tactical surveillance screens displaying Gotham City crime grid, Batmobile parked in shadowy background, water dripping, hyper-detailed 8k, 9:16 vertical",
                    f"Dramatic close-up portrait of Batman in tactical cowl armor, rain droplets streaming down black Kevlar helmet, piercing white eye lenses, intense gritty cinematic shadows, 9:16 vertical",
                    f"The Batmobile rushing at extreme speed through neon-lit wet Gotham alleyways, asphalt reflections, afterburner glowing blue flame, atmospheric rain sparks, motion blur, 9:16 vertical",
                    f"Confrontation between Batman and shadowy rogue enemies on a dark Gotham industrial rooftop, searchlights cutting through stormy clouds, comic-book realism, 8k, 9:16 vertical",
                    f"Epic final low-angle hero shot of Batman leaping off a gothic tower with cape spread like bat wings against a stormy full moon, cinematic climax, 9:16 vertical"
                ]
                img_prompt = batman_prompts[i % len(batman_prompts)]
                motion_prompt = "Cinematic slow zoom into Batman with atmospheric rain particles and volumetric lightning flash"
            elif is_tech_ai:
                tech_prompts = [
                    f"Futuristic dark laboratory revealing glowing quantum neural network core, floating holographic code nodes and cyan data streams, 8k cinematic photography, 9:16 vertical",
                    f"Ultra-detailed robotic android hand interacting with glowing translucent holographic UI, cybernetic joints, neon violet and blue backlight, 9:16 vertical",
                    f"Digital brain synthesis inside a supercomputer server farm, pulsing fiber-optic light pulses, high-tech server racks stretching into infinity, 9:16 vertical",
                    f"Macro close-up of a futuristic semiconductor AI microchip with glowing gold and neon circuit pathways, raytraced metallic reflections, 9:16 vertical",
                    f"Human mind interfacing with advanced artificial intelligence, dual exposure silhouette with cosmic neural pathways, hyper-detailed, 9:16 vertical",
                    f"Global cybernetic Earth network illuminated by millions of interconnected light pulses from orbit, dark space backdrop, 9:16 vertical"
                ]
                img_prompt = tech_prompts[i % len(tech_prompts)]
                motion_prompt = "Dynamic whip pan across glowing neural data streams with speed ramp burst"
            else:
                img_prompt = (
                    f"Cinematic 8k hyper-realistic visual depicting {topic_clean} (Scene {scene_num}), "
                    f"dramatic volumetric lighting, atmospheric depth of field, pristine photorealistic textures, "
                    f"curated for {style_desc}, 9:16 vertical aspect ratio"
                )
                motion_prompt = f"Smooth cinematic {bp['camera_motion']} with atmospheric ambient lighting"

            scenes.append({
                "scene_number": scene_num,
                "image_prompt": img_prompt,
                "image_to_video_prompt": motion_prompt,
                "transition_type": trans,
                "sfx": sfx,
                "duration": bp["pacing_cut_s"]
            })

        return scenes


_brain_instance = None

def get_viral_brain() -> ViralReelBrain:
    """Singleton getter for the Viral Reel Brain."""
    global _brain_instance
    if _brain_instance is None:
        _brain_instance = ViralReelBrain()
    return _brain_instance
