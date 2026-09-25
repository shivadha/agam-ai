"""
AGAM — AI thumbnail generator.

YouTube CTR lives or dies on the thumbnail. This module builds a 1280x720
thumbnail from either an existing scene image or a freshly generated one,
then overlays a bold, high-contrast title treatment with PIL.

Styles:
  - "Bold Viral"  — yellow Impact-style uppercase text, heavy stroke (default)
  - "Dark Moody"  — white text on darkened cinematic frame
  - "Minimal"     — clean white text, subtle gradient

All local, zero cost (PIL is already a dependency).
"""

import os
import textwrap

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "output")

THUMB_W, THUMB_H = 1280, 720


def _find_bold_font(size):
    """Resolve a bold TTF across Windows / Linux; fall back to PIL default."""
    from PIL import ImageFont
    candidates = [
        "C:/Windows/Fonts/impact.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _shorten_title(title, max_words=7):
    words = (title or "").strip().split()
    if len(words) > max_words:
        words = words[:max_words]
    text = " ".join(words).upper()
    # Strip trailing punctuation that looks weak in thumbnails
    return text.rstrip(".,!?;:")


def _cover_resize(img, w, h):
    """Resize + center-crop to exactly fill (w, h)."""
    iw, ih = img.size
    scale = max(w / iw, h / ih)
    img = img.resize((int(iw * scale) + 1, int(ih * scale) + 1))
    left = (img.size[0] - w) // 2
    top = (img.size[1] - h) // 2
    return img.crop((left, top, left + w, top + h))


def generate_thumbnail(title, hook="", scene_images=None, style="Bold Viral",
                        custom_text="", output_filename="thumbnail.png",
                        base_image_model=None):
    """Build a 1280x720 YouTube thumbnail. Returns the saved path.

    base_image_model: when no scene image exists, which engine paints the
    background art. Pass "free-web" / "free-web:<provider_id>" to use the
    invisible background agent (ChatGPT Go / Gemini web, $0).
    """
    from PIL import Image, ImageDraw, ImageFont

    text = _shorten_title(custom_text or hook or title)
    if not text:
        text = "WATCH THIS"

    # ── 1. Base image: reuse a scene frame, else generate one ──
    base = None
    for p in (scene_images or []):
        if p and os.path.exists(p):
            base = p
            break

    if base:
        print(f"[thumbnail] Using scene image as base: {os.path.basename(base)}")
        img = Image.open(base).convert("RGB")
    else:
        print("[thumbnail] No scene image — generating dedicated thumbnail art...")
        try:
            prompt = (
                f"Cinematic YouTube thumbnail background for '{title}'. "
                "Dramatic, ultra-detailed, high contrast, vibrant colors, "
                "rule-of-thirds composition with clear negative space on the left "
                "for text, 16:9, no text, no watermark"
            )
            gen_path = os.path.join(OUTPUT_DIR, "_thumb_base.png")
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            if base_image_model and str(base_image_model).lower().startswith("free-web"):
                from .free_agent_client import generate_image_file
                prefer = (str(base_image_model).split(":", 1)[1].strip()
                          if ":" in str(base_image_model) else None)
                print(f"[thumbnail] base art via free-web agent (prefer={prefer or 'auto'})")
                got = generate_image_file(prompt, provider_id=prefer)
                img = Image.open(got).convert("RGB")
            else:
                from .image_gen import _generate_image_once
                got = _generate_image_once(prompt, gen_path, width=1280, height=720,
                                           model_name="Pollinations FLUX", seed=7)
                img = Image.open(got or gen_path).convert("RGB")
        except Exception as e:
            print(f"[thumbnail] Generation failed ({e}) — using gradient fallback.")
            from PIL import Image as _I
            img = _I.new("RGB", (THUMB_W, THUMB_H), (12, 14, 24))

    img = _cover_resize(img, THUMB_W, THUMB_H)

    # ── 2. Style treatment ──
    draw = ImageDraw.Draw(img, "RGBA")
    style_key = (style or "Bold Viral").lower()

    if "moody" in style_key:
        # Darken everything for white-text contrast
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 110))
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img, "RGBA")
        text_color, stroke_w, grad_alpha = (255, 255, 255), 6, 160
    elif "minimal" in style_key:
        text_color, stroke_w, grad_alpha = (255, 255, 255), 4, 120
    else:  # Bold Viral
        text_color, stroke_w, grad_alpha = (255, 230, 0), 7, 170

    # Bottom gradient for text legibility
    grad_h = 380
    for y in range(grad_h):
        alpha = int(grad_alpha * (y / grad_h) ** 1.4)
        draw.rectangle([0, THUMB_H - grad_h + y, THUMB_W, THUMB_H - grad_h + y + 1],
                       fill=(0, 0, 0, alpha))

    # ── 3. Title text, auto-sized to fit ──
    font_size = 120
    font = _find_bold_font(font_size)
    # Wrap to ~14 chars/line at large sizes
    lines = textwrap.wrap(text, width=14)[:3]
    while font_size > 48:
        font = _find_bold_font(font_size)
        widths = [draw.textlength(l, font=font) for l in lines]
        if max(widths or [0]) <= THUMB_W - 120:
            break
        font_size -= 8

    line_h = int(font_size * 1.12)
    total_h = line_h * len(lines)
    y = THUMB_H - total_h - 70
    for line in lines:
        lw = draw.textlength(line, font=font)
        x = (THUMB_W - lw) / 2
        draw.text((x, y), line, font=font, fill=text_color,
                  stroke_width=stroke_w, stroke_fill=(0, 0, 0))
        y += line_h

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, output_filename)
    img.save(out_path, "PNG")
    print(f"[thumbnail] Saved -> {out_path}")
    return out_path
