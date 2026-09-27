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
import time
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

# Hyphen/dash variants that libass WrapStyle 0 can break after, leaving a
# dangling hyphen at the start of the next line ("LIVE-ACTION" -> "LIVE" /
# "-ACTION"). Every one of them is normalized to the non-breaking hyphen so
# a compound can never split mid-word.
_HYPHEN_RE = re.compile("[\u002D\u2010\u2011\u2012\u2013\u2212]")


def _sanitize_caption_word(word: str) -> str:
    """Escape ASS control chars and keep hyphenated compounds on one line.

    libass smart-wrapping breaks "LIVE-ACTION" into "LIVE" / "-ACTION" with a
    dangling hyphen. Every hyphen/dash variant becomes a non-breaking hyphen
    so the break can never happen, without changing how the word reads.
    """
    w = _esc_ass_text(word)
    return _HYPHEN_RE.sub(_NB_HYPHEN, w)


# At Arial Bold 72 on a 1080px frame with 80px side margins, ~20 uppercase
# characters fit on one line. Fixed 5-word chunks overflowed, and libass
# WrapStyle 0 then broke hyphenated compounds mid-word ("LIVE-ACTION" ->
# "LIVE" / "-ACTION"). Lines are chunked to fit instead.
_MAX_LINE_CHARS = 20
_MAX_CHUNK_WORDS = 6


def _reflow_leading_hyphens(chunks: list) -> list:
    """Ensure no rendered caption line starts with a hyphen.

    If a chunk's first word still begins with a hyphen (e.g. the
    transcriber emitted "-ACTION" as its own word), strip the leading
    hyphen and move the word back onto the previous line when there is
    one; a lone "-" fragment is dropped. Returns the chunk list.
    """
    hyphens = "\u002D\u2010\u2011\u2012\u2013\u2212"
    out = []
    for chunk in chunks:
        chunk = list(chunk)
        while chunk:
            w, s, e = chunk[0]
            stripped = w.lstrip(hyphens)
            if stripped == w:
                break  # no leading hyphen on this line
            if not stripped:
                chunk.pop(0)  # lone "-" fragment: drop it
                continue
            if out and out[-1]:
                out[-1].append((stripped, s, e))
                chunk.pop(0)
            else:
                chunk[0] = (stripped, s, e)
                break
        if chunk:
            out.append(chunk)
    return out


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
    # Final safety: no rendered line may start with a hyphen (reflow the
    # word back onto the previous line).
    chunks = _reflow_leading_hyphens(chunks)
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


def prepare_video_shot(video_path, duration, width, height, fallback_image=None):
    """
    Loads an AI-generated video file, scales and crops it to vertical 9:16 aspect ratio.

    A short AI clip is played ONCE, then the shot continues with a slow Ken
    Burns drift on the clip's final frame. (The old vfx.Loop fill made a 1s
    clip visibly snap back and repeat for the whole shot — "animated for a
    second then repeats".)

    If the video cannot be loaded, the scene's image is animated with a
    motion effect instead — NEVER a black screen.
    """
    from moviepy import VideoFileClip, ColorClip, concatenate_videoclips

    def _image_fallback(reason):
        if fallback_image and os.path.exists(fallback_image):
            print(f"[video_assembler] {reason}; using scene image instead of black.")
            return create_advanced_motion_effect(
                fallback_image, duration, width, height, "zoom_in")
        print(f"[video_assembler] {reason}; no image available — dark placeholder.")
        return ColorClip(size=(width, height), color=(15, 15, 25), duration=duration)

    try:
        clip = VideoFileClip(video_path)
    except Exception as e:
        return _image_fallback(f"Error loading AI video {video_path}: {e}")

    if not getattr(clip, "duration", 0):
        return _image_fallback(f"AI video has no duration ({video_path})")

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
        # Last resort: fall back to the scene image (exact duration) rather
        # than returning a short clip. A short clip makes the concatenated
        # content shorter than the audio, and with_duration() then pads the
        # tail with BLACK frames ("video stops, blank screen with music").
        # (2026-09-27 loop-test root cause of the 52s->30s+blank symptom.)
        print(f"[video_assembler] Tail-drift note ({e}); using scene image (exact duration).")
        return _image_fallback(f"Tail-drift failed for {video_path}")


def add_custom_transitions(clips, scenes, width, height):
    """
    Applies diverse cinematic transitions:
    - Speed ramp, Zoom burst in/out, Whip pan left/right, Glitch flash, RGB split, White flash, Dark pop, Cyber glow, Parallax slide.
    """
    from moviepy import ColorClip, concatenate_videoclips

    def _flash_for(trans):
        if trans in ['glitch_flash', 'glitch', 'rgb_split']:
            return [ColorClip(size=(width, height), color=(255, 20, 80), duration=0.03),
                    ColorClip(size=(width, height), color=(0, 240, 255), duration=0.03)]
        if trans in ['whip_pan_left', 'whip_pan_right', 'whip_pan', 'whip']:
            return [ColorClip(size=(width, height), color=(240, 248, 255), duration=0.05)]
        if trans in ['zoom_burst_in', 'zoom_burst_out', 'speed_ramp', 'flash', 'white_flash']:
            return [ColorClip(size=(width, height), color=(255, 255, 255), duration=0.05)]
        if trans in ['motion_blur_push', 'dark_pop', 'dark_fade']:
            return [ColorClip(size=(width, height), color=(10, 15, 26), duration=0.04)]
        if trans in ['cyber_glow', 'color_pop']:
            return [ColorClip(size=(width, height), color=(0, 255, 170), duration=0.04)]
        if trans in ['parallax_slide', 'parallax']:
            return [ColorClip(size=(width, height), color=(56, 189, 248), duration=0.04)]
        return []

    new_clips = []
    for i, c in enumerate(clips):
        if i < len(clips) - 1:
            scene = scenes[min(i, len(scenes)-1)] if scenes else {}
            trans = (scene.get('transition_type') or 'speed_ramp').lower().replace('-', '_')
            flashes = _flash_for(trans)
            flash_dur = sum(f.duration for f in flashes)
            # Trim the flash duration off the END of the scene clip so the
            # total stays exactly sum(scene spans). Inserted flashes used to
            # push every later scene ~0.05s late vs the audio/captions.
            # (2026-09-27 loop-test: caption/visual drift fix.)
            if flash_dur > 0 and c.duration > flash_dur + 0.2:
                c = c.subclipped(0, c.duration - flash_dur)
            new_clips.append(c)
            new_clips.extend(flashes)
        else:
            new_clips.append(c)

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


def _regenerate_dead_video(image_path, scene, topic_title, duration, output_dir):
    """Regenerate a missing/corrupt AI video from the scene's image.

    Writes a FRESH image-to-video motion script grounded in the video's
    title + the scene's narration/image prompt (the "title script context"),
    then renders it via generate_video_from_image. Returns the new video
    path, or None if regeneration failed.
    """
    try:
        from .free_prompting import _ask_chatgpt
        from .video_gen_ai import generate_video_from_image
    except Exception as e:
        print(f"[video_assembler] regen imports unavailable: {e}")
        return None
    title = (topic_title or scene.get("topic_title") or "").strip()
    narration = (scene.get("narration") or "")[:400]
    img_prompt = (scene.get("image_prompt") or "")[:400]
    motion = (scene.get("image_to_video_prompt") or "").strip()
    try:
        fresh = _ask_chatgpt(
            "You are a motion director for AI image-to-video. Write ONE motion "
            "script: the exact camera movement (slow push-in, pan, tilt, orbit, "
            "dolly) plus dynamic motion inside the frame (fog drift, particles, "
            "light flicker). Reply with ONLY the script, no extra text.",
            f"Video title: \"{title}\"\n"
            f"Scene voiceover: \"{narration}\"\n"
            f"The still image shows: \"{img_prompt}\"\n"
            f"Write one image-to-video motion script that continues this scene's "
            f"story and matches the video's title. Keep the camera motion slow "
            f"and smooth — the clip plays {duration:.0f} seconds.",
            max_new_tokens=300,
        )
        if fresh and fresh.strip():
            motion = fresh.strip()
            print(f"[video_assembler] Fresh motion script written from title context: {motion[:80]}...")
    except Exception as e:
        print(f"[video_assembler] Fresh motion script note: {e} — reusing scene prompt.")
    if not motion:
        motion = "slow cinematic push-in with gentle parallax drift, volumetric light"
    try:
        new_path = generate_video_from_image(
            image_path=image_path,
            prompt=motion,
            duration=duration,
            output_dir=output_dir,
        )
        if new_path and os.path.exists(new_path) and os.path.getsize(new_path) > 1000:
            print(f"[video_assembler] Regenerated dead video -> {new_path}")
            return new_path
        print("[video_assembler] Regeneration produced no usable file.")
    except Exception as e:
        print(f"[video_assembler] Regeneration failed: {e}")
    return None


def _scene_time_boundaries(scenes, timed_words, total_duration):
    """Per-scene (start, end) seconds so each scene's visuals cover exactly
    the span where its narration is spoken.

    The old code gave every scene an EQUAL share of the audio (total/n),
    which desynced video from voice whenever scenes had different narration
    lengths. Now each scene's span is derived from the word timings:
    scene i owns the timed words matching its narration word count. Falls
    back to narration-word-count proportional split when timings are absent.
    """
    n = max(1, len(scenes))
    total_duration = max(0.1, float(total_duration or 0))
    counts = [len((sc.get("narration") or "").split()) for sc in scenes]
    total_words = sum(counts)

    spans = []
    tw = [t for t in (timed_words or [])
          if t and t.get("word") and float(t.get("end", 0)) >= float(t.get("start", 0))]
    if tw and total_words > 0:
        # Walk the timed words sequentially, handing each scene a slice
        # proportional to its narration word count.
        cursor = 0
        prev_e = 0.0
        for i, c in enumerate(counts):
            if i < len(counts) - 1:
                take = round(len(tw) * c / total_words)
            else:
                take = len(tw) - cursor
            take = max(0, min(take, len(tw) - cursor))
            seg = tw[cursor:cursor + take]
            if seg:
                s = float(seg[0]["start"])
                e = float(seg[-1]["end"])
            else:
                # Rounding left no timed words for this scene (or it has no
                # narration): start where the previous scene ended.
                s = e = prev_e
            if i == 0:
                s = 0.0
            if i == len(counts) - 1:
                e = total_duration
            e = max(e, s + 0.25)
            spans.append((round(s, 2), round(e, 2)))
            cursor += take
            prev_e = e
    else:
        # No timings: split proportionally to narration word counts.
        cur = 0.0
        for i, c in enumerate(counts):
            frac = (c / total_words) if total_words > 0 else 1.0 / n
            nxt = total_duration if i == len(counts) - 1 else cur + total_duration * frac
            spans.append((round(cur, 2), round(max(nxt, cur + 0.25), 2)))
            cur = nxt
    # Monotonicity: no scene may start before the previous one ends.
    fixed = []
    prev_end = 0.0
    for s, e in spans:
        s = max(s, prev_end)
        e = max(e, s + 0.25)
        fixed.append((s, e))
        prev_end = e
    if fixed:
        fixed[-1] = (fixed[-1][0], round(total_duration, 2))
    return fixed


def _build_caption_events(word_timings_path, subtitle_path, script_words=None):
    """Word-level caption events: [(words_list, active_word_idx, start, end)].

    Real speech timings (faster-whisper) preferred; falls back to the
    estimated even-division timings from the SRT. Also drives BGM ducking.

    script_words (the exact words TTS spoke, in order): when given AND real
    word timings exist, the timed words are RECONCILED to the script words
    (captions.py:reconcile_words) so a mistranscription can never put wrong
    words on screen — captions always match the voice.
    """
    caption_events = []
    try:
        real_words = []
        if word_timings_path:
            try:
                from .captions import load_word_timings
                real_words = load_word_timings(word_timings_path)
            except Exception as wt_err:
                print(f"[video_assembler] Word-timing load note: {wt_err}")

        if real_words and script_words:
            try:
                from .captions import reconcile_words
                fixed = reconcile_words(script_words, real_words)
                if fixed:
                    print(f"[video_assembler] Caption words reconciled to script "
                          f"({len(fixed)} words) — captions match the voice.")
                    real_words = fixed
            except Exception as rc_err:
                print(f"[video_assembler] Caption reconcile note: {rc_err}")

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
    return caption_events


def _build_ducked_bgm(music_path, total_duration, speech_intervals,
                      duck_vol=0.08, gap_vol=0.22):
    """Background music that DUCKS under speech.

    The track is tiled to cover the whole video, then split at speech
    boundaries: quiet (duck_vol) while the narrator talks, louder
    (gap_vol) in the gaps. speech_intervals = [(start, end), ...].
    Returns an AudioClip or None.
    """
    from moviepy import AudioFileClip, concatenate_audioclips
    music = AudioFileClip(music_path)
    m_dur = getattr(music, "duration", 0) or 0
    if m_dur <= 0:
        return None
    # Tile the track so it covers the whole video.
    tiles, covered = [music], m_dur
    while covered < total_duration:
        tiles.append(music)
        covered += m_dur
    looped = (concatenate_audioclips(tiles) if len(tiles) > 1
              else tiles[0]).subclipped(0, total_duration)
    # Merge overlapping speech intervals.
    merged = []
    for s, e in sorted(speech_intervals):
        s = max(0.0, min(s, total_duration))
        e = max(0.0, min(e, total_duration))
        if e <= s:
            continue
        if merged and s <= merged[-1][1] + 0.10:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    if not merged:
        return looped.with_volume_scaled(gap_vol)
    segs = []
    t = 0.0
    for s, e in merged:
        if s > t + 0.05:
            segs.append(looped.subclipped(t, s).with_volume_scaled(gap_vol)
                        .audio_fadein(0.15).audio_fadeout(0.15))
        segs.append(looped.subclipped(max(t, s), e).with_volume_scaled(duck_vol)
                    .audio_fadein(0.15).audio_fadeout(0.15))
        t = e
    if t < total_duration - 0.05:
        segs.append(looped.subclipped(t, total_duration).with_volume_scaled(gap_vol)
                    .audio_fadein(0.15).audio_fadeout(0.15))
    return concatenate_audioclips(segs) if len(segs) > 1 else segs[0]


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
    word_timings_path: str = None,
    script_text: str = None,
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
    # ── Word timings + script words: each scene's visuals must cover exactly
    # the span where its narration is spoken (user report 2026-09-27: video
    # "all messed up" — the old equal split desynced video from voice).
    script_words = (script_text or "").split()
    if not script_words:
        script_words = [w for sc in scenes for w in (sc.get("narration") or "").split()]
    timed_words = []
    if word_timings_path:
        try:
            from .captions import load_word_timings
            timed_words = load_word_timings(word_timings_path) or []
        except Exception:
            timed_words = []
    scene_bounds = _scene_time_boundaries(scenes, timed_words, total_duration)
    print(f"[video_assembler] Scene time spans: "
          + ", ".join(f"{s:.1f}-{e:.1f}s" for s, e in scene_bounds))
    video_clips = []
    current_time = 0.0
    boundary_times = []
    
    effects_list = ['zoom_burst_in', 'zoom_burst_out', 'whip_pan_left', 'whip_pan_right', 'speed_ramp', 'motion_blur_push', 'glitch_flash']

    for idx, scene in enumerate(scenes):
        scene_dur = scene_bounds[idx][1] - scene_bounds[idx][0]
        clips_before = len(video_clips)
        video_paths = scene.get('video_paths', [])
        img_paths = scene.get('image_paths', [])
        
        if video_paths:
            # ── Dead-video guard (user report 2026-09-27: "rest was just black
            # screen"). A missing/corrupt AI video is REGENERATED with a fresh
            # motion script written from the title + script context; only if
            # regeneration fails does the scene fall back to its images.
            live = [vp for vp in video_paths
                    if vp and os.path.exists(vp) and os.path.getsize(vp) > 1000]
            dead = [vp for vp in video_paths if vp not in set(live)]
            if dead:
                shot_est = scene_dur / max(1, len(video_paths))
                regen = []
                for d_i, _dv in enumerate(dead):
                    src_img = (img_paths[d_i] if d_i < len(img_paths)
                               else (img_paths[0] if img_paths else None))
                    if src_img and os.path.exists(src_img):
                        new_vp = _regenerate_dead_video(
                            src_img, scene, topic_title, shot_est, output_dir)
                        if new_vp:
                            regen.append(new_vp)
                if regen:
                    print(f"[video_assembler] Scene {idx+1}: regenerated "
                          f"{len(regen)}/{len(dead)} dead video(s) from title context.")
                still_dead = len(dead) - len(regen)
                if still_dead:
                    print(f"[video_assembler] Scene {idx+1}: {still_dead} video(s) "
                          f"unrecoverable; falling back to images (no black screen).")
                video_paths = live + regen
            else:
                video_paths = live

        if video_paths:
            shot_duration = scene_dur / len(video_paths)
            fb_img = (img_paths or [None])[0]
            for shot_idx, video_path in enumerate(video_paths):
                vc = prepare_video_shot(video_path, shot_duration, 1080, 1920,
                                        fallback_image=fb_img)
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
    # SAFETY (2026-09-27 loop-test): with_duration() on content SHORTER than
    # total_duration pads the tail with BLACK frames (the "30s video + blank
    # screen with music" symptom). If content runs short, extend the last
    # frame as a freeze instead of ever emitting black.
    try:
        _content_dur = float(final_video.duration or 0)
    except Exception:
        _content_dur = 0.0
    if _content_dur < total_duration - 0.05:
        from moviepy import ImageClip, concatenate_videoclips as _concat
        import numpy as _np
        _gap = total_duration - _content_dur
        try:
            _last = final_video.get_frame(max(0.0, _content_dur - 0.04))
            _freeze = ImageClip(_last).with_duration(_gap + 0.1)
            final_video = _concat([final_video, _freeze],
                                  method="compose").with_duration(total_duration)
            print(f"[video_assembler] Content was {_content_dur:.2f}s < "
                  f"audio {total_duration:.2f}s; froze last frame for "
                  f"{_gap:.2f}s (no black tail).")
        except Exception as _e:
            print(f"[video_assembler] Freeze-pad note ({_e}); keeping content as-is.")
    final_video = final_video.with_duration(total_duration)

    # 3. Audio Mixing & Topic-Synced Background Music
    creative_brain = get_creative_brain()
    mix_levels = creative_brain.get_audio_mix()
    tracks = [audio_clip.with_volume_scaled(mix_levels["voice"])]

    # Word timings first: speech intervals drive BGM ducking (music drops
    # low UNDER the narration, rises in the gaps). Built once, reused by
    # the karaoke captions in section 4.
    caption_events = _build_caption_events(word_timings_path, subtitle_path, script_words)
    speech_intervals = [(s, e) for (_w, _i, s, e) in caption_events]

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
            ducked = _build_ducked_bgm(music_path, total_duration, speech_intervals)
            if ducked is not None:
                tracks.append(ducked)
                print(f"[video_assembler] BGM ducked under {len(speech_intervals)} speech event(s).")
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
    # caption_events was already built in section 3 (it also drives BGM
    # ducking); rebuild only if something cleared it.
    if not caption_events:
        caption_events = _build_caption_events(word_timings_path, subtitle_path, script_words)

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
        creative_brain.record_learning_session(
            video_id=output_filename,
            topic=topic_title,
            viral_score=viral_score,
            transitions_used=[s.get("transition_type", "cut") for s in scenes],
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
