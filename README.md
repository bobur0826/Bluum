# MedPass — The Patient Intelligence Platform for Central Asia

A personal medical passport patients fill in once — every hospital visit after that is
auto-filled via QR scan, explained in plain language, and remembered. Phase 1 (MVP) and
Phase 2 (post-investment feature set) are both implemented.

## Run it

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY="your-key-here"      # needed for all AI features
export ESKIZ_EMAIL="your-eskiz-email"          # optional — needed for real SMS reminders
export ESKIZ_PASSWORD="your-eskiz-password"    # optional — without it, SMS calls just log and no-op
python app.py
```

Opens on `http://localhost:5001`. Without `ANTHROPIC_API_KEY`, AI-dependent forms show a clear
error instead of generating — nothing crashes, nothing is lost.

## Phase 1 — MVP

- `/patient/new` — one-time patient profile
- `/patients/<token>/qr` — QR code the patient shows at reception
- `/staff/login`, `/staff/register` — hospital staff accounts
- `/staff` → `/reception/<token>` — scan/enter a patient code, view auto-filled intake
- `/patients/<token>/summary/new` — doctor's consultation notes → AI plain-language summary
  (Uzbek + Russian), gated behind doctor approval before the patient can see it
- `/patients/<token>/history` — past approved appointment summaries

## Phase 2 — post-investment feature set

**Patient side:** test result upload + AI explanation with urgency flag (`/results`),
medication tracker with SMS reminders (`/medications`), discharge instructions as a daily
checklist (`/summary/<id>/discharge`), document storage (`/documents`), symptom checker
(`/symptom-checker`), appointment prep questions (`/appointments/prepare`), appointment booking
(`/appointments`), progressive profile completion (`/profile/next-question`). All reachable from
`/patients/<token>/dashboard`.

**Hospital side:** patient flow dashboard with check-ins/wait-time/bottlenecks
(`/hospital/dashboard`), appointment requests (`/hospital/appointments`), digital prescriptions
with automatic interaction checking (`/prescriptions/new`), doctor approval queue (built into the
summary flow), internal staff notes never shown to patients (`/notes`).

**AI layer:** medication interaction checker, test-result risk level (urgent/routine), and a
language register setting (`Patient.language_register`: "simple" vs "medical") that adjusts how
AI-generated text is phrased.

## Known limitations

- SMS delivery (`sms.py`) targets Eskiz.uz's commonly documented REST pattern — verify field
  names against your live Eskiz account before relying on it; without credentials it logs and
  no-ops rather than failing.
- File uploads are stored on local disk under `backend/uploads/`, not cloud storage.
- EN/UZ/RU nav pills are visual only — page chrome isn't actually translated, only AI-generated
  content is genuinely bilingual.
- No real camera-based QR scanning yet — `/staff` takes a manually entered/pasted code.
