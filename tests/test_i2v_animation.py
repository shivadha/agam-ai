"""Tests for 2026-09-27 img-to-video animation fixes (user report:
"image to video was not animated").

Root causes found by loop-testing:
1. The ComfyUI SVD branch produced a 1.0s clip (14 frames @ 14fps) no
   matter the requested duration — the "only 2 second video" complaint.
   Now: 25 frames for SVD-XT / 14 for base SVD, played at the conditioning
   fps (7) -> 3.6s / 2.0s of genuine AI motion.
2. The assembler's short-clip tail was a plain slow zoom (~32% over ~8s),
   which reads as a still image on a phone. Now: a rich animated tail
   (2.5D parallax, drifting particles, light sweep, grain) rendered from
   the clip's last frame — in-memory, no temp files.
"""
import os
import sys

import pytest

REPO = "/home/hatch/workspace/projects/agam-ai"
sys.path.insert(0, REPO)
os.chdir(REPO)

from src.backend import video_assembler as va
from src.backend import video_gen_ai as vg


def test_svd_frame_plan_xt():
    frames, fps = vg._svd_frame_plan("svd_xt_1_1.safetensors")
    assert frames == 25
    assert fps == 7


def test_svd_frame_plan_base():
    frames, fps = vg._svd_frame_plan("svd.safetensors")
    assert frames == 14
    assert fps == 7


def test_svd_workflow_uses_planned_frames_and_fps():
    import inspect
    src = inspect.getsource(vg._generate_comfyui_wan)
    assert "_svd_frame_plan(svd_model)" in src
    # SaveAnimatedWEBP must play at the conditioning fps, not a hardcoded 14
    assert '"fps": float(svd_fps)' in src
    assert '"fps": 14.0' not in src
    # webp->mp4 conversion must keep the same fps (was hardcoded 14 -> 1s clip)
    assert "frames, fps=7, codec" in src


def test_prepare_video_shot_accepts_motion_prompt():
    import inspect
    sig = inspect.signature(va.prepare_video_shot)
    assert "motion_prompt" in sig.parameters


def _natural_test_image(path, w=320, h=568):
    """Synthetic but natural-ish image: sky gradient + sun + dark ground."""
    import numpy as np
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (w, h))
    dr = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        dr.line([(0, y), (w, y)],
                fill=(int(20 + 60 * t), int(30 + 40 * t), int(60 + 80 * (1 - t))))
    dr.ellipse([w // 2 - 40, h // 3 - 40, w // 2 + 40, h // 3 + 40],
               fill=(255, 200, 120))
    dr.rectangle([0, int(h * 0.72), w, h], fill=(25, 20, 30))
    img.save(path)
    return str(path)


def _short_ai_clip(path, img_path, frames=14, fps=7):
    """Simulate a ComfyUI SVD webp->mp4 result: a few seconds of motion."""
    import numpy as np
    from PIL import Image
    import imageio.v2 as imageio
    base = np.asarray(Image.open(img_path).convert("RGB").resize((256, 454)))
    out = []
    for i in range(frames):
        f = base.copy()
        yy = 120 + i * 8
        f[yy:yy + 40, 90:170] = [235, 120, 40]
        out.append(f)
    imageio.mimsave(str(path), out, fps=fps, codec="libx264")
    return str(path)


def test_tail_is_animated_not_a_still(tmp_path):
    """A 2s AI clip stretched to 9s must stay visibly animated in the tail."""
    import numpy as np
    img = _natural_test_image(tmp_path / "scene.jpg")
    clip_p = _short_ai_clip(tmp_path / "ai.mp4", img)
    shot = va.prepare_video_shot(clip_p, 9.0, 320, 568, fallback_image=None,
                                 motion_prompt="desert dust drifting, slow push-in")
    assert abs(shot.duration - 9.0) < 0.15, f"got {shot.duration}"

    def motion(t1, t2):
        a = shot.get_frame(t1).astype(float)
        b = shot.get_frame(t2).astype(float)
        return float(np.mean(np.abs(a - b)))

    # tail region (after the 2s AI head): must be clearly animated at every point
    for t1, t2 in [(2.5, 3.5), (4.5, 5.5), (6.5, 7.5), (7.8, 8.8)]:
        m = motion(t1, t2)
        assert m > 1.5, f"tail looks frozen at {t1}-{t2}s (motion={m:.2f})"
    # no black frames anywhere
    for t in [0.5, 3.0, 6.0, 8.8]:
        assert float(shot.get_frame(t).mean()) > 5, f"black frame at {t}s"


def test_tail_differs_from_plain_zoom(tmp_path):
    """The animated tail must move MORE than the old plain-zoom tail did.

    Guards against regressing to a subtle drift that reads as a still image:
    with zoom-only motion the 1s-apart frame diff on this image stays low.
    """
    import numpy as np
    img = _natural_test_image(tmp_path / "scene.jpg")
    clip_p = _short_ai_clip(tmp_path / "ai.mp4", img)
    shot = va.prepare_video_shot(clip_p, 9.0, 320, 568, fallback_image=None,
                                 motion_prompt="fire embers rising")

    def motion(t1, t2):
        a = shot.get_frame(t1).astype(float)
        b = shot.get_frame(t2).astype(float)
        return float(np.mean(np.abs(a - b)))

    # rich tail: parallax + particles + sweep + grain over 1s gaps
    m1 = motion(3.0, 4.0)
    m2 = motion(5.0, 6.0)
    assert m1 > 2.0 and m2 > 2.0, f"tail too subtle: {m1:.2f}, {m2:.2f}"
