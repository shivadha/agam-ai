"""Tests for the anti-slop editing upgrades (B1 kinetic captions, B2 cadence,
B3 SFX, B4 hook bans) and the SDXL-Lightning image stack (C1–C3)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.backend import video_assembler
from src.backend import hook_gen
from src.backend.image_gen import (
    build_image_prompt,
    _pick_image_checkpoint,
    _is_distilled_checkpoint,
    STYLE_ANCHOR,
    ANTI_SLOP_NEGATIVE,
)


def _events(n_words=9, word_dur=0.4):
    # n words at word_dur each, as (words, active_idx, start, end) events.
    words = [f"W{i+1}" for i in range(n_words)]
    events = []
    for i, w in enumerate(words):
        s = i * word_dur
        events.append(([w], 0, s, s + word_dur))
    return events


# ── B1: kinetic captions ─────────────────────────────────────────────────

def test_kinetic_chunks_max_3_words(tmp_path):
    ass = str(tmp_path / "k.ass")
    video_assembler.build_caption_ass(_events(9), ass)
    texts = []
    with open(ass, encoding="utf-8") as f:
        for line in f:
            if line.startswith("Dialogue:"):
                texts.append(line.split(",,", 1)[1])
    assert texts
    for t in texts:
        # strip ASS override tags, then count visible words (≤3 per page)
        import re
        visible = re.sub(r"\{[^}]*\}", "", t)
        assert len(visible.split()) <= 3, visible


def test_kinetic_gold_highlight_and_pop(tmp_path):
    ass = str(tmp_path / "k.ass")
    video_assembler.build_caption_ass(_events(3), ass)
    content = open(ass, encoding="utf-8").read()
    assert "Montserrat ExtraBold" in content          # kinetic font
    assert "&H003FD2FF" in content                    # gold #FFD23F
    assert "\\t(0,150,\\fscx100\\fscy100)" in content  # pop animation


def test_kinetic_lower_third_margin(tmp_path):
    ass = str(tmp_path / "k.ass")
    video_assembler.build_caption_ass(_events(2), ass)
    content = open(ass, encoding="utf-8").read()
    assert "80,80,360,1" in content  # MarginV 360 (lower-third)


# ── B2: ≤3s visual cadence ───────────────────────────────────────────────

def test_split_media_caps_shot_at_3s():
    shots = video_assembler._split_scene_media(["a.jpg", "b.jpg"], 9.0)
    assert len(shots) == 3
    assert all(abs(d - 3.0) < 1e-6 for _p, d in shots)
    assert [p for p, _d in shots] == ["a.jpg", "b.jpg", "a.jpg"]  # cycled


def test_split_media_short_scene_untouched():
    shots = video_assembler._split_scene_media(["a.jpg"], 2.5)
    assert shots == [("a.jpg", 2.5)]


def test_split_media_sums_to_scene():
    shots = video_assembler._split_scene_media(["a.jpg", "b.jpg", "c.jpg"], 7.7)
    assert abs(sum(d for _p, d in shots) - 7.7) < 1e-6
    assert all(d <= 3.0 + 1e-6 for _p, d in shots)


# ── B3: procedural chime exists ──────────────────────────────────────────

def test_procedural_chime_writes_wav(tmp_path):
    out = str(tmp_path / "chime.wav")
    video_assembler.generate_procedural_chime(out)
    assert os.path.exists(out) and os.path.getsize(out) > 1000


# ── B4: banned hook openers ──────────────────────────────────────────────

def test_hook_bans_slop_openers():
    assert not hook_gen._is_valid_hook("Did you know this secret")
    assert not hook_gen._is_valid_hook("You won't believe this trick")
    assert hook_gen._is_valid_hook("This secret changes everything")


def test_hook_system_prompt_bans_slop_openers():
    prompt = hook_gen._build_system_prompt("curiosity")
    assert "Did you know" in prompt and "You won't believe" in prompt


# ── C1/C3: image stack ───────────────────────────────────────────────────

def test_pick_checkpoint_prefers_lightning():
    ckpts = ["sd_xl_base.safetensors", "sdxl_lightning_8step.safetensors",
             "svd_xt.safetensors"]
    name, distilled = _pick_image_checkpoint(ckpts)
    assert name == "sdxl_lightning_8step.safetensors"
    assert distilled is True


def test_pick_checkpoint_excludes_video_models():
    name, _ = _pick_image_checkpoint(["svd.safetensors", "wan_i2v.safetensors"])
    assert name is None


def test_pick_checkpoint_prefers_xl_over_sd15():
    name, distilled = _pick_image_checkpoint(["v1-5-pruned.safetensors",
                                              "dreamshaper_xl.safetensors"])
    assert name == "dreamshaper_xl.safetensors"
    assert distilled is False


def test_distilled_detection():
    assert _is_distilled_checkpoint("sdxl_lightning_8step.safetensors")
    assert _is_distilled_checkpoint("sdxl_turbo.safetensors")
    assert not _is_distilled_checkpoint("sd_xl_base_1.0.safetensors")


def test_build_image_prompt_appends_anchor_and_composition():
    p = build_image_prompt("a street vendor selling chai at dawn")
    assert "Kodak Portra 400" in p
    assert "no text" in p
    assert "a street vendor selling chai at dawn" in p


def test_build_image_prompt_idempotent():
    once = build_image_prompt("a cat on a scooter")
    assert build_image_prompt(once) == once


def test_anti_slop_negative_covers_tells():
    for tell in ("plastic skin", "cgi", "text", "watermark", "bad hands",
                 "gradient background"):
        assert tell in ANTI_SLOP_NEGATIVE
