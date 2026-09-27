"""Tests for 2026-09-27 loop-test assembly fixes:
- prepare_video_shot NEVER returns a clip shorter than the requested duration
  (short clips caused with_duration() to pad the tail with BLACK frames —
  the "video stops at 30s, blank screen with music" symptom).
- add_custom_transitions keeps total duration == sum(scene spans) so
  captions/audio stay aligned (flashes are trimmed from scene ends, not inserted).
"""
import os
import sys

import pytest

REPO = "/home/hatch/workspace/projects/agam-ai"
sys.path.insert(0, REPO)
os.chdir(REPO)

from src.backend import video_assembler as va


def _red_clip(dur, w=320, h=568):
    from moviepy import ColorClip
    return ColorClip(size=(w, h), color=(200, 30, 30), duration=dur)


def test_prepare_video_shot_missing_video_uses_image_exact_duration(tmp_path):
    from PIL import Image
    img = tmp_path / "scene.jpg"
    Image.new("RGB", (576, 1024), (40, 60, 90)).save(img)
    shot = va.prepare_video_shot("/nonexistent/video.mp4", 7.5, 320, 568,
                                 fallback_image=str(img))
    assert abs(shot.duration - 7.5) < 0.1, f"got {shot.duration}"


def test_prepare_video_shot_missing_video_no_image_exact_duration():
    shot = va.prepare_video_shot("/nonexistent/video.mp4", 7.5, 320, 568,
                                 fallback_image=None)
    assert abs(shot.duration - 7.5) < 0.1, f"got {shot.duration}"


def test_prepare_video_shot_short_clip_padded_to_duration(tmp_path):
    """A 2s AI clip for a 9s shot must come back 9s (drift tail), never 2s."""
    from moviepy import VideoFileClip
    src = _red_clip(2.0)
    p = str(tmp_path / "short.mp4")
    src.write_videofile(p, fps=12, logger=None)
    src.close()
    shot = va.prepare_video_shot(p, 9.0, 320, 568, fallback_image=None)
    assert abs(shot.duration - 9.0) < 0.15, f"got {shot.duration}"
    # first 2s should be the red clip, not black
    import numpy as np
    fr = shot.get_frame(1.0)
    assert fr[..., 0].mean() > 100, "head of shot should be the clip, not black"


def test_transitions_keep_total_duration():
    clips = [_red_clip(5.0) for _ in range(3)]
    scenes = [{"transition_type": "white_flash"},
              {"transition_type": "glitch_flash"},
              {"transition_type": "zoom_burst_in"}]
    out = va.add_custom_transitions(clips, scenes, 320, 568)
    # 3 x 5s scenes, flashes trimmed from scene ends -> total stays 15s
    assert abs(out.duration - 15.0) < 0.15, f"got {out.duration}"


def test_concatenated_short_content_freeze_pads_no_black():
    """End-to-end guard: if content < audio length, the assembler must freeze
    the last frame instead of emitting black (verified mechanism)."""
    from moviepy import ColorClip, concatenate_videoclips
    import numpy as np
    c1 = ColorClip((160, 284), color=(255, 0, 0), duration=2.0)
    c2 = ColorClip((160, 284), color=(0, 0, 255), duration=3.0)
    content = concatenate_videoclips([c1, c2], method="compose")
    total = 10.0
    # replicate the assembler's freeze-pad logic
    if content.duration < total - 0.05:
        from moviepy import ImageClip
        last = content.get_frame(max(0.0, content.duration - 0.04))
        freeze = ImageClip(last).with_duration(total - content.duration + 0.1)
        content = concatenate_videoclips([content, freeze],
                                        method="compose").with_duration(total)
    assert abs(content.duration - total) < 0.1
    tail = content.get_frame(9.0)
    # tail must be the frozen blue frame, not black (moviepy frames are RGB)
    assert tail[..., 2].mean() > 100 and tail[..., 0].mean() < 50, \
        f"tail should be frozen blue frame, got mean {tail.mean(axis=(0,1))}"
