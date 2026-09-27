"""Tests for the reference-clone engine (src/backend/reference_clone.py).

Builds synthetic videos with ffmpeg (the pipeline requires ffmpeg anyway)
and verifies: shot-boundary detection, camera-motion classification
(zoom-in / zoom-out / pan / static), palette extraction, and script
splitting. Skips gracefully when ffmpeg is unavailable.
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FFMPEG = shutil.which("ffmpeg")
NEED = "ffmpeg not available — skipping reference-clone tests"


def _run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def _make_fixtures(d):
    from PIL import Image, ImageDraw
    import random
    random.seed(7)
    still = os.path.join(d, "still.png")
    img = Image.new("RGB", (640, 560), (20, 20, 40))
    dr = ImageDraw.Draw(img)
    for _ in range(300):
        x, y = random.randint(0, 639), random.randint(0, 559)
        c = (random.randint(80, 255), random.randint(80, 255), random.randint(80, 255))
        dr.ellipse([x - 8, y - 8, x + 8, y + 8], fill=c)
    dr.rectangle([200, 200, 440, 360], outline=(255, 255, 255), width=6)
    img.save(still)

    zin = os.path.join(d, "zin.mp4")
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
          "-loop", "1", "-framerate", "30", "-i", still,
          "-vf", "zoompan=z='min(1+0.005*on,1.45)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=90:s=320x560:fps=30",
          "-t", "3", "-c:v", "libx264", zin])
    zout = os.path.join(d, "zout.mp4")
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
          "-loop", "1", "-framerate", "30", "-i", still,
          "-vf", "zoompan=z='max(1.45-0.005*on,1.0)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=90:s=320x560:fps=30",
          "-t", "3", "-c:v", "libx264", zout])
    pan = os.path.join(d, "pan.mp4")
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
          "-loop", "1", "-framerate", "30", "-i", still,
          "-vf", "crop=320:560:x='n*2':y=0,fps=30",
          "-t", "3", "-c:v", "libx264", pan])
    static = os.path.join(d, "static.mp4")
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
          "-framerate", "30", "-loop", "1", "-i", still,
          "-t", "2", "-pix_fmt", "yuv420p", static])
    cut = os.path.join(d, "cut.mp4")
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
          "-f", "lavfi", "-i", "color=c=red:s=320x560:d=3:r=30",
          "-f", "lavfi", "-i", "color=c=blue:s=320x560:d=3:r=30",
          "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0", cut])
    return {"zin": zin, "zout": zout, "pan": pan, "static": static, "cut": cut}


def main():
    if not FFMPEG:
        print(NEED)
        return 0
    from src.backend.reference_clone import (
        detect_shots, probe, estimate_motion, palette_and_mood,
        extract_keyframes, split_script_for_shots, MOTION_TO_PROMPT,
    )
    d = tempfile.mkdtemp(prefix="refclone_test_")
    try:
        v = _make_fixtures(d)

        # 1. motion classification
        for key, want in [("zin", "zoom-in"), ("zout", "zoom-out"),
                          ("pan", "pan-right"), ("static", "static")]:
            dur, _, _, _ = probe(v[key])
            got = estimate_motion(v[key], (0, dur))
            assert got == want, f"{key}: want {want}, got {got}"
            print(f"  motion {key} -> {got}: OK")

        # 2. cut detection
        dur, _, _, _ = probe(v["cut"])
        shots = detect_shots(v["cut"], dur)
        assert len(shots) == 2, f"expected 2 shots, got {shots}"
        assert abs(shots[0][1] - 3.0) < 0.3, f"cut not at ~3s: {shots}"
        for s in shots:
            assert estimate_motion(v["cut"], s) == "static", s
        print(f"  cut detection {shots}: OK")

        # 3. palette differs per shot
        kfs = extract_keyframes(v["cut"], shots, os.path.join(d, "kf"))
        h1, _, _ = palette_and_mood(kfs[0])
        h2, _, _ = palette_and_mood(kfs[1])
        assert h1 and h2 and h1 != h2, (h1, h2)
        print(f"  palettes {h1} vs {h2}: OK")

        # 4. script splitting
        parts = split_script_for_shots("One. Two. Three. Four. Five. Six.",
                                       [(0, 1), (1, 4), (4, 6)])
        assert len(parts) == 3 and all(parts), parts
        print(f"  script split: OK")

        # 5. motion prompt map complete
        for m in ["static", "zoom-in", "zoom-out", "pan-left", "pan-right",
                  "pan-up", "pan-down", "dolly-in", "dolly-out"]:
            assert m in MOTION_TO_PROMPT, m
        print("  motion->prompt map: OK")
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("ALL REFERENCE-CLONE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
