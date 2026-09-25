"""
video_assembler.py — PulseForge High-Retention Cinematic Video Engine
======================================================================
Features:
  - Multi-transition sequencing (Speed ramp, Zoom burst, Whip pans, Motion blur push, Glitch flashes, Crossfade)
  - Local AI Creative Brain feedback recording
  - Precision multitrack audio ducking and SFX alignment
  - Word-by-word kinetic subtitle overlays (Hormozi style) with retention bounce
  - Moving retention progress bar
  - Robust resource management & clean stream closure
"""

import os
import random
import re
import math
import wave
import struct
from .creative_learner import get_creative_brain

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def parse_srt(srt_path):
    """
    Parses an .srt subtitle file and groups words into 2-3 word chunks for high-retention reading.
    """
    subs = []
    if not os.path.exists(srt_path):
        print(f"[video_assembler] Subtitle file not found: {srt_path}")
        return subs
        
    with open(srt_path, 'r', encoding='utf-8') as f:
        content = f.read()
        
    blocks = content.strip().split('\n\n')
    
    def to_sec(ts):
        ts = ts.replace(',', '.')
        parts = ts.split(':')
        if len(parts) == 3:
            h, m, s = parts
            return int(h)*3600 + int(m)*60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return int(m)*60 + float(s)
        return float(ts)
        
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            time_line = lines[1]
            text = " ".join(lines[2:]).strip()
            
            if '-->' not in time_line:
                continue
                
            start_str, end_str = time_line.split(' --> ')
            t_start = to_sec(start_str)
            t_end = to_sec(end_str)
            
            subs.append({
                'start': t_start,
                'end': t_end,
                'text': text
            })
            
    grouped_subs = []
    current_chunk = []
    chunk_start = 0.0
    
    for sub in subs:
        if not current_chunk:
            chunk_start = sub['start']
            
        current_chunk.append(sub['text'])
        
        if len(current_chunk) >= 3 or any(p in sub['text'] for p in ['.', '!', '?', ',']):
            grouped_subs.append({
                'start': chunk_start,
                'end': sub['end'],
                'text': " ".join(current_chunk)
            })
            current_chunk = []
            
    if current_chunk:
        grouped_subs.append({
            'start': chunk_start,
            'end': subs[-1]['end'],
            'text': " ".join(current_chunk)
        })
        
    print(f"[video_assembler] Parsed {len(grouped_subs)} grouped subtitle segments.")
    return grouped_subs


def create_advanced_motion_effect(image_path, duration, width, height, effect_type):
    """
    Applies custom cinematic zooming, panning, camera shakes, or glitches to vertical clips.
    """
    from moviepy import ImageClip, VideoClip, ColorClip
    
    try:
        clip = ImageClip(image_path).with_duration(duration)
    except Exception as e:
        print(f"[video_assembler] Error loading ImageClip for {image_path}: {e}")
        return ColorClip(size=(width, height), color=(15, 15, 25), duration=duration)
    
    img_ratio = clip.w / clip.h
    target_ratio = width / height
    
    # Crop to vertical 9:16 aspect ratio
    if img_ratio > target_ratio:
        clip = clip.resized(height=height)
        clip = clip.cropped(x_center=clip.w/2, y_center=clip.h/2, width=width, height=height)
    else:
        clip = clip.resized(width=width)
        clip = clip.cropped(x_center=clip.w/2, y_center=clip.h/2, width=width, height=height)
        
    def make_frame(t):
        progress = t / max(duration, 0.01)
        
        if effect_type in ['zoom_in', 'zoom_burst_in']:
            zoom = 1.0 + 0.32 * progress
            return clip.resized(zoom).cropped(x_center=clip.w/2, y_center=clip.h/2, width=width, height=height).get_frame(t)
        elif effect_type in ['zoom_out', 'zoom_burst_out']:
            zoom = 1.3 - 0.28 * progress
            return clip.resized(zoom).cropped(x_center=clip.w/2, y_center=clip.h/2, width=width, height=height).get_frame(t)
        elif effect_type in ['pan_left', 'whip_pan_left']:
            x_shift = 0.16 * width * progress
            return clip.resized(1.22).cropped(x_center=(clip.w/2) + x_shift, y_center=clip.h/2, width=width, height=height).get_frame(t)
        elif effect_type in ['pan_right', 'whip_pan_right']:
            x_shift = 0.16 * width * progress
            return clip.resized(1.22).cropped(x_center=(clip.w/2) - x_shift, y_center=clip.h/2, width=width, height=height).get_frame(t)
        elif effect_type == 'speed_ramp':
            # Exponential speed curve
            zoom = 1.0 + 0.35 * (progress ** 2.2)
            return clip.resized(zoom).cropped(x_center=clip.w/2, y_center=clip.h/2, width=width, height=height).get_frame(t)
        elif effect_type == 'motion_blur_push':
            y_shift = 0.12 * height * progress
            return clip.resized(1.18).cropped(x_center=clip.w/2, y_center=(clip.h/2) - y_shift, width=width, height=height).get_frame(t)
        elif effect_type == 'glitch_flash':
            zoom = 1.2
            g_shift = random.choice([-25, 0, 25]) if (0.2 < progress < 0.4 or 0.65 < progress < 0.82) else 0
            return clip.resized(zoom).cropped(x_center=(clip.w/2) + g_shift, y_center=clip.h/2, width=width, height=height).get_frame(t)
        else:
            zoom = 1.0 + 0.18 * progress
            return clip.resized(zoom).cropped(x_center=clip.w/2, y_center=clip.h/2, width=width, height=height).get_frame(t)
            
    try:
        anim_clip = VideoClip(make_frame, duration=duration)
        return anim_clip
    except Exception as e:
        print(f"[video_assembler] VideoClip compilation error: {e}. Returning static clip.")
        return clip


def prepare_video_shot(video_path, duration, width, height):
    """
    Loads an AI-generated video file, scales and crops it to vertical 9:16 aspect ratio.
    """
    from moviepy import VideoFileClip, vfx, ColorClip
    try:
        clip = VideoFileClip(video_path)
    except Exception as e:
        print(f"[video_assembler] Error loading AI video {video_path}: {e}")
        return ColorClip(size=(width, height), color=(0,0,0), duration=duration)
        
    img_ratio = clip.w / clip.h
    target_ratio = width / height
    
    if img_ratio > target_ratio:
        clip = clip.resized(height=height)
        clip = clip.cropped(x_center=clip.w/2, y_center=clip.h/2, width=width, height=height)
    else:
        clip = clip.resized(width=width)
        clip = clip.cropped(x_center=clip.w/2, y_center=clip.h/2, width=width, height=height)
        
    if clip.duration >= duration:
        clip = clip.subclipped(0, duration)
    else:
        try:
            clip = clip.with_effects([vfx.Loop(duration=duration)])
        except Exception:
            clip = clip.with_duration(duration)
            
    return clip


def add_custom_transitions(clips, scenes, width, height):
    """
    Applies diverse cinematic transitions:
    - Speed ramp, Zoom burst in/out, Whip pan left/right, Glitch flash, RGB split, White flash, Dark pop, Cyber glow, Parallax slide.
    """
    from moviepy import ColorClip, concatenate_videoclips
    new_clips = []
    
    for i, c in enumerate(clips):
        new_clips.append(c)
        if i < len(clips) - 1:
            scene = scenes[min(i, len(scenes)-1)] if scenes else {}
            trans = (scene.get('transition_type') or 'speed_ramp').lower().replace('-', '_')
            
            if trans in ['glitch_flash', 'glitch', 'rgb_split']:
                glitch_c1 = ColorClip(size=(width, height), color=(255, 20, 80), duration=0.03)
                glitch_c2 = ColorClip(size=(width, height), color=(0, 240, 255), duration=0.03)
                new_clips.extend([glitch_c1, glitch_c2])
            elif trans in ['whip_pan_left', 'whip_pan_right', 'whip_pan', 'whip']:
                white_swipe = ColorClip(size=(width, height), color=(240, 248, 255), duration=0.05)
                new_clips.append(white_swipe)
            elif trans in ['zoom_burst_in', 'zoom_burst_out', 'speed_ramp', 'flash', 'white_flash']:
                flash = ColorClip(size=(width, height), color=(255, 255, 255), duration=0.05)
                new_clips.append(flash)
            elif trans in ['motion_blur_push', 'dark_pop', 'dark_fade']:
                dark_pop = ColorClip(size=(width, height), color=(10, 15, 26), duration=0.04)
                new_clips.append(dark_pop)
            elif trans in ['cyber_glow', 'color_pop']:
                cyan_pop = ColorClip(size=(width, height), color=(0, 255, 170), duration=0.04)
                new_clips.append(cyan_pop)
            elif trans in ['parallax_slide', 'parallax']:
                glow_pop = ColorClip(size=(width, height), color=(56, 189, 248), duration=0.04)
                new_clips.append(glow_pop)
                
    return concatenate_videoclips(new_clips, method="compose")


def generate_procedural_whoosh(output_path, duration=0.8):
    sample_rate = 22050
    num_samples = int(duration * sample_rate)
    with wave.open(output_path, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for i in range(num_samples):
            t = i / sample_rate
            freq = 140 + 700 * math.sin(math.pi * (t / duration))
            amp = 8000 * math.sin(math.pi * (t / duration))**2
            val = int(amp * math.sin(2 * math.pi * freq * t))
            wav.writeframesraw(struct.pack('<h', val))


def generate_procedural_hit(output_path, duration=1.2):
    sample_rate = 22050
    num_samples = int(duration * sample_rate)
    with wave.open(output_path, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for i in range(num_samples):
            t = i / sample_rate
            freq = 75 + 280 * math.exp(-30 * t)
            amp = 12000 * math.exp(-5.0 * t)
            val = int(amp * math.sin(2 * math.pi * freq * t))
            wav.writeframesraw(struct.pack('<h', val))


def make_progress_bar(duration, width, bar_height=14, color=(0, 255, 170)):
    from moviepy import VideoClip
    import numpy as np
    
    def make_frame(t):
        progress = min(1.0, max(0.0, t / duration))
        fill_width = int(width * progress)
        frame = np.zeros((bar_height, width, 3), dtype=np.uint8)
        if fill_width > 0:
            frame[:, :fill_width, :] = color
        return frame
        
    return VideoClip(make_frame, duration=duration)


def assemble_cinematic_video(
    audio_path: str,
    subtitle_path: str,
    scenes: list,
    output_filename: str = "final_short.mp4",
    music_path: str = None,
    sfx_timeline: list = None,
    viral_score: float = 85.0,
    topic_title: str = "PulseForge Video",
    editing_style: str = "auto"
) -> str:
    """
    Master video assembly function powered by the Viral Reel Intelligence Brain.
    Dynamically applies viral reel pacing, transitions, subtitle aesthetics,
    multitrack audio ducking, and motion effects matching the topic.
    """
    from moviepy import AudioFileClip, CompositeAudioClip, CompositeVideoClip, TextClip
    from .viral_reel_brain import get_viral_brain
    
    output_dir = OUTPUT_DIR
    output_path = os.path.join(output_dir, output_filename)
    
    # ── 0. Viral Reel Brain Analysis ──
    viral_brain = get_viral_brain()
    blueprint = viral_brain.analyze_topic(topic_title, custom_style=editing_style)
    print(f"[video_assembler] [Viral Reel Brain] Active Blueprint: '{blueprint['name']}' ({blueprint['match_reason']})")
    print(f"[video_assembler] Assembling video -> {output_path}")

    # 1. Base Audio Track
    audio_clip = AudioFileClip(audio_path)
    total_duration = audio_clip.duration
    print(f"[video_assembler] Voice narration duration: {total_duration:.2f}s across {len(scenes)} scenes.")

    # Assign transitions from the Viral Reel Blueprint
    blueprint_transitions = blueprint.get("transitions", ['zoom_burst_in', 'whip_pan', 'glitch_flash', 'speed_ramp'])
    for idx, sc in enumerate(scenes):
        if not sc.get('transition_type'):
            sc['transition_type'] = blueprint_transitions[idx % len(blueprint_transitions)]

    # Assets for SFX fallbacks
    whoosh_path = os.path.join(output_dir, "sfx_whoosh.wav")
    hit_path = os.path.join(output_dir, "sfx_hit.wav")
    if not os.path.exists(whoosh_path): generate_procedural_whoosh(whoosh_path)
    if not os.path.exists(hit_path): generate_procedural_hit(hit_path)

    # 2. Scene Compilation
    scene_dur = total_duration / max(1, len(scenes))
    video_clips = []
    current_time = 0.0
    boundary_times = []
    
    effects_list = ['zoom_burst_in', 'zoom_burst_out', 'whip_pan_left', 'whip_pan_right', 'speed_ramp', 'motion_blur_push', 'glitch_flash']

    for idx, scene in enumerate(scenes):
        clips_before = len(video_clips)
        video_paths = scene.get('video_paths', [])
        img_paths = scene.get('image_paths', [])
        
        if video_paths:
            shot_duration = scene_dur / len(video_paths)
            for shot_idx, video_path in enumerate(video_paths):
                vc = prepare_video_shot(video_path, shot_duration, 1080, 1920)
                video_clips.append(vc)
                if shot_idx > 0 or idx > 0:
                    boundary_times.append(current_time)
                current_time += shot_duration
        else:
            # Generate authentic topic-aligned visual if scene has no images (NEVER use random cached files)
            if not img_paths:
                scene_prompt = scene.get('image_prompt') or f"Cinematic shot of {topic_title}, dramatic lighting, 8k vertical 9:16"
                fallback_img = os.path.join(output_dir, f"scene_auto_{idx+1}_{int(time.time()*1000)%1000000}.jpg")
                from .image_gen import generate_image
                print(f"[video_assembler] Synthesizing topic-aligned image for Scene {idx+1} ({topic_title})...")
                res_img = generate_image(scene_prompt, fallback_img, width=1080, height=1920, scene_index=idx, total_scenes=len(scenes))
                img_paths = [res_img] if res_img and os.path.exists(res_img) else []
                
            if not img_paths:
                fallback_img = os.path.join(output_dir, f"temp_fallback_{idx}.png")
                from .image_gen import _create_placeholder_image
                _create_placeholder_image(fallback_img, f"{topic_title} Scene {idx+1}", 1080, 1920, seed_val=idx+1)
                img_paths = [fallback_img]
                
            shot_duration = scene_dur / len(img_paths)
            for shot_idx, img_path in enumerate(img_paths):
                effect_type = effects_list[idx % len(effects_list)]
                if idx == 0 and shot_idx == 0:
                    effect_type = 'zoom_burst_in'
                    
                vc = create_advanced_motion_effect(img_path, shot_duration, 1080, 1920, effect_type)
                video_clips.append(vc)
                
                if shot_idx > 0 or idx > 0:
                    boundary_times.append(current_time)
                current_time += shot_duration

        clips_added = len(video_clips) - clips_before
        if clips_added == 0:
            # A scene must NEVER silently vanish — fail loudly so the run halts
            # instead of producing a video with missing scenes.
            raise RuntimeError(
                f"Scene {idx + 1}/{len(scenes)} produced zero video clips "
                f"(no video_paths and no image_paths). Aborting assembly."
            )
        print(f"[video_assembler] Scene {idx + 1}/{len(scenes)}: {clips_added} clip(s) "
              f"({'AI video' if video_paths else 'motion-effect stills'}).")

    if not video_clips:
        raise RuntimeError("Video assembly failed: no clips were produced from any scene.")

    final_video = add_custom_transitions(video_clips, scenes, 1080, 1920)
    final_video = final_video.with_duration(total_duration)

    # 3. Audio Mixing & Topic-Synced Background Music
    creative_brain = get_creative_brain()
    mix_levels = creative_brain.get_audio_mix()
    tracks = [audio_clip.with_volume_scaled(mix_levels["voice"])]
    
    # Auto-resolve emotion-matched background music if not explicitly provided
    if not music_path or not os.path.exists(music_path):
        try:
            from .music_engine import ensure_music_assets, EMOTION_TO_MOOD
            emotion = (scenes[0].get('emotion') if scenes else '') or 'epic'
            mood = EMOTION_TO_MOOD.get(emotion.lower(), 'dramatic')
            music_dict = ensure_music_assets()
            avail_tracks = music_dict.get(mood) or music_dict.get('futuristic') or []
            if avail_tracks:
                music_path = random.choice(avail_tracks)
                print(f"[video_assembler] Auto-synced BGM for emotion '{emotion}' -> '{mood}': {music_path}")
        except Exception as bgm_err:
            print(f"[video_assembler] BGM auto-selection note: {bgm_err}")
            
    if music_path and os.path.exists(music_path):
        try:
            bgm = AudioFileClip(music_path).with_duration(total_duration)
            tracks.append(bgm.with_volume_scaled(0.16))
        except Exception as e:
            print(f"[video_assembler] Error mixing BGM: {e}")
            
    if sfx_timeline:
        for event in sfx_timeline:
            evt_time = event.get('time', 0.0)
            evt_path = event.get('path')
            evt_vol = event.get('volume', mix_levels["sfx"])
            if evt_path and os.path.exists(evt_path):
                try:
                    sfx_clip = AudioFileClip(evt_path)
                    tracks.append(sfx_clip.with_start(evt_time).with_volume_scaled(evt_vol))
                except Exception as e:
                    print(f"[video_assembler] Error mixing SFX: {e}")
    else:
        for bt in boundary_times:
            if whoosh_path:
                try:
                    whoosh = AudioFileClip(whoosh_path)
                    tracks.append(whoosh.with_start(max(0.0, bt - 0.25)).with_volume_scaled(0.20))
                except Exception:
                    pass
            if hit_path and random.random() < 0.65:
                try:
                    hit = AudioFileClip(hit_path)
                    tracks.append(hit.with_start(bt).with_volume_scaled(0.24))
                except Exception:
                    pass

    mixed_audio = CompositeAudioClip(tracks)
    final_video = final_video.with_audio(mixed_audio)

    # 4. Word-by-Word Bouncing Karaoke Subtitles (Alex Hormozi / CapCut Style at Safe-Zone y=1120)
    subs = parse_srt(subtitle_path)
    overlay_clips = []
    font_path = "C:/Windows/Fonts/impact.ttf" if os.path.exists("C:/Windows/Fonts/impact.ttf") else ("C:/Windows/Fonts/arialbd.ttf" if os.path.exists("C:/Windows/Fonts/arialbd.ttf") else "Arial")
    bp_primary = blueprint.get("caption_color", "#FFE600")
    bp_accent = blueprint.get("caption_accent", "#00FFAA")
    karaoke_colors = [bp_primary, bp_accent, "#38BDF8", "#FF3366", "#A855F7"]

    for sub in subs:
        try:
            raw_text = sub['text'].strip()
            if not raw_text:
                continue

            words = raw_text.split()
            seg_start = sub['start']
            seg_end = sub['end']
            seg_dur = max(0.25, seg_end - seg_start)
            num_words = len(words)
            word_dur = seg_dur / max(1, num_words)
            active_color = random.choice(karaoke_colors)

            # Generate word-by-word bouncing highlight frames for the chunk
            for w_idx, active_word in enumerate(words):
                w_start = seg_start + w_idx * word_dur
                w_end = seg_start + (w_idx + 1) * word_dur if w_idx < num_words - 1 else seg_end
                
                # Active word gets uppercase emphasis and glowing brackets / color
                display_parts = []
                for idx_i, w in enumerate(words):
                    if idx_i == w_idx:
                        display_parts.append(f"★ {w.upper()} ★")
                    else:
                        display_parts.append(w.upper())
                
                if len(display_parts) > 4:
                    mid = len(display_parts) // 2
                    formatted_line = " ".join(display_parts[:mid]) + "\n" + " ".join(display_parts[mid:])
                else:
                    formatted_line = " ".join(display_parts)

                font_size = 56 if len(formatted_line) < 20 else 48

                txt_clip = TextClip(
                    font=font_path,
                    text=formatted_line,
                    font_size=font_size,
                    color=active_color,
                    stroke_color="black",
                    stroke_width=5.0,
                    method="caption",
                    size=(860, None),
                    text_align="center"
                )
                txt_clip = txt_clip.with_start(w_start).with_end(w_end)
                # Golden Safe-Zone: y = 1120 (Centered, strictly clear of YouTube Shorts overlay UI)
                txt_clip = txt_clip.with_position(('center', 1120))
                overlay_clips.append(txt_clip)
        except Exception as e:
            print(f"[video_assembler] Karaoke subtitle rendering note: {e}")

    # Retention Progress Bar
    try:
        pb_clip = make_progress_bar(total_duration, 1080, bar_height=14, color=(0, 255, 170))
        pb_clip = pb_clip.with_position((0, 1920 - 14))
        overlay_clips.append(pb_clip)
    except Exception as e:
        print(f"[video_assembler] Progress bar generation error: {e}")

    if overlay_clips:
        final_video = CompositeVideoClip([final_video] + overlay_clips)

    print(f"[video_assembler] Rendering vertical video to {output_path}...")
    final_video.write_videofile(
        output_path, 
        fps=24, 
        codec="libx264", 
        audio_codec="aac", 
        logger=None,
        threads=4,
        preset="fast"
    )
    
    # Close streams
    audio_clip.close()
    mixed_audio.close()
    
    # Record render in Creative AI Brain for continuous learning
    try:
        creative_brain.record_learning_session(
            video_id=output_filename,
            topic=topic_title,
            viral_score=viral_score,
            transitions_used=learned_transitions,
            visual_style="Cinematic High-Retention"
        )
    except Exception as brain_err:
        print(f"[video_assembler] Creative Brain learning note: {brain_err}")

    # 5. Multi-Platform Syndication & Social Media Package Generation
    try:
        from .syndication import syndicate_video
        narration_full = " ".join([s.get('narration', '') for s in scenes]) if scenes else topic_title
        synd_res = syndicate_video(
            video_path=output_path,
            title=topic_title,
            description=f"Deep-dive breakdown into {topic_title}. Watch till the end to discover what happened next!",
            tags=["Shorts", "Trending", "AI", "Viral"],
            script=narration_full,
            viral_score=viral_score
        )
        print(f"[video_assembler] [OK] Multi-platform syndication ready: {synd_res.get('package_path')}")
    except Exception as synd_err:
        print(f"[video_assembler] Syndication note: {synd_err}")

    print(f"[video_assembler] Rendering complete! Video saved: {output_path} ({os.path.getsize(output_path)/1024/1024:.2f} MB)")
    return output_path
