"""
AGAM — Background music: 100% free, local-first.

Two sources:
  1. Local library — drop MP3/WAV/OGG/M4A files into assets/music/.
     list_tracks() enumerates them with durations (ffprobe).
  2. Pixabay Music API (free key) — search + download royalty-free tracks
     into the library. The key is read from the same store /api/keys uses
     (PIXABAY_API_KEY in os.environ or BASE_DIR/.env).

     NOTE: Pixabay officially documents only its image/video endpoints; the
     /api/music/ endpoint is community-known and unofficial, so it may
     change or fail — failures raise RuntimeError with the reason instead
     of failing silently. Also note some Pixabay tracks carry Content-ID
     fingerprints: check the track page before using a bed in monetized
     uploads.

Mixing:
  fit_music()  — loops a track to cover target_sec, fades out the last 2s.
  duck_under() — sidechain-ducks the music bed under the voiceover and
                 mixes to ONE track (voice full + ducked bed).
"""

import os
import re
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB_DIR = os.path.join(BASE_DIR, "assets", "music")
os.makedirs(LIB_DIR, exist_ok=True)

AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac")

PIXABAY_MUSIC_URL = "https://pixabay.com/api/music/"


def _ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _read_api_key(env_name):
    """Same key store /api/keys uses: os.environ first, then BASE_DIR/.env."""
    val = (os.environ.get(env_name) or "").strip()
    if val:
        return val
    env_path = os.path.join(BASE_DIR, ".env")
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(env_name + "="):
                    v = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if v:
                        return v
    except Exception:
        pass
    return ""


def _probe_duration(path):
    """Audio duration in seconds via ffprobe, falling back to ffmpeg -i parse."""
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=20,
        )
        if proc.returncode == 0:
            return round(float(proc.stdout.strip()), 1)
    except Exception:
        pass
    try:
        proc = subprocess.run(
            [_ffmpeg_exe(), "-i", path],
            capture_output=True, text=True, timeout=20,
        )
        m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", proc.stderr or "")
        if m:
            h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
            return round(h * 3600 + mi * 60 + s, 1)
    except Exception:
        pass
    return None


def list_tracks():
    """List local library tracks: [{name, path, duration_sec}]."""
    tracks = []
    try:
        files = sorted(os.listdir(LIB_DIR))
    except Exception:
        files = []
    for fname in files:
        if not fname.lower().endswith(AUDIO_EXTS):
            continue
        path = os.path.join(LIB_DIR, fname)
        tracks.append({
            "name": os.path.splitext(fname)[0].replace("_", " ").replace("-", " "),
            "path": path,
            "duration_sec": _probe_duration(path),
        })
    return tracks


def pixabay_search(query, per_page=5):
    """Search Pixabay Music. Returns [{id, title, duration_sec, audio_url}].

    Raises RuntimeError if no PIXABAY_API_KEY is set or the endpoint fails.
    """
    import requests

    key = _read_api_key("PIXABAY_API_KEY")
    if not key:
        raise RuntimeError(
            "Add a free Pixabay API key first (pixabay.com/api → PIXABAY_API_KEY "
            "in the Keys panel), then search again."
        )
    try:
        r = requests.get(
            PIXABAY_MUSIC_URL,
            params={"key": key, "q": query or "", "per_page": max(1, min(20, per_page))},
            timeout=25,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        raise RuntimeError(f"Pixabay music search failed ({e}). The /api/music/ endpoint is unofficial and may be unavailable.")

    hits = data.get("hits") if isinstance(data, dict) else None
    if not hits:
        raise RuntimeError("Pixabay returned no music hits for that query (or an unexpected response shape).")

    results = []
    for h in hits:
        # Defensive: the undocumented endpoint's field names vary.
        audio_url = (
            h.get("audio") or h.get("previewURL") or h.get("preview_url")
            or h.get("downloadURL") or h.get("download_url") or h.get("mp3")
        )
        if not audio_url:
            continue
        results.append({
            "id": h.get("id"),
            "title": h.get("title") or h.get("name") or h.get("tags") or "Untitled",
            "duration_sec": h.get("duration"),
            "audio_url": audio_url,
        })
    if not results:
        raise RuntimeError("Pixabay returned hits but no playable audio URLs (unexpected response shape).")
    return results


def pixabay_download(audio_url, dest_name):
    """Download a Pixabay track into assets/music/. Returns the local path."""
    import requests

    if not audio_url:
        raise RuntimeError("No audio_url provided.")
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", dest_name or "track.mp3")
    if not safe.lower().endswith(AUDIO_EXTS):
        safe += ".mp3"
    dest = os.path.join(LIB_DIR, safe)
    try:
        r = requests.get(audio_url, stream=True, timeout=120)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
    except Exception as e:
        try:
            if os.path.exists(dest):
                os.remove(dest)
        except Exception:
            pass
        raise RuntimeError(f"Pixabay download failed: {e}")
    print(f"[music] Downloaded -> {dest}")
    return dest


def fit_music(track_path, target_sec, out_path):
    """Loop a track to cover target_sec, fade out the last 2s. Returns out_path."""
    if not track_path or not os.path.exists(track_path):
        raise RuntimeError(f"Music track not found: {track_path}")
    target_sec = max(1.0, float(target_sec))
    fade_start = max(0.0, target_sec - 2.0)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    cmd = [
        _ffmpeg_exe(), "-y",
        "-stream_loop", "-1", "-i", track_path,
        "-t", f"{target_sec:.2f}",
        "-af", f"afade=t=in:st=0:d=0.5,afade=t=out:st={fade_start:.2f}:d=2",
        "-c:a", "aac", "-b:a", "160k",
        out_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError(f"fit_music failed: {(proc.stderr or '')[-400:]}")
    print(f"[music] Fitted {target_sec:.0f}s bed -> {out_path}")
    return out_path


def duck_under(music_path, voice_path, out_path, music_db=-20):
    """Duck the music bed under the voiceover, mix to ONE track.

    voice stays full volume; music sits at music_db and dips further
    whenever the voice is active (sidechain compression).
    Returns out_path.
    """
    for p, label in ((music_path, "music"), (voice_path, "voice")):
        if not p or not os.path.exists(p):
            raise RuntimeError(f"Duck: {label} audio not found: {p}")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    filt = (
        f"[1:a]volume={music_db}dB[m];"
        "[m][0:a]sidechaincompress=threshold=0.02:ratio=8:attack=200:release=800[mduck];"
        "[0:a][mduck]amix=inputs=2:duration=first:dropout_transition=0[aout]"
    )
    cmd = [
        _ffmpeg_exe(), "-y",
        "-i", voice_path,
        "-stream_loop", "-1", "-i", music_path,
        "-filter_complex", filt,
        "-map", "[aout]",
        "-c:a", "aac", "-b:a", "160k",
        out_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError(f"duck_under failed: {(proc.stderr or '')[-400:]}")
    print(f"[music] Ducked mix -> {out_path}")
    return out_path
