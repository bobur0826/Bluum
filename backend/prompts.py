import json
import os

from openai import OpenAI

MODEL = "gpt-4o"

REGISTER_INSTRUCTIONS = {
    "simple": "Use everyday words a non-medical person understands. No clinical jargon.",
    "medical": "Keep proper medical/clinical terminology intact (e.g. drug names, diagnosis names) "
    "but still explain what each term means in a following clause.",
}


class SummaryGenerationError(Exception):
    pass


def _client():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SummaryGenerationError("OPENAI_API_KEY is not set")
    return OpenAI(api_key=api_key)


def _call(prompt: str, max_tokens: int = 1024) -> dict:
    try:
        response = _client().chat.completions.create(
            model=MODEL,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        raise SummaryGenerationError(f"OpenAI request failed: {e}")

    raw = response.choices[0].message.content.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise SummaryGenerationError(f"Could not parse AI response: {e}")


SUMMARY_PROMPT = """You are helping a patient in Uzbekistan understand what happened in their \
doctor's appointment. Given the doctor's raw consultation notes and the patient's known medical \
background, write a plain-language explanation.

Doctor's notes:
{notes}

Patient's known allergies: {allergies}
Patient's current medications: {current_medications}
Patient's chronic conditions: {chronic_conditions}

Language register: {register_instruction}

Respond with ONLY valid JSON, no markdown fences, in exactly this shape:
{{
  "uz": {{"diagnosis": "...", "medications": "...", "next_steps": "...", "follow_up": "...", "daily_steps": ["...", "..."]}},
  "ru": {{"diagnosis": "...", "medications": "...", "next_steps": "...", "follow_up": "...", "daily_steps": ["...", "..."]}}
}}

Rules for every field:
- "diagnosis": what the diagnosis means, 2-3 sentences.
- "medications": what to take and when. If the notes mention a medication that conflicts with the \
patient's known allergies, say so clearly as a warning.
- "next_steps": what the patient should actually do at home, 1-3 short sentences.
- "follow_up": when to come back or call the hospital, one sentence.
- "daily_steps": the same guidance as next_steps + medications, broken into a short checklist of \
3-6 individual daily actions (e.g. "Take amoxicillin at 8am and 8pm", "Rest, avoid heavy exercise").
- "uz" must be written in Uzbek, "ru" must be written in Russian. No English in either.
- Warm, clear, short sentences."""


def generate_summary(
    notes: str,
    allergies: str,
    current_medications: str,
    chronic_conditions: str,
    language_register: str = "simple",
) -> dict:
    prompt = SUMMARY_PROMPT.format(
        notes=notes,
        allergies=allergies or "None reported",
        current_medications=current_medications or "None reported",
        chronic_conditions=chronic_conditions or "None reported",
        register_instruction=REGISTER_INSTRUCTIONS.get(language_register, REGISTER_INSTRUCTIONS["simple"]),
    )
    data = _call(prompt)
    try:
        out = {}
        for lang in ("uz", "ru"):
            out[f"diagnosis_{lang}"] = data[lang]["diagnosis"]
            out[f"medications_{lang}"] = data[lang]["medications"]
            out[f"next_steps_{lang}"] = data[lang]["next_steps"]
            out[f"follow_up_{lang}"] = data[lang]["follow_up"]
            out[f"daily_steps_{lang}"] = json.dumps(data[lang]["daily_steps"], ensure_ascii=False)
        return out
    except KeyError as e:
        raise SummaryGenerationError(f"Missing field in AI response: {e}")


TEST_RESULT_PROMPT = """A patient in Uzbekistan uploaded a lab/test result. Here is a description \
or transcription of the result:

{result_text}

Patient's known chronic conditions: {chronic_conditions}

Respond with ONLY valid JSON, no markdown fences:
{{
  "risk_level": "urgent" or "routine",
  "uz": "plain-language explanation of what this result means, 2-4 sentences, in Uzbek",
  "ru": "the same explanation in Russian"
}}

"urgent" means the patient should contact the hospital soon / seek care within a day or two.
"routine" means it can wait for a normal follow-up. No clinical jargon in the explanations."""


def generate_test_result_explanation(result_text: str, chronic_conditions: str) -> dict:
    prompt = TEST_RESULT_PROMPT.format(
        result_text=result_text, chronic_conditions=chronic_conditions or "None reported"
    )
    data = _call(prompt)
    try:
        return {
            "risk_level": data["risk_level"],
            "explanation_uz": data["uz"],
            "explanation_ru": data["ru"],
        }
    except KeyError as e:
        raise SummaryGenerationError(f"Missing field in AI response: {e}")


CHAT_PROMPT = """You are Bluum, a friendly, knowledgeable medical assistant chatting with a patient \
in Uzbekistan. Talk naturally, like a real conversation - not a rigid form.

Full patient context - weigh ALL of this in every reply, even when not directly asked about it:
- Allergies: {allergies}
- Chronic conditions: {chronic_conditions}
- Current medications: {current_medications}
- Active prescriptions: {prescriptions}
- Habits they are actively quitting or building right now: {habits}
- Last night's sleep: {last_sleep}
- Today so far: {today_activity}
- Recent test results on file: {recent_results}

Conversation so far:
{history}

Patient's new message: "{message}"

Reply helpfully and personally, ALWAYS factoring in the context above when it's relevant - e.g. if \
they are actively quitting alcohol, never casually recommend or normalize a bar/drinking venue even if \
they only mention it in passing; if they slept badly or have eaten few calories today, factor that into \
energy/activity advice; if a habit, prescription, or condition changes what's safe to suggest, say so \
directly. If they're just asking a general question (lifestyle, sports, nutrition, a follow-up, etc.) - \
answer it directly and conversationally, no diagnosis format needed. Only set is_symptom_report to true \
if they are actually describing new or worsening symptoms that warrant medical triage.

Respond with ONLY valid JSON, no markdown fences:
{{
  "is_symptom_report": true or false,
  "urgency": "emergency" or "urgent" or "routine" or null (null unless is_symptom_report is true),
  "specialist": "type of doctor to see, in English, or null" (null unless is_symptom_report is true),
  "en": "your reply, in English, 1-4 sentences",
  "uz": "the same reply, in Uzbek",
  "ru": "the same reply, in Russian"
}}

"emergency" = go to the ER now. "urgent" = see a doctor within 1-2 days. "routine" = book a normal \
appointment. This is guidance, not a diagnosis - never definitively diagnose."""


def generate_chat_reply(message: str, history: list, context: dict) -> dict:
    history_text = "\n".join(f"{h['role']}: {h['text']}" for h in history[-8:]) or "(none yet)"
    prompt = CHAT_PROMPT.format(
        message=message,
        history=history_text,
        allergies=context.get("allergies") or "None reported",
        chronic_conditions=context.get("chronic_conditions") or "None reported",
        current_medications=context.get("current_medications") or "None reported",
        prescriptions=context.get("prescriptions") or "None on file",
        habits=context.get("habits") or "None being tracked",
        last_sleep=context.get("last_sleep") or "Not logged",
        today_activity=context.get("today_activity") or "Nothing logged yet today",
        recent_results=context.get("recent_results") or "None on file",
    )
    data = _call(prompt)
    try:
        return {
            "is_symptom_report": bool(data.get("is_symptom_report")),
            "urgency": data.get("urgency"),
            "specialist": data.get("specialist"),
            "explanation_uz": data["uz"],
            "explanation_ru": data["ru"],
            "explanation_en": data.get("en", data["uz"]),
        }
    except KeyError as e:
        raise SummaryGenerationError(f"Missing field in AI response: {e}")


PREP_QUESTIONS_PROMPT = """A patient in Uzbekistan has an upcoming appointment. Reason for visit:

{reason}

Patient's known chronic conditions: {chronic_conditions}
Patient's current medications: {current_medications}

Respond with ONLY valid JSON, no markdown fences:
{{
  "uz": ["question 1", "question 2", "question 3"],
  "ru": ["question 1", "question 2", "question 3"]
}}

Generate 3-5 specific questions this patient should ask their doctor during this visit, based on \
their reason for visiting and their medical background. Written in Uzbek and Russian respectively."""


def generate_prep_questions(reason: str, chronic_conditions: str, current_medications: str) -> dict:
    prompt = PREP_QUESTIONS_PROMPT.format(
        reason=reason,
        chronic_conditions=chronic_conditions or "None reported",
        current_medications=current_medications or "None reported",
    )
    data = _call(prompt)
    try:
        return {
            "questions_uz": json.dumps(data["uz"], ensure_ascii=False),
            "questions_ru": json.dumps(data["ru"], ensure_ascii=False),
        }
    except KeyError as e:
        raise SummaryGenerationError(f"Missing field in AI response: {e}")


INTERACTION_PROMPT = """A doctor in Uzbekistan is about to prescribe a new medication to a patient.

New medication: {new_drug} {new_dosage}
Patient's current medications: {current_medications}
Patient's known allergies: {allergies}

Respond with ONLY valid JSON, no markdown fences:
{{
  "has_warning": true or false,
  "warning": "explanation of the dangerous interaction or allergy conflict, in plain English, or empty string if none"
}}

Only set has_warning true for a genuine, clinically real interaction or allergy conflict - do not \
invent risks that don't exist."""


def check_medication_interactions(new_drug: str, new_dosage: str, current_medications: str, allergies: str) -> dict:
    prompt = INTERACTION_PROMPT.format(
        new_drug=new_drug,
        new_dosage=new_dosage or "",
        current_medications=current_medications or "None reported",
        allergies=allergies or "None reported",
    )
    data = _call(prompt, max_tokens=512)
    try:
        return {"has_warning": bool(data["has_warning"]), "warning": data["warning"]}
    except KeyError as e:
        raise SummaryGenerationError(f"Missing field in AI response: {e}")
