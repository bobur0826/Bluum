# MedPass — The Patient Intelligence Platform for Central Asia

A personal medical passport patients fill in once — every hospital visit after that is
auto-filled via QR scan. Week 1 MVP milestone: patient profile + QR check-in.

## Run it

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Opens on `http://localhost:5001`.

- `/` — patient fills their medical profile once, gets a QR code
- `/patients/<token>/qr` — the QR code screen (what the patient shows at reception)
- `/reception/<token>` — what reception sees after scanning (the auto-filled paperwork)

## Next up

AI appointment summary (GPT-4, plain-language Uzbek) is the next MVP milestone — not started yet.
