"""
AGAM — One master render -> every platform format.

export_all() takes the finished master video and produces:
  - wide     : 16:9 as-is, re-encoded (h264 yuv420p + aac) for compatibility
  - vertical : center-crop to 9:16, 1080x1920 (Shorts / Reels / TikTok)
  - square   : center-crop to 1:1, 1080x1080 (feed posts)

All outputs: libx264 preset fast, crf 20, yuv420p, aac 160k, +faststart —
the same encode conventions as the rest of the pipeline. ffmpeg is resolved
like dubbing.py (imageio-ffmpeg first, PATH fallback). Only stdlib otherwise.
"""

import os
import subprocess

from .dubbing import _ffmpeg_exe


def _run_ffmpeg(cmd, timeout=900):
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr[-800:]}")
    return proc


def _encode(input_path, out_path, vf=None):
    """Re-encode with the pipeline-standard settings; optional video filter."""
    cmd = [_ffmpeg_exe(), "-y", "-i", input_path]
    if vf:
        cmd += ["-vf", vf]
    cmd += [
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart",
        out_path,
    ]
    _run_ffmpeg(cmd)
    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError(f"ffmpeg produced no output: {out_path}")
    return out_path


def export_all(master_path, out_dir):
    """Export wide / vertical / square versions of the master.

    Returns {'wide': path, 'vertical': path, 'square': path}.
    Raises FileNotFoundError when the master is missing, RuntimeError when
    ffmpeg fails (fail loudly — a half-exported set is worse than none).
    """
    if not master_path or not os.path.exists(master_path):
        raise FileNotFoundError(f"Master video not found: {master_path}")
    os.makedirs(out_dir, exist_ok=True)

    base = os.path.splitext(os.path.basename(master_path))[0]
    wide = os.path.join(out_dir, f"{base}_wide_16x9.mp4")
    vertical = os.path.join(out_dir, f"{base}_vertical_9x16.mp4")
    square = os.path.join(out_dir, f"{base}_square_1x1.mp4")

    print(f"[repurpose] Exporting platform formats from {master_path} ...")
    _encode(master_path, wide)                                        # 16:9 as-is
    print(f"[repurpose] wide     -> {wide}")
    _encode(master_path, vertical, "crop=ih*9/16:ih,scale=1080:1920")  # 9:16
    print(f"[repurpose] vertical -> {vertical}")
    _encode(master_path, square, "crop=ih:ih,scale=1080:1080")         # 1:1
    print(f"[repurpose] square   -> {square}")

    return {"wide": wide, "vertical": vertical, "square": square}
