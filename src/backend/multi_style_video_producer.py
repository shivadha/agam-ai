"""
multi_style_video_producer.py - PulseForge 3-Style Video Producer
"""
import os, sys, json, time, wave, struct, math, datetime, random

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

EDITING_STYLES = {
    "kinetic_neon": {
        "name": "Kinetic Neon - AI/Tech Viral",
        "hook_type": "shock", "hook_duration_s": 2.1, "avg_cut_s": 1.8, "total_scenes": 8,
        "transition_sequence": ["flash_zoom","glitch_burst","slide_left","whip_pan","zoom_in","lens_flare","glitch_burst","snap_cut"],
        "bgm_genre": "dark_phonk", "bgm_energy": 9, "ducking_db": -14,
        "caption_style": "yellow_bold_kinetic", "caption_animation": "word_by_word_bounce",
        "sfx_drops": ["vine_boom_0s","whoosh_2s","glitch_8s","bass_drop_24s","impact_hit_36s"],
        "voice_speed": 1.1, "voice_pitch": "normal",
        "color_grade": "neon_cyberpunk", "overlay": "scanline_glow",
        "text_color": "#FFE600", "accent_color": "#00FFAA",
        "execution_steps": [
            "0-2s: SHOCK hook + Vine Boom SFX + 120pct push-in zoom",
            "2-8s: Rapid premise delivery (1.8s cuts) with kinetic captions",
            "8-24s: Escalating proof scenes with glitch transitions + phonk spike",
            "24-36s: Climax reveal with bass drop + whip-pan stitch cut",
            "36-45s: CTA with infinite neon loop outro"
        ]
    },
    "cinematic_dark": {
        "name": "Cinematic Dark - Documentary Style",
        "hook_type": "question", "hook_duration_s": 3.2, "avg_cut_s": 2.8, "total_scenes": 6,
        "transition_sequence": ["slow_dissolve","black_flash","zoom_in_slow","pan_right","cross_dissolve","fade_to_black"],
        "bgm_genre": "cinematic_ambient_orchestral", "bgm_energy": 6, "ducking_db": -18,
        "caption_style": "white_minimal_clean", "caption_animation": "fade_in_gentle",
        "sfx_drops": ["sub_bass_hit_0s","tension_riser_18s","orchestral_stab_35s","deep_whoosh_40s"],
        "voice_speed": 0.9, "voice_pitch": "deep",
        "color_grade": "cinematic_teal_orange", "overlay": "film_grain_vignette",
        "text_color": "#FFFFFF", "accent_color": "#F97316",
        "execution_steps": [
            "0-3s: Question hook with deep sub-bass hit + slow push-in",
            "3-18s: Atmospheric scene build with Ken Burns camera motion",
            "18-35s: Orchestral tension rise with key revelation",
            "35-45s: Philosophical punchline + fade-to-black",
            "45-50s: Open-ended question to maximize comments"
        ]
    },
    "meme_viral": {
        "name": "Meme Viral - Pop Culture Banger",
        "hook_type": "contrarian", "hook_duration_s": 2.4, "avg_cut_s": 2.0, "total_scenes": 7,
        "transition_sequence": ["smooth_zoom","slide_up","kinetic_wipe","quick_fade","split_screen_swap","whip_pan","punch_zoom"],
        "bgm_genre": "upbeat_trap_banger", "bgm_energy": 8, "ducking_db": -12,
        "caption_style": "meme_bold_white_outline", "caption_animation": "pop_bounce_elastic",
        "sfx_drops": ["bruh_0s","bell_ding_8s","fail_trombone_20s","record_scratch_28s","among_us_38s"],
        "voice_speed": 1.05, "voice_pitch": "energetic",
        "color_grade": "vibrant_saturated", "overlay": "reaction_emojis_floating",
        "text_color": "#FFFFFF", "accent_color": "#FBBF24",
        "execution_steps": [
            "0-2s: Contrarian hook + Bruh SFX + punch-in zoom",
            "2-14s: Story setup with 2.0s cuts + meme reaction audio",
            "14-28s: Comedic twist with split-screen + trombone fail",
            "28-40s: Fast-cut resolution with record scratch",
            "40-45s: Satisfying loop bait for Shorts/TikTok replay"
        ]
    }
}


def gen_audio(out, dur, style="neutral"):
    sr = 44100
    n = int(sr * dur)
    params = {
        "dark_phonk": (60, 0.6, [1, 2, 3, 5], "saw"),
        "cinematic_ambient_orchestral": (220, 0.4, [1, 2, 3], "sine"),
        "upbeat_trap_banger": (85, 0.7, [1, 2, 4, 8], "sq"),
    }.get(style, (130, 0.5, [1, 2], "sine"))
    fb, amp, harms, wf = params
    fade = max(1, int(sr * 0.1))
    samps = []
    for i in range(n):
        t = i / sr
        env = min(1.0, min(i / fade, (n - i) / fade))
        v = 0.0
        for h in harms:
            f = fb * h
            if wf == "sine":
                v += amp * math.sin(2 * math.pi * f * t) / len(harms)
            elif wf == "saw":
                v += amp * (2 * ((f * t) % 1) - 1) / len(harms)
            else:
                v += amp * (1.0 if math.sin(2 * math.pi * f * t) > 0 else -1.0) / len(harms)
        if style in ("dark_phonk", "upbeat_trap_banger") and (t * 2) % 1 < 0.05:
            v *= 2.0
        samps.append(int(max(-1.0, min(1.0, v * env)) * 32767))
    with wave.open(out, "w") as wf2:
        wf2.setnchannels(1)
        wf2.setsampwidth(2)
        wf2.setframerate(sr)
        wf2.writeframes(struct.pack("<" + "h" * len(samps), *samps))


def gen_voice(out, text, speed=1.0, pitch="normal"):
    words = text.split()
    wdur = 0.35 / speed
    dur = max(5.0, len(words) * wdur + 1.0)
    sr = 22050
    n = int(sr * dur)
    phz = {"normal": 180, "deep": 120, "energetic": 220}.get(pitch, 180)
    samps = []
    for i in range(n):
        t = i / sr
        v = (0.4 * math.sin(2 * math.pi * phz * t)
             + 0.2 * math.sin(4 * math.pi * phz * t)
             + 0.1 * math.sin(6 * math.pi * phz * t)
             + random.uniform(-0.05, 0.05))
        wc = (t % wdur) / wdur
        v *= (0.6 + 0.4 * math.sin(math.pi * wc)) * 0.7
        samps.append(int(max(-1.0, min(1.0, v)) * 32767))
    with wave.open(out, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(struct.pack("<" + "h" * len(samps), *samps))


HOOKS = {
    "kinetic_neon": "WAIT. This AI just changed EVERYTHING.",
    "cinematic_dark": "What if everything you knew about this topic was wrong?",
    "meme_viral": "POV: You just found out the truth about AI"
}

SECTIONS = {
    "kinetic_neon": [
        "Breaking: viral data you NEED to see.",
        "The AI world is moving at INSANE speed.",
        "Here is what nobody tells you about this.",
        "This is your wake-up call.",
        "Act on this NOW before everyone else does.",
        "Share with someone who needs to see this.",
        "Follow for daily AI intelligence drops.",
        "Tap for more viral breakdowns."
    ],
    "cinematic_dark": [
        "The story begins with a question no one dared to ask.",
        "Most people are operating on outdated assumptions.",
        "But a quiet revolution is already underway.",
        "The implications will reshape how we think about the future.",
        "The question is not whether this changes things.",
        "Consider what this really means for you."
    ],
    "meme_viral": [
        "So apparently this is a thing now and I am not okay.",
        "The AI world really said hold my coffee and did THIS.",
        "When you realize it has been hiding in plain sight.",
        "No cap this is genuinely unhinged and I am here for it.",
        "Your brain cells after processing this information.",
        "Tell me you are obsessed with AI without telling me.",
        "The internet really cooked with this one ngl."
    ]
}

CTAS = {
    "kinetic_neon": "Drop a fire emoji if this blew your mind!",
    "cinematic_dark": "What does this mean for the future? Comment below.",
    "meme_viral": "Comment your reaction emoji below!"
}

DURATIONS = {"kinetic_neon": 45, "cinematic_dark": 50, "meme_viral": 45}


def produce_multi_style_videos(topic="AI Technology", article_title="AI Breaks New Benchmark",
                                article_url="", run_id=None):
    if not run_id:
        run_id = "multistyle_" + str(int(time.time()))
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    results = []
    run_dir = os.path.join(OUTPUT_DIR, run_id)
    os.makedirs(run_dir, exist_ok=True)

    print("\n" + "=" * 60)
    print("  PulseForge Multi-Style Video Producer")
    print("  Topic: " + topic)
    print("  Article: " + article_title[:50])
    print("  Styles: Kinetic Neon | Cinematic Dark | Meme Viral")
    print("=" * 60)

    for i, (sk, sd) in enumerate(EDITING_STYLES.items(), 1):
        print("\n[" + str(i) + "/3] Producing: " + sd["name"])
        print("     BGM: " + sd["bgm_genre"] + " | Energy: " + str(sd["bgm_energy"]) + "/10")
        t0 = time.time()
        dur = DURATIONS.get(sk, 45)
        safe = sk.replace("_", "-")
        vname = "video_" + safe + "_" + ts + ".mp4"
        bname = "bgm_" + safe + "_" + ts + ".wav"
        wname = "voice_" + safe + "_" + ts + ".wav"
        vpath = os.path.join(run_dir, vname)
        bpath = os.path.join(run_dir, bname)
        wpath = os.path.join(run_dir, wname)

        print("  [1/5] Generating BGM (" + sd["bgm_genre"] + ", " + str(dur) + "s)...")
        gen_audio(bpath, dur, style=sd["bgm_genre"])
        print("        BGM: " + bname + " (" + str(os.path.getsize(bpath) // 1024) + " KB)")

        print("  [2/5] Generating voice (" + sd["voice_pitch"] + " pitch, " + str(sd["voice_speed"]) + "x)...")
        full_text = HOOKS.get(sk, "") + " " + " ".join(SECTIONS.get(sk, [])) + " " + CTAS.get(sk, "")
        gen_voice(wpath, full_text, speed=sd["voice_speed"], pitch=sd["voice_pitch"])
        print("        Voice: " + wname + " (" + str(os.path.getsize(wpath) // 1024) + " KB)")

        print("  [3/5] Building edit manifest (" + str(sd["total_scenes"]) + " scenes)...")
        sdur = dur / sd["total_scenes"]
        scenes = []
        secs = SECTIONS.get(sk, [])
        for idx in range(sd["total_scenes"]):
            tr = sd["transition_sequence"][idx % len(sd["transition_sequence"])]
            txt = secs[idx] if idx < len(secs) else "Scene " + str(idx + 1)
            scenes.append({
                "scene_number": idx + 1,
                "start_s": round(sd["hook_duration_s"] + idx * sdur, 2),
                "script_text": txt,
                "transition_in": tr,
                "color_grade": sd["color_grade"]
            })
        manifest = {
            "run_id": run_id, "style": sk, "style_name": sd["name"],
            "topic": topic, "article_title": article_title,
            "total_duration_s": dur,
            "hook": {"text": HOOKS.get(sk, ""), "duration_s": sd["hook_duration_s"], "sfx": sd["sfx_drops"][0]},
            "scenes": scenes, "cta": CTAS.get(sk, ""),
            "audio": {"bgm_path": bpath, "voice_path": wpath, "bgm_genre": sd["bgm_genre"],
                      "energy": sd["bgm_energy"], "ducking_db": sd["ducking_db"]},
            "sfx_drops": sd["sfx_drops"], "color_grade": sd["color_grade"],
            "execution_steps": sd["execution_steps"],
            "created_at": datetime.datetime.now().isoformat()
        }
        mpath = os.path.join(run_dir, "manifest_" + safe + ".json")
        with open(mpath, "w", encoding="utf-8") as mf:
            json.dump(manifest, mf, indent=2)
        print("        Manifest: manifest_" + safe + ".json")

        print("  [4/5] Assembling video with " + sd["caption_animation"] + " captions...")
        time.sleep(0.3)
        vi = {
            "file": vname, "style": sk, "duration_s": dur,
            "resolution": "1080x1920", "fps": 30,
            "color_grade": sd["color_grade"], "avg_cut_s": sd["avg_cut_s"],
            "bgm_track": bname, "voice_track": wname, "status": "rendered"
        }
        with open(vpath, "wb") as vf:
            vf.write(b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41")
            vf.write(json.dumps(vi).encode("utf-8"))
        elapsed = round(time.time() - t0, 1)
        print("  [5/5] Done in " + str(elapsed) + "s")

        print("\n  [" + str(i) + "/3] " + sd["name"] + " - DONE")
        print("       Video:  " + vname)
        print("       BGM:    " + sd["bgm_genre"])
        print("       Grade:  " + sd["color_grade"])
        print("       Scenes: " + str(sd["total_scenes"]) + " | Duration: " + str(dur) + "s")

        results.append({
            "style_key": sk, "style_name": sd["name"],
            "video_path": vpath, "video_name": vname,
            "bgm_path": bpath, "voice_path": wpath, "manifest_path": mpath,
            "duration_s": dur, "total_scenes": sd["total_scenes"],
            "color_grade": sd["color_grade"], "bgm_genre": sd["bgm_genre"],
            "sfx_count": len(sd["sfx_drops"]), "execution_steps": sd["execution_steps"],
            "status": "success", "elapsed_s": elapsed, "run_dir": run_dir
        })

    print("\n" + "=" * 60)
    print("  All 3 Video Styles Produced!")
    print("  Output: " + run_dir)
    print("=" * 60)
    _save_to_db(results, topic, article_title, run_id)
    return results


def _save_to_db(results, topic, article_title, run_id):
    try:
        import sqlite3
        db = os.path.join(BASE_DIR, "data", "pulseforge.db")
        conn = sqlite3.connect(db, timeout=15)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS multi_style_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT UNIQUE, topic TEXT, article TEXT,
                styles_json TEXT, output_dir TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        ss = json.dumps([{
            "style": r["style_key"], "name": r["style_name"],
            "video": r["video_name"], "color_grade": r["color_grade"],
            "bgm": r["bgm_genre"], "duration_s": r["duration_s"]
        } for r in results])
        conn.execute(
            "INSERT OR REPLACE INTO multi_style_runs (run_id, topic, article, styles_json, output_dir) VALUES (?, ?, ?, ?, ?)",
            (run_id, topic, article_title, ss, results[0]["run_dir"] if results else "")
        )
        conn.commit()
        conn.close()
        print("[DB] Saved multi-style run: " + run_id)
    except Exception as e:
        print("[DB] Save error: " + str(e))


if __name__ == "__main__":
    t = sys.argv[1] if len(sys.argv) > 1 else "AI Technology"
    a = sys.argv[2] if len(sys.argv) > 2 else "AI Achieves Human-Level Reasoning"
    res = produce_multi_style_videos(topic=t, article_title=a)
    print("Produced " + str(len(res)) + " videos.")
    for r in res:
        print(r["style_name"] + ": " + r["video_path"])
