"""Tests for the 2026-09-27 user feedback round (5 issues).

1. Title + description saved in DB BEFORE the script is generated; the
   script is written FROM them.
2. (covered by ordering test below + existing chain tests)
3. Image relevance: no-text guard on prompts + concrete-noun rules.
4. Image-to-video minimum > 8s (9s).
5. No black screen: dead videos fall back to scene images.
6. BGM ducks under speech; Indian-accent TTS default (en-IN-PrabhatNeural).
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import src.database as database
from src.backend import video_gen_ai, voice_gen
from src.backend import video_assembler


# ── Issue 2: title/description in DB, script grounded in them ────────────────

def test_workflow_runs_schema_has_title_description():
    src = inspect.getsource(database.init_db)
    assert "title       TEXT" in src or "title TEXT" in src
    assert "description" in src
    # legacy-DB migration present
    assert "ADD COLUMN" in src and "workflow_runs" in src


def test_save_and_get_run_title_description(tmp_path, monkeypatch):
    db_file = str(tmp_path / "t.db")
    monkeypatch.setattr(database, "DB_PATH", db_file)
    database.init_db()
    database.record_workflow_run("run123", "test run")
    database.save_run_title_description("run123", "My Title", "My Desc #Shorts")
    got = database.get_run_title_description("run123")
    assert got["title"] == "My Title"
    assert got["description"] == "My Desc #Shorts"
    # legacy row without title still reads back as empty strings
    database.record_workflow_run("run999", "legacy")
    got2 = database.get_run_title_description("run999")
    assert got2 == {"title": "", "description": ""}


def test_gen_script_saves_title_before_generating():
    from src.engine import orchestrator as orch_mod
    src = inspect.getsource(orch_mod.WorkflowEngine.execute_node)
    gen_block = src.split("node_type == 'gen-script'")[1]
    # cut the block at the next node-type branch
    cut = len(gen_block)
    for marker in ("node_type == 'gen-title'", "node_type == 'gen-desc'",
                   "node_type == 'gen-tags'", "node_type == 'tts'"):
        i = gen_block.find(marker)
        if 0 < i < cut:
            cut = i
    gen_block = gen_block[:cut]
    save_i = gen_block.find("save_run_title_description")
    gen_i = gen_block.find("generate_video_content(")
    assert save_i != -1 and gen_i != -1 and save_i < gen_i, \
        "title/description must be saved BEFORE generate_video_content is called"
    # the script prompt carries the saved title/description
    assert "VIDEO TITLE" in gen_block
    # result uses the saved (authoritative) title/description
    assert '"title": title' in gen_block


# ── Issue 3 (image relevance): no-text guard ─────────────────────────────────

def test_image_prompt_no_text_guard():
    from src.backend import free_prompting
    src = inspect.getsource(free_prompting.ensure_image_prompts)
    assert "NEVER include text" in src
    assert "CONCRETE visual nouns" in src


def test_generate_images_appends_no_text_clause():
    from src.backend import image_gen
    src = inspect.getsource(image_gen.generate_images_for_scenes)
    assert "no text, no words" in src
    src2 = inspect.getsource(image_gen.generate_image)
    assert "no text, no words" in src2


# ── Issue 4: img-to-video > 8s ───────────────────────────────────────────────

def test_min_shot_seconds_above_8():
    assert video_gen_ai.MIN_SHOT_SECONDS > 8.0


# ── Issue 5: no black screen ─────────────────────────────────────────────────

def test_prepare_video_shot_accepts_fallback_image():
    sig = inspect.signature(video_assembler.prepare_video_shot)
    assert "fallback_image" in sig.parameters


def test_dead_videos_dropped_before_black():
    src = inspect.getsource(video_assembler.assemble_cinematic_video)
    assert "dropped" in src and "dead" in src
    assert "falling back to images" in src
    # failure path inside prepare_video_shot prefers the scene image
    psrc = inspect.getsource(video_assembler.prepare_video_shot)
    assert "create_advanced_motion_effect" in psrc
    assert "color=(0, 0, 0)" not in psrc, "pure-black fallback must be gone"


# ── Issue 6a: BGM ducking ────────────────────────────────────────────────────

def test_ducked_bgm_helper_volumes():
    src = inspect.getsource(video_assembler._build_ducked_bgm)
    assert "duck_vol" in src and "gap_vol" in src
    sig = inspect.signature(video_assembler._build_ducked_bgm)
    assert sig.parameters["duck_vol"].default < sig.parameters["gap_vol"].default


def test_assembler_uses_ducked_bgm_not_constant():
    src = inspect.getsource(video_assembler.assemble_cinematic_video)
    assert "_build_ducked_bgm" in src
    assert "with_volume_scaled(0.16)" not in src, \
        "constant-volume BGM must be replaced by ducking"


def test_caption_events_built_once_and_reused():
    src = inspect.getsource(video_assembler.assemble_cinematic_video)
    assert "_build_caption_events" in src
    # built before mixing (drives ducking), reused by captions
    assert src.find("_build_caption_events") < src.find("mixed_audio")


# ── Issue 6b: Indian accent TTS ──────────────────────────────────────────────

def test_indian_voice_routing():
    r = voice_gen._resolve_tts_provider
    assert r("en-IN-PrabhatNeural", "auto") == "edge-tts"
    assert r("en-IN-NeerjaNeural", "auto") == "edge-tts"
    assert r("en-US-AriaNeural", "auto") == "edge-tts"
    assert r("af_heart", "auto") == "kokoro"
    assert r("af_heart", "kokoro") == "kokoro"
    assert r("en-IN-PrabhatNeural", "kokoro") == "edge-tts", \
        "explicit kokoro must not silently swallow an Edge voice id"


def test_orchestrator_tts_defaults_to_indian_voice():
    from src.engine import orchestrator as orch_mod
    src = inspect.getsource(orch_mod.WorkflowEngine.execute_node)
    assert "node_data.get('voice', 'en-IN-PrabhatNeural')" in src
    assert "en-US-ChristopherNeural" not in src
