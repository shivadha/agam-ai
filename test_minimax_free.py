"""Tests for the MiniMax H3 free routes (no network; all external calls mocked)."""
import inspect
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

# ── 1. hailuo provider registered ──────────────────────────────────────
from src.agent.providers.registry import get_provider, known_providers
from src.agent.providers import hailuo as hailuo_mod

assert "hailuo_web" in known_providers(), known_providers()
p = get_provider("hailuo_web")
assert p.id == "hailuo_web"
assert "video" in p.kinds
assert p.login_url == "https://hailuoai.video/"
names = [s["name"] for s in hailuo_mod.VIDEO_STRATEGIES]
assert len(names) == 4 and len(set(names)) == 4, names
assert all(callable(s["run"]) and s["desc"] for s in hailuo_mod.VIDEO_STRATEGIES)
# every selector bucket is non-empty
assert all(hailuo_mod.SELECTORS.values())
print("1. hailuo provider registry: OK")

# ── 2. strategy rotation never repeats ─────────────────────────────────
from src.agent.providers.base import StrategyRotator

sf = os.path.join(tempfile.mkdtemp(), "s.json")
r = StrategyRotator("hailuo_web", hailuo_mod.VIDEO_STRATEGIES, state_file=sf)
a = r.pick()["name"]
b = r.pick()["name"]
assert a != b, "rotator must not repeat the previous strategy"
print("2. strategy rotation: OK")

# ── 3. space endpoint discovery (fake client) ───────────────────────────
from src.backend import minimax_space


class FakeClient:
    def get_api_info(self):
        return {"named_endpoints": {
            "/generate": {
                "parameters": [
                    {"parameter_name": "prompt", "type": "string",
                     "python_type": {"type": "str"}},
                    {"parameter_name": "input_image", "type": "image",
                     "python_type": {"type": "filepath"}},
                    {"parameter_name": "upsample_prompt", "type": "boolean",
                     "python_type": {"type": "bool"}},
                ],
                "returns": [{"type": "video", "python_type": {"type": "filepath"}}],
            },
            "/other": {
                "parameters": [{"parameter_name": "x", "type": "string",
                                "python_type": {"type": "str"}}],
                "returns": [{"type": "string", "python_type": {"type": "str"}}],
            },
        }}


ep = minimax_space._find_video_endpoint(FakeClient())
assert ep == "/generate", ep
kw = minimax_space._build_kwargs(FakeClient(), "/generate", "a cat", "/tmp/img.png")
assert kw["prompt"] == "a cat", kw
assert kw["input_image"] == "/tmp/img.png", kw
assert kw["upsample_prompt"] is True, kw
print("3. space endpoint discovery: OK")

# ── 4. result extraction variants ──────────────────────────────────────
d = tempfile.mkdtemp()
vf = os.path.join(d, "v.mp4")
with open(vf, "wb") as f:
    f.write(b"x" * 2000)
assert minimax_space._extract_video_path(vf) == vf
assert minimax_space._extract_video_path([{"path": vf}]) == vf
assert minimax_space._extract_video_path({"url": "https://x/y.mp4"}) == "https://x/y.mp4"
assert minimax_space._extract_video_path("nope") is None
print("4. result extraction: OK")

# ── 5. missing gradio_client -> helpful error ──────────────────────────
sys.modules["gradio_client"] = None  # force ImportError on 'from ... import'
try:
    minimax_space.generate_minimax_h3_space(None, "p", os.path.join(d, "o.mp4"))
    raise AssertionError("should have raised")
except RuntimeError as e:
    assert "gradio_client" in str(e) and "pip install" in str(e), e
finally:
    del sys.modules["gradio_client"]
print("5. missing-dep error: OK")

# ── 6. video_gen_ai queue: minimax_space is keyless ────────────────────
import src.backend.video_gen_ai as vga

src_txt = inspect.getsource(vga.generate_video_from_image)
backups = src_txt.split("backups =")[1].split("]")[0]
assert '"minimax_space"' in backups, "minimax_space must be in the backup queue"
lines = src_txt.splitlines()
keyless_idx = next(i for i, l in enumerate(lines) if 'p == "minimax_space"' in l)
keycheck_idx = next(i for i, l in enumerate(lines) if "if not p_key:" in l)
assert keyless_idx < keycheck_idx, "minimax_space must be tried WITHOUT an API key"
assert '"space" in prov_lower' in src_txt, "explicit space request must route keyless"
print("6. video queue wiring: OK")

# ── 7. ledger seeds hailuo_web ─────────────────────────────────────────
import inspect as _inspect
import src.backend.free_providers as fp

seed_src = _inspect.getsource(fp.seed_builtin_providers)
assert '"hailuo_web"' in seed_src, "seed must include hailuo_web"
assert 'kinds=["video"]' in seed_src
print("7. ledger seed: OK")

print("ALL MINIMAX-FREE TESTS PASSED")
