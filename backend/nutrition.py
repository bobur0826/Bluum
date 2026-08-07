"""Food-photo calorie/macro estimation and daily-burn figures.

Both are currently SIMULATED - there's no real vision model or wearable
integration wired up yet. generate_food_estimate() and
generate_calories_burned() are the two functions to replace with real ones
later; everything here is deliberately just plausible placeholder data so
the feature is fully demoable today (per the product ask: "for now just
generate").
"""

import hashlib
import random
from datetime import date

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
