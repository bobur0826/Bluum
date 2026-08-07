"""Generates a shareable streak-card PNG (Instagram/Telegram-Story ready).

Uses the bundled Inter variable font (static/fonts/Inter.ttf, OFL-licensed,
see static/fonts/OFL.txt) instead of Pillow's built-in font: Pillow's default
has zero Cyrillic coverage, so any Uzbek/Russian habit name rendered as
broken tofu boxes before this. Inter covers Latin + Cyrillic cleanly and
ships as a single variable-weight file, so no per-weight files to bundle.
"""

import io
import math
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

CARD_SIZE = (1080, 1080)

BG_TOP = (7, 32, 19)          # deep green-black
BG_BOTTOM = (3, 8, 5)         # near black
WHITE = (255, 255, 255)
MUTED = (176, 214, 194)       # pale green-white, secondary text - stays on-brand
# rather than a neutral gray.

FLAME_TOP = (255, 214, 92)    # warm yellow
FLAME_MID = (255, 140, 40)    # orange
FLAME_BOTTOM = (224, 62, 26)  # red-orange

FONT_PATH = os.path.join(os.path.dirname(__file__), "static", "fonts", "Inter.ttf")


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


def _flame_mask(size):
    """A single stylized flame silhouette (tip up), as a soft-edged mask.

    Built from many points sampled along a piecewise-linear width profile
    (narrow tip -> widest near the base -> rounded bottom) with a slight
    left-right wobble for a natural flicker, then blurred to round off the
    straight segments into a smooth curve rather than a faceted gem."""
    w, h = size

    # (t, half-width) keyframes from tip (t=0) to base (t=1).
    keyframes = [
        (0.00, 0.00), (0.12, 0.09), (0.24, 0.15), (0.32, 0.12),
        (0.48, 0.20), (0.66, 0.34), (0.85, 0.31), (1.00, 0.17),
    ]

    def half_width(t):
        for (t0, r0), (t1, r1) in zip(keyframes, keyframes[1:]):
            if t0 <= t <= t1:
                frac = (t - t0) / (t1 - t0) if t1 > t0 else 0
                return r0 + (r1 - r0) * frac
        return keyframes[-1][1]

    n = 64
    left, right = [], []
    for i in range(n + 1):
        t = i / n
        radius = half_width(t)
        wobble = 0.025 * (t ** 0.5) * math.sin(t * math.pi * 1.6)
        cx = 0.5 + wobble
        left.append((cx - radius, t))
        right.append((cx + radius, t))
    points = left + right[::-1]

    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).polygon([(x * w, y * h) for x, y in points], fill=255)
    return mask.filter(ImageFilter.GaussianBlur(max(w, h) * 0.014))


def _flame_image(size):
    """Returns an RGBA flame icon: warm gradient fill plus a soft glow halo
    behind it, the same "glowing streak flame" look used across every
    reference (Snapchat, Duolingo-style streak cards, etc.)."""
    w, h = size
    fill = _vertical_gradient(size, FLAME_TOP, FLAME_BOTTOM)
    flame = Image.new("RGBA", size, (0, 0, 0, 0))
    flame.paste(fill, (0, 0), _flame_mask(size))

    glow_size = (int(w * 1.9), int(h * 1.9))
    glow_mask = _flame_mask(size).resize(glow_size).filter(ImageFilter.GaussianBlur(w * 0.07))
    glow_fill = Image.new("RGB", glow_size, FLAME_MID)
    glow = Image.new("RGBA", glow_size, (0, 0, 0, 0))
    glow.paste(glow_fill, (0, 0), glow_mask)

    canvas = Image.new("RGBA", glow_size, (0, 0, 0, 0))
    canvas.alpha_composite(glow)
    offset = ((glow_size[0] - w) // 2, (glow_size[1] - h) // 2)
    canvas.alpha_composite(flame, offset)
    return canvas


def generate_streak_card(title, streak, subtitle=""):
    """Returns a BytesIO PNG: dark gradient background, glowing flame icon,
    big streak number, habit title, subtitle, and Bluum branding - sized for
    Instagram/Telegram Stories."""
    img = _vertical_gradient(CARD_SIZE, BG_TOP, BG_BOTTOM).convert("RGBA")
    draw = ImageDraw.Draw(img)

    _centered_text(draw, 76, "B L U U M", _font(32, "SemiBold"), MUTED)

    flame = _flame_image((190, 190))
    flame_top = 160
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
