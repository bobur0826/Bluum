"""Food-photo calorie/macro estimation and daily-burn figures.

analyze_food_photo() does a real GPT-4o vision call on the actual photo.
generate_food_estimate() is the fallback used only when that's unavailable
(no API key, request failure, unparseable response) or when there's no
photo at all - it's a deterministic placeholder, not a guess at real
content, which is why it landed on "Beef burger with fries" for a yogurt
photo before this. generate_calories_burned() is still fully simulated -
there's no wearable/sensor integration to pull a real burn figure from.
"""

import base64
import hashlib
import json
import os
import random
from datetime import date

from openai import OpenAI

MODEL = "gpt-4o"

VISION_PROMPT = """You are estimating nutrition facts from a photo of a meal for a health app. \
Look at the food in this image and estimate its nutritional content.

Respond with ONLY valid JSON, no markdown fences, in exactly this shape:
{"description": "short name of the dish, 2-5 words", "calories": <int>, "protein_g": <int>, \
"fat_g": <int>, "carbs_g": <int>}

If the image does not show food at all, still respond in the same JSON shape, using your best \
guess of what's shown as the description and 0 for all the numeric fields."""


def analyze_food_photo(image_bytes: bytes) -> dict | None:
    """Returns a real {description, calories, protein_g, fat_g, carbs_g}
    estimate from GPT-4o's vision, or None if that's not possible right now
    (missing API key, request failure, bad response) - callers should fall
    back to generate_food_estimate() in that case rather than fail the log."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        b64 = base64.b64encode(image_bytes).decode()
        response = OpenAI(api_key=api_key).chat.completions.create(
            model=MODEL,
            max_tokens=300,
            response_format={"type": "json_object"},
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }],
        )
        data = json.loads(response.choices[0].message.content.strip())
        return {
            "description": str(data["description"])[:160],
            "calories": max(0, int(data["calories"])),
            "protein_g": max(0, int(data["protein_g"])),
            "fat_g": max(0, int(data["fat_g"])),
            "carbs_g": max(0, int(data["carbs_g"])),
        }
    except Exception:
        # Network hiccup, bad JSON, missing key in the response, whatever -
        # this feature degrading to the simulated fallback beats a 500.
        return None

# (description, calories, protein_g, fat_g, carbs_g) - a believable spread
# of everyday meals, not meant to be exhaustive.
MEAL_PRESETS = [
    ("Chicken & rice bowl", 520, 38, 12, 58),
    ("Grilled salmon with vegetables", 480, 34, 22, 18),
    ("Beef plov", 650, 28, 24, 78),
    ("Pasta with tomato sauce", 560, 18, 14, 88),
    ("Greek yogurt with granola", 320, 16, 9, 42),
    ("Omelette with vegetables", 380, 24, 26, 8),
    ("Lentil soup with bread", 410, 20, 10, 62),
    ("Grilled chicken salad", 390, 36, 16, 20),
    ("Beef burger with fries", 780, 32, 38, 72),
    ("Fruit smoothie bowl", 340, 10, 6, 64),
]


def generate_food_estimate(seed_text: str) -> dict:
    """Returns a plausible {description, calories, protein_g, fat_g, carbs_g}
    for a food photo. Deterministic per `seed_text` (the stored photo
    filename) so re-viewing the same entry never changes its numbers, while
    different photos land on different presets."""
    digest = hashlib.sha256(seed_text.encode()).hexdigest()
    rng = random.Random(int(digest, 16))
    name, cal, protein, fat, carbs = rng.choice(MEAL_PRESETS)

    def jitter(value, pct):
        return max(0, round(value * rng.uniform(1 - pct, 1 + pct)))

    return {
        "description": name,
        "calories": jitter(cal, 0.12),
        "protein_g": jitter(protein, 0.15),
        "fat_g": jitter(fat, 0.15),
        "carbs_g": jitter(carbs, 0.15),
    }


def generate_calories_burned(patient_token: str, for_date: date) -> int:
    """A plausible daily calories-burned figure - simulated, no wearable/
    sensor data behind it yet. Deterministic per patient+day so it stays
    stable across page reloads instead of flickering."""
    digest = hashlib.sha256(f"{patient_token}:{for_date.isoformat()}".encode()).hexdigest()
    rng = random.Random(int(digest, 16))
    return rng.randint(1850, 2450)
