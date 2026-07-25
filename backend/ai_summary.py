import json
import os

import anthropic

MODEL = "claude-sonnet-5"

PROMPT_TEMPLATE = """You are helping a patient in Uzbekistan understand what happened in their \
doctor's appointment. Given the doctor's raw consultation notes and the patient's known medical \
background, write a plain-language explanation a non-medical person can understand.

Doctor's notes:
{notes}

Patient's known allergies: {allergies}
Patient's current medications: {current_medications}
Patient's chronic conditions: {chronic_conditions}

Respond with ONLY valid JSON, no markdown fences, in exactly this shape:
{{
  "uz": {{"diagnosis": "...", "medications": "...", "next_steps": "...", "follow_up": "..."}},
  "ru": {{"diagnosis": "...", "medications": "...", "next_steps": "...", "follow_up": "..."}}
}}

Rules for every field:
- "diagnosis": what the diagnosis means, in simple everyday words, 2-3 sentences.
- "medications": what to take and when, plain instructions. If the notes mention a medication \
that conflicts with the patient's known allergies, say so clearly as a warning.
- "next_steps": what the patient should actually do at home, 1-3 short sentences.
- "follow_up": when to come back or call the hospital, one sentence.
- "uz" must be written in Uzbek, "ru" must be written in Russian. No English in either.
- No clinical jargon. Warm, clear, short sentences."""


class SummaryGenerationError(Exception):
    pass


def generate_summary(notes: str, allergies: str, current_medications: str, chronic_conditions: str) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SummaryGenerationError("ANTHROPIC_API_KEY is not set")

    client = anthropic.Anthropic(api_key=api_key)
    prompt = PROMPT_TEMPLATE.format(
        notes=notes,
        allergies=allergies or "None reported",
        current_medications=current_medications or "None reported",
        chronic_conditions=chronic_conditions or "None reported",
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        data = json.loads(raw)
        return {
            "diagnosis_uz": data["uz"]["diagnosis"],
            "medications_uz": data["uz"]["medications"],
            "next_steps_uz": data["uz"]["next_steps"],
            "follow_up_uz": data["uz"]["follow_up"],
            "diagnosis_ru": data["ru"]["diagnosis"],
            "medications_ru": data["ru"]["medications"],
            "next_steps_ru": data["ru"]["next_steps"],
            "follow_up_ru": data["ru"]["follow_up"],
        }
    except (json.JSONDecodeError, KeyError) as e:
        raise SummaryGenerationError(f"Could not parse AI response: {e}")
