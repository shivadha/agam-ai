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


def _ass_timestamp(sec: float) -> str:
    sec = max(0.0, sec)
    return f"{int(sec // 3600)}:{int((sec % 3600) // 60):02d}:{sec % 60:05.2f}"


def _esc_ass_text(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\n", " ")


_NB_HYPHEN = "‑"  # U+2011 non-breaking hyphen

# At Arial Bold 72 on a 1080px frame with 80px side margins, ~20 uppercase
# characters fit on one line. Fixed 5-word chunks overflowed, and libass
# WrapStyle 0 then broke hyphenated compounds mid-word ("LIVE-ACTION" ->
# "LIVE" / "-ACTION"). Lines are chunked to fit instead.
_MAX_LINE_CHARS = 20
_MAX_CHUNK_WORDS = 6


def _sanitize_caption_word(word: str) -> str:
    """Escape ASS control chars and keep hyphenated compounds on one line.

    libass smart-wrapping breaks "LIVE-ACTION" into "LIVE" / "-ACTION" with a
    dangling hyphen. A non-breaking hyphen between alphanumerics stops the
    break without changing how the word reads.
    """
    w = _esc_ass_text(word)
    return re.sub(r"(?<=[A-Za-z0-9])-(?=[A-Za-z0-9])", _NB_HYPHEN, w)


def _ffmpeg_bin() -> str:
    """Resolve an ffmpeg binary: system PATH first, else imageio-ffmpeg's."""
    import shutil
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def build_caption_ass(caption_events: list, ass_path: str,
                      highlight_bgr: str = "&H0000FFFF") -> str | None:
    """Build a karaoke-style ASS file from (words, active_idx, start, end) events.

    Re-chunks the flat word stream into ≤5-word display lines so every line
    fits the frame (no halfway-cut text), and emits one Dialogue per word
    with the spoken word highlighted — the Hormozi look, burned reliably by
    ffmpeg's subtitles filter instead of hundreds of fragile TextClips.
    """
    flat = []
    for (words, _w_idx, w_start, w_end) in caption_events:
        w = words[_w_idx] if 0 <= _w_idx < len(words) else ""
        if w:
            flat.append((_sanitize_caption_word(str(w)), float(w_start), float(w_end)))
    if not flat:
        return None

    # Word timings (especially faster-whisper's) can overlap slightly at the
    # edges. Two overlapping karaoke Dialogues render as stacked duplicate
    # lines, so clamp every word's end to the next word's start.
    for i in range(len(flat) - 1):
        w, s, e = flat[i]
        ns = flat[i + 1][1]
        if e > ns - 0.01:
            flat[i] = (w, s, max(s + 0.01, ns - 0.01))

    # Width-aware line chunking so every line fits the frame (no halfway-cut
    # text, no mid-word hyphen breaks).
    chunks, cur, cur_len = [], [], 0
    for w, s, e in flat:
        need = len(w) + (1 if cur else 0)  # +1 for the joining space
        if cur and (cur_len + need > _MAX_LINE_CHARS or len(cur) >= _MAX_CHUNK_WORDS):
            chunks.append(cur)
            cur, cur_len = [], 0
            need = len(w)
        cur.append((w, s, e))
        cur_len += need
    if cur:
        chunks.append(cur)
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n"
        "WrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Cap,Arial,72,&H00FFFFFF,&H00FFFFFF,&H80000000,&H00000000,"
        "-1,0,0,0,100,100,0,0,1,4,1,2,80,80,380,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )
    WHITE = "&H00FFFFFF"
    events = []
    for chunk in chunks:
        line_words = [w for w, _s, _e in chunk]
        for j, (word, start, end) in enumerate(chunk):
            if end <= start:
                # Minimal visible flash, but never past the next word's start
                # (overlapping karaoke events stack into duplicate lines).
                nxt = chunk[j + 1][1] if j + 1 < len(chunk) else None
                end = start + 0.08
                if nxt is not None and end > nxt - 0.01:
                    end = max(start + 0.01, nxt - 0.01)
            parts = []
            for k, lw in enumerate(line_words):
                if k == j:
                    parts.append("{\\c%s}%s{\\c%s}" % (highlight_bgr, lw.upper(), WHITE))
                else:
                    parts.append(lw.upper())
            events.append("Dialogue: 0,%s,%s,Cap,,0,0,0,,%s"
                          % (_ass_timestamp(start), _ass_timestamp(end), " ".join(parts)))
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(events) + "\n")
    print(f"[video_assembler] Caption ASS built: {len(events)} word events in {len(chunks)} lines.")
    return ass_path


def burn_captions_ass(video_path: str, ass_path: str) -> str:
    """Burn an ASS subtitle file into the video via ffmpeg. Returns final path.

    The same pass also applies a light film finish (grain + vignette) so the
    whole video shares one cinematic grade instead of the flat '80s look.
    """
    import subprocess
    if not ass_path or not os.path.exists(ass_path):
        return video_path
    ffmpeg = _ffmpeg_bin()
    # Escape for the subtitles filter (Windows-safe: forward slashes, quote escapes)
    filt_path = ass_path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'").replace(",", "\\,")
    vf = (f"subtitles='{filt_path}',"
          f"noise=alls=6:allf=t,"      # fine film grain, temporally animated
          f"vignette=angle=PI/4.6")    # gentle edge falloff
    out_path = os.path.splitext(video_path)[0] + "_captioned.mp4"
    cmd = [ffmpeg, "-y", "-i", video_path,
           "-vf", vf,
           "-c:v", "libx264", "-preset", "fast", "-crf", "20",
           "-c:a", "copy", out_path]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=600)
        if os.path.exists(out_path) and os.path.getsize(out_path) > 10000:
            print(f"[video_assembler] Captions burned: {os.path.basename(out_path)}")
            try:
                os.remove(video_path)
            except Exception:
                pass
            return out_path
    except Exception as e:
        print(f"[video_assembler] ASS burn failed ({e}); keeping uncaptioned video.")
    return video_path


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
        # Opening punch-in: a quick ~5% scale pop that settles in ~0.4s gives
        # every scene cut the modern shorts feel (skipped on zoom-out/shake).
        punch = 1.0 + 0.05 * math.exp(-t * 7.0)

        if effect_type in ['zoom_in', 'zoom_burst_in']:
            zoom = (1.0 + 0.32 * progress) * punch
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
            zoom = (1.0 + 0.35 * (progress ** 2.2)) * punch
            return clip.resized(zoom).cropped(x_center=clip.w/2, y_center=clip.h/2, width=width, height=height).get_frame(t)
        elif effect_type == 'motion_blur_push':
            y_shift = 0.12 * height * progress
            return clip.resized(1.18).cropped(x_center=clip.w/2, y_center=(clip.h/2) - y_shift, width=width, height=height).get_frame(t)
        elif effect_type == 'glitch_flash':
            zoom = 1.2
            g_shift = random.choice([-25, 0, 25]) if (0.2 < progress < 0.4 or 0.65 < progress < 0.82) else 0
            return clip.resized(zoom).cropped(x_center=(clip.w/2) + g_shift, y_center=clip.h/2, width=width, height=height).get_frame(t)
        else:
            zoom = (1.0 + 0.18 * progress) * punch
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

    A short AI clip is played ONCE, then the shot continues with a slow Ken
    Burns drift on the clip's final frame. (The old vfx.Loop fill made a 1s
    clip visibly snap back and repeat for the whole shot — "animated for a
    second then repeats".)
    """
    from moviepy import VideoFileClip, ColorClip, concatenate_videoclips
    try:
        clip = VideoFileClip(video_path)
    except Exception as e:
        print(f"[video_assembler] Error loading AI video {video_path}: {e}")
        return ColorClip(size=(width, height), color=(0, 0, 0), duration=duration)

    if not getattr(clip, "duration", 0):
        print(f"[video_assembler] AI video has no duration ({video_path}); using fallback.")
        return ColorClip(size=(width, height), color=(0, 0, 0), duration=duration)

    img_ratio = clip.w / clip.h
    target_ratio = width / height

    if img_ratio > target_ratio:
        clip = clip.resized(height=height)
    else:
        clip = clip.resized(width=width)
    clip = clip.cropped(x_center=clip.w / 2, y_center=clip.h / 2,
                        width=width, height=height)

    if clip.duration >= duration:
        return clip.subclipped(0, duration)

    # Short clip: play it once, then drift on its last frame — never loop.
    tail_dur = duration - clip.duration
    try:
        import tempfile
        from PIL import Image as _PILImage
        last = clip.get_frame(max(0.0, clip.duration - 0.05))
        fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="tailframe_")
        os.close(fd)
        _PILImage.fromarray(last).save(tmp_path)
        try:
            tail = create_advanced_motion_effect(tmp_path, tail_dur, width, height, "zoom_in")
            head = clip.without_audio() if hasattr(clip, "without_audio") else clip
            full = concatenate_videoclips([head, tail], method="compose").with_duration(duration)
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        print(f"[video_assembler] Short AI clip ({clip.duration:.2f}s) plays once + "
              f"{tail_dur:.2f}s drift tail (no loop).")
        return full
    except Exception as e:
        # Last resort: return the short clip as-is (shot runs slightly short)
        # rather than crash the render — never silently loop.
        print(f"[video_assembler] Tail-drift note ({e}); keeping unlooped short clip.")
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
    editing_style: str = "auto",
    word_timings_path: str = None
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
    # Real speech timings (faster-whisper) are preferred; falls back to the
    # estimated even-division timings from the SRT when unavailable.
    # Each event: (words_list, active_word_index, start, end)
    caption_events = []
    try:
        real_words = []
        if word_timings_path:
            try:
                from .captions import load_word_timings
                real_words = load_word_timings(word_timings_path)
            except Exception as wt_err:
                print(f"[video_assembler] Word-timing load note: {wt_err}")

        if real_words:
            from .captions import chunk_words
            for chunk in chunk_words(real_words):
                for w_idx, (_w, w_start, w_end) in enumerate(chunk["timings"]):
                    caption_events.append((chunk["words"], w_idx, w_start, w_end))
            print(f"[video_assembler] Karaoke synced to {len(real_words)} real word timings.")
        else:
            subs = parse_srt(subtitle_path)
            for sub in subs:
                raw = sub['text'].strip()
                if not raw:
                    continue
                words = raw.split()
                seg_start, seg_end = sub['start'], sub['end']
                seg_dur = max(0.25, seg_end - seg_start)
                word_dur = seg_dur / max(1, len(words))
                for w_idx in range(len(words)):
                    w_start = seg_start + w_idx * word_dur
                    w_end = seg_start + (w_idx + 1) * word_dur if w_idx < len(words) - 1 else seg_end
                    caption_events.append((words, w_idx, w_start, w_end))
    except Exception as e:
        print(f"[video_assembler] Caption event build note: {e}")

    overlay_clips = []
    # Karaoke captions are built as an ASS file and burned with ffmpeg's
    # subtitles filter (reliable wrapping, no halfway-cut text). The old
    # per-word TextClip renderer was fragile — it stays only as a fallback.
    caption_ass_path = None
    if caption_events:
        try:
            def _hex_to_ass_bgr(hex_color: str) -> str:
                h = (hex_color or "#FFE600").lstrip("#")
                if len(h) != 6:
                    h = "FFE600"
                r, g, b = h[0:2], h[2:4], h[4:6]
                return f"&H00{b}{g}{r}".upper()

            bp_primary = blueprint.get("caption_color", "#FFE600")
            ass_path = os.path.join(os.path.dirname(os.path.abspath(output_path)),
                                    f"captions_{os.path.splitext(os.path.basename(output_path))[0]}.ass")
            caption_ass_path = build_caption_ass(
                caption_events, ass_path,
                highlight_bgr=_hex_to_ass_bgr(bp_primary))
        except Exception as e:
            print(f"[video_assembler] Caption ASS build note: {e}")
            caption_ass_path = None

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

    # Burn karaoke captions into the final video (ASS via ffmpeg).
    if caption_ass_path:
        output_path = burn_captions_ass(output_path, caption_ass_path)
    
    # Record render in Creative AI Brain for continuous learning
    try:
        learned_transitions = [s.get('transition_type', 'glitch_flash') for s in (scenes or [])] or ['zoom_burst_in']
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
