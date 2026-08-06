# Bluum — The Patient Intelligence Platform for Central Asia

A personal medical passport patients fill in once — every hospital visit after that is
auto-filled via QR scan, explained in plain language by AI, and remembered. Phase 1 (MVP) and
Phase 2 (post-investment feature set) are both implemented.

- **Patients** never fill the same form twice, get their diagnosis explained in plain Uzbek or
  Russian, and can manage records, medications, and appointments from one place.
- **Hospitals** get instant check-in, AI-assisted documentation with a doctor-approval safety
  gate, automatic medication-interaction checks, and a live patient-flow dashboard.

This document covers setup for developers, and day-to-day usage for both patients and hospital
staff.

---

## 1. Developer setup

### Requirements

- Python 3.10+
- An OpenAI API key (for the AI layer — appointment summaries, symptom checker, etc.)
- Optionally, an Eskiz.uz account (for real SMS delivery — otherwise SMS calls safely no-op)

### Install and run

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in OPENAI_API_KEY (see below)
python app.py
```

Opens on `http://localhost:5001`. The SQLite database (`backend/instance/bluum.db`) and any
uploaded files (`backend/uploads/`) are created automatically on first run.

### Production deployment

`python app.py` is dev-only (Flask's built-in server). In production:

```bash
export FLASK_DEBUG=0
export SECRET_KEY=...        # required - see .env.example for how to generate one
export DATABASE_URL=postgresql://user:pass@host:5432/bluum
gunicorn -w 4 -b 0.0.0.0:5001 app:app
```

Put Nginx (or similar) in front with a real TLS certificate — Flask itself never terminates
HTTPS. `FLASK_DEBUG=0` also switches session cookies to HTTPS-only and refuses to start without
a real `SECRET_KEY`, so a misconfigured deployment fails loudly instead of running insecurely.

### Environment variables (`backend/.env`)

| Variable | Required | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | For AI features | Powers every AI call (summaries, symptom checker, prep questions, interaction checks, test-result explanations). Without it, those forms show a clear in-app error instead of generating — nothing crashes. |
| `ESKIZ_EMAIL` / `ESKIZ_PASSWORD` | No | Real SMS delivery for OTP codes, medication reminders, follow-up reminders, and summary-approval notifications. Without these, `sms.py` logs the message and returns `False` instead of sending — and OTP codes are shown directly on-screen so the login flow stays testable. |

`.env` is gitignored — never commit it. `.env.example` documents the shape for new
contributors.

### Project structure

```
Bluum/
├── README.md
└── backend/
    ├── app.py              # all Flask routes
    ├── models.py            # SQLAlchemy models (Patient, Staff, AppointmentSummary, ...)
    ├── ai_summary.py         # every OpenAI call + prompt template
    ├── auth.py               # Flask-Login setup for staff accounts
    ├── sms.py                # Eskiz.uz SMS client (no-ops without credentials)
    ├── uploads.py             # file upload helper
    ├── requirements.txt
    ├── .env.example
    ├── static/style.css
    └── templates/            # Jinja templates (Flask + server-rendered, no JS framework)
```

Patients authenticate via **SMS OTP** (phone number, no password) using Flask's built-in
`session`. Staff authenticate via **email + password** using Flask-Login. The two systems are
intentionally separate — see the comment in `inject_notifications()` in `app.py` for why (a
single browser can legitimately hold both a patient session and a staff login at once).

### Full route reference

**Public / home**
| Route | Purpose |
|---|---|
| `GET /` | Landing page |

**Patient auth (SMS OTP, no password)**
| Route | Purpose |
|---|---|
| `GET /patient/new` | Registration form (name, DOB, phone) |
| `POST /patients` | Creates the patient, sends OTP, redirects to verify |
| `GET/POST /patient/login` | Phone-number login, sends OTP |
| `GET /patient/verify` | Enter the 6-digit code |
| `POST /patient/verify` | Verifies the code, starts the session |
| `POST /patient/verify/resend` | Resends a fresh code |
| `GET /patient/logout` | Clears the patient session |

**Patient app** (all under `/patients/<token>/...`)
| Route | Purpose |
|---|---|
| `qr`, `qr.png` | QR code screen + the image itself (encodes the reception URL) |
| `dashboard` | Entry hub — links to records, visits, symptom checker, profile |
| `profile` | Full profile overview (all data in one place) |
| `profile/next-question` (GET/POST) | The progressive-profile Q&A flow |
| `records` | Hub: test results, documents, medications, prescriptions |
| `visits` | Hub: appointment history, booking, visit prep |
| `history` | Past **approved** appointment summaries |
| `summary/<id>` | One summary (plain-language diagnosis/meds/next steps, Uzbek+Russian) |
| `summary/<id>/discharge` | Same summary as a daily checklist |
| `results`, `results/upload` (GET/POST) | Test result list / upload → AI explanation + urgency flag |
| `results/<id>` | One test result's explanation |
| `medications` (GET/POST), `medications/<id>/delete` | Medication tracker (feeds SMS reminders) |
| `documents` (GET/POST), `documents/<id>/download` | Document storage |
| `symptom-checker` (GET/POST) | Describe symptoms → AI urgency + specialist routing |
| `appointments/prepare` (GET/POST) | AI-generated questions to ask your doctor |
| `appointments` (GET/POST) | Book an appointment by department/time |
| `prescriptions` | List of everything a doctor has prescribed |
| `notes` (GET/POST) | **Staff-only** — internal notes, never shown to the patient |

**Staff auth (email + password)**
| Route | Purpose |
|---|---|
| `GET/POST /staff/register` | Create a hospital account |
| `GET/POST /staff/login` | Log in |
| `GET /staff/logout` | Log out |

**Hospital / staff-only** (require login)
| Route | Purpose |
|---|---|
| `GET /staff` | Look up a patient by code |
| `POST /staff/lookup` | Logs a check-in, opens the patient |
| `GET /reception/<token>` | Auto-filled intake view for a checked-in patient |
| `GET /patients/<token>/summary/new`, `POST .../summary` | Doctor writes notes → AI generates a summary (status: `pending_review`) |
| `GET .../summary/<id>/review`, `POST .../approve` | Doctor reviews and approves before the patient can see it |
| `GET/POST /patients/<token>/prescriptions/new` | Write a prescription (auto-checked against allergies/current meds) |
| `GET /hospital/appointments`, `POST .../confirm` | Appointment request queue |
| `GET /hospital/dashboard` | Check-ins today, avg. wait time, bottlenecks |

---

## 2. Patient usage guide

### Creating your profile

1. Go to the home page → **I'm a patient** → fill in your **name, date of birth, and phone
   number**. No password.
2. You'll be sent a 6-digit code by SMS (or, if SMS isn't configured yet, it's shown directly
   on-screen so you can still test).
3. Enter the code → you're in, and taken straight to your **QR code**.

That's it for signup — everything else (allergies, conditions, medications, emergency contact,
blood type, etc.) is asked **one question at a time**, later, not all at once.

### Your QR code

- Screenshot it, or tap **Print my ID card** for a physical backup card — useful if you don't
  always have your phone handy at the hospital.
- Show it at reception (or have staff enter your code manually) — that's what auto-fills your
  paperwork.

### Logging back in later

Home page → **I'm a patient** → **Already registered? Log in** → enter your phone number → enter
the code they text you.

### Your dashboard

Four sections, reachable from the sidebar or the dashboard hub:

- **My records** — test results (upload one, get a plain-language explanation with an urgency
  flag), documents (prescriptions, referrals, insurance, lab results), your medication tracker,
  and everything a doctor has ever prescribed you.
- **Appointments** — your visit history, booking a new appointment by department, and "prepare
  for a visit" (describe why you're going, get AI-suggested questions to ask).
- **Ask Bluum** — describe symptoms, get an urgency level (routine / urgent / emergency) and
  which type of specialist to see. This is triage guidance, not a diagnosis.
- **Profile** — your full medical profile in one place. If you haven't finished answering the
  progressive questions yet, the next one is prompted right at the top.

### After a visit

Once a doctor writes up your visit and a staff member **approves** it, you'll get an SMS and a
notification (bell icon, top right) — open it to see your diagnosis explained simply, your
medications, what to do next, and when to come back. There's also a **daily checklist** view of
the same information if that's easier to follow.

### Language

Under **Profile**, you can choose whether AI explanations use **simple everyday language** or
keep **proper medical terminology** (with plain-language notes alongside it).

---

## 3. Hospital staff usage guide

### Getting an account

Home page → **Hospital staff** → **Create a hospital account** (name, hospital name, email,
password). Log in the same way afterward.

### Checking in a patient

**Look up patient** in the sidebar → scan or type in the patient's code → this logs the
check-in and opens their full profile (blood type, allergies, conditions, medications, emergency
contact — all auto-filled, nothing to type).

### Writing up a visit

From a patient's page: **Add appointment notes** → type up what happened in the consultation
(plain clinical shorthand is fine) → Bluum generates a plain-language explanation in Uzbek and
Russian automatically.

**This does not go to the patient yet.** You land on a **review** screen first — check it, then
**Approve & send to patient**. Only after approval can the patient see it (and only then does
their SMS/notification fire). If something's off, discard and rewrite the notes instead.

### Prescriptions

**Write prescription** on a patient's page → drug name, dosage, duration, instructions. Bluum
automatically cross-checks the new drug against the patient's known allergies and current
medications and flags a warning if there's a real conflict.

### Staff notes

**Staff notes (internal)** on a patient's page — for things you want on record for other staff,
that should never be shown to the patient (e.g. behavioral notes, billing flags).

### Dashboard and appointments

- **Dashboard** — check-ins today, how many patients have been seen, average wait time, and any
  detected bottlenecks (patients waiting over 45 minutes).
- **Appointments** — the queue of patient-requested appointments waiting to be confirmed.

---

## 4. Known limitations

- SMS delivery (`sms.py`) targets Eskiz.uz's commonly documented REST pattern — verify field
  names against your live Eskiz account before relying on it in production.
- File uploads are stored on local disk under `backend/uploads/`, not cloud storage.
- EN/UZ/RU nav pills are visual only — page chrome isn't actually translated; only AI-generated
  content (summaries, explanations) is genuinely bilingual.
- No real camera-based QR scanning yet — `/staff` takes a manually entered/pasted code.
- No password reset flow for staff accounts.
