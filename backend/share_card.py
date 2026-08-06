"""Generates a shareable streak-card PNG (Instagram/Telegram-Story ready).

Uses Pillow's built-in scalable font so this works on any server without
bundling font files or depending on OS-specific font paths.
"""

import io

from PIL import Image, ImageDraw, ImageFont

CARD_SIZE = (1080, 1080)
BG_TOP = (22, 163, 74)      # flat brand green
BG_BOTTOM = (5, 90, 45)     # deep green
WHITE = (255, 255, 255)
FADED = (255, 255, 255, 180)


def _font(size):
    return ImageFont.load_default(size=size)


def _vertical_gradient(size, top, bottom):
    w, h = size
    base = Image.new("RGB", size, top)
    grad = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        px = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        grad.putpixel((0, y), px)
    grad = grad.resize(size)
    return Image.blend(base, grad, 1.0)


def _centered_text(draw, y, text, font, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    draw.text(((CARD_SIZE[0] - w) / 2, y), text, font=font, fill=fill)


def generate_streak_card(title, streak, subtitle=""):
    """Returns a BytesIO PNG: gradient background, big streak number, title,
    subtitle, and Bluum branding — sized for Instagram/Telegram Stories."""
    img = _vertical_gradient(CARD_SIZE, BG_TOP, BG_BOTTOM).convert("RGB")
    draw = ImageDraw.Draw(img)

    _centered_text(draw, 170, "BLUUM", _font(42), FADED[:3])

    streak_text = str(streak)
    _centered_text(draw, 370, streak_text, _font(220), WHITE)
    _centered_text(draw, 610, "DAY STREAK", _font(40), FADED[:3])

    _centered_text(draw, 760, title, _font(56), WHITE)
    if subtitle:
        _centered_text(draw, 840, subtitle, _font(34), FADED[:3])

    _centered_text(draw, 990, "bluum.app", _font(28), FADED[:3])

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
