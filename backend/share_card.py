"""Generates a shareable streak-card PNG (Instagram/Telegram-Story ready).

Uses the bundled Inter variable font (static/fonts/Inter.ttf, OFL-licensed,
see static/fonts/OFL.txt) instead of Pillow's built-in font: Pillow's default
has zero Cyrillic coverage, so any Uzbek/Russian habit name rendered as
broken tofu boxes before this. Inter covers Latin + Cyrillic cleanly and
ships as a single variable-weight file, so no per-weight files to bundle.
"""

import io
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

CARD_SIZE = (1080, 1080)

BG_TOP = (7, 32, 19)          # deep green-black
BG_BOTTOM = (3, 8, 5)         # near black
WHITE = (255, 255, 255)
MUTED = (176, 214, 194)       # pale green-white, secondary text - stays on-brand
# rather than a neutral gray.

FLAME_GLOW = (255, 150, 50)   # warm orange, used only for the blurred halo

FONT_PATH = os.path.join(os.path.dirname(__file__), "static", "fonts", "Inter.ttf")
FLAME_PATH = os.path.join(os.path.dirname(__file__), "static", "img", "fire.png")


def _font(size, weight="Regular"):
    f = ImageFont.truetype(FONT_PATH, size)
    f.set_variation_by_name(weight)
    return f


def _vertical_gradient(size, top, bottom):
    w, h = size
    grad = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        px = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        grad.putpixel((0, y), px)
    return grad.resize(size)


def _centered_text(draw, y, text, font, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    draw.text(((CARD_SIZE[0] - w) / 2, y), text, font=font, fill=fill)


def _radial_glow(diameter, color, exponent=2.2):
    """A soft circular light glow: bright warm center fading smoothly to
    fully transparent at the edge - a real radial falloff, not a blur of
    the icon's own (irregular) silhouette, which is what made earlier
    attempts come out as a blobby, edge-clipped mess."""
    yy, xx = np.mgrid[0:diameter, 0:diameter]
    center = diameter / 2
    dist = np.sqrt((xx - center) ** 2 + (yy - center) ** 2) / center
    alpha = (np.clip(1 - dist, 0, 1) ** exponent * 255).astype(np.uint8)
    glow = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    glow.paste(Image.new("RGB", (diameter, diameter), color), (0, 0), Image.fromarray(alpha, mode="L"))
    return glow


def _flame_image(icon_size, glow_diameter):
    """Returns an RGBA image, always exactly `glow_diameter` square: the
    fire.png icon (background already keyed out) centered over a soft
    radial glow. Callers lay out around the fixed glow_diameter, not the
    icon's own pixel size, so this can't throw off spacing unpredictably."""
    flame = Image.open(FLAME_PATH).convert("RGBA")
    flame.thumbnail(icon_size, Image.LANCZOS)

    canvas = _radial_glow(glow_diameter, FLAME_GLOW)
    offset = ((glow_diameter - flame.width) // 2, (glow_diameter - flame.height) // 2)
    canvas.alpha_composite(flame, offset)
    return canvas


def generate_streak_card(title, streak, subtitle=""):
    """Returns a BytesIO PNG: dark gradient background, glowing flame icon,
    big streak number, habit title, subtitle, and Bluum branding - sized for
    Instagram/Telegram Stories."""
    img = _vertical_gradient(CARD_SIZE, BG_TOP, BG_BOTTOM).convert("RGBA")
    draw = ImageDraw.Draw(img)

    _centered_text(draw, 76, "B L U U M", _font(32, "SemiBold"), MUTED)

    flame = _flame_image((190, 190), 320)
    flame_top = 150
    img.alpha_composite(flame, ((CARD_SIZE[0] - flame.width) // 2, flame_top))

    number_y = flame_top + flame.height + 35
    _centered_text(draw, number_y, str(streak), _font(200, "ExtraBold"), WHITE)
    _centered_text(draw, number_y + 215, "DAY STREAK", _font(34, "SemiBold"), MUTED)

    _centered_text(draw, number_y + 300, title, _font(52, "SemiBold"), WHITE)
    if subtitle:
        _centered_text(draw, number_y + 366, subtitle, _font(30, "Medium"), MUTED)

    _centered_text(draw, 1000, "bluum.app", _font(26, "Medium"), MUTED)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf
