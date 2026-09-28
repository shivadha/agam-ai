"""Tests for TTS script normalization (anti-slop: machine-read tokens)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.backend.tts_normalize import (
    normalize_script_for_tts,
    number_to_words,
    spoken_sidecar_path,
)


def test_rupee_lakh():
    out = normalize_script_for_tts("It costs ₹10L per year.")
    assert "ten lakh rupees" in out
    assert "₹" not in out and "10L" not in out


def test_rupee_crore_decimal():
    out = normalize_script_for_tts("valued at ₹2.5Cr")
    assert "two crore" in out and "rupees" in out
    assert "₹" not in out


def test_rupee_plain():
    out = normalize_script_for_tts("pay ₹500 now")
    assert "five hundred rupees" in out


def test_percent():
    out = normalize_script_for_tts("grew 45% last quarter")
    assert "forty five percent" in out
    assert "%" not in out


def test_abbreviations_spelled_out():
    out = normalize_script_for_tts("An MBA in AI from an IIT")
    assert "M-B-A" in out and "A-I" in out and "I-I-T" in out


def test_year_stays_year_like():
    out = normalize_script_for_tts("in 2026 everything changed")
    assert "twenty twenty six" in out
    assert "2026" not in out


def test_markdown_stripped():
    out = normalize_script_for_tts("This is **very** important #hook")
    assert "*" not in out and "#" not in out
    assert "very" in out


def test_prosody_punctuation_preserved():
    out = normalize_script_for_tts("Wait — this changes everything… listen.")
    assert "—" in out and "…" in out


def test_idempotent():
    once = normalize_script_for_tts("It costs ₹10L, up 45% for MBA grads in 2026.")
    assert normalize_script_for_tts(once) == once


def test_empty_safe():
    assert normalize_script_for_tts("") == ""
    assert normalize_script_for_tts(None) == ""


def test_number_to_words_indian_system():
    assert number_to_words(100000) == "one lakh"
    assert number_to_words(2500000) == "twenty five lakh"
    assert number_to_words(10000000) == "one crore"
    assert number_to_words(45) == "forty five"


def test_sidecar_path():
    assert spoken_sidecar_path("/tmp/out/audio.mp3") == "/tmp/out/audio.spoken.txt"
    assert spoken_sidecar_path("C:/x/v.wav") == "C:/x/v.spoken.txt"
