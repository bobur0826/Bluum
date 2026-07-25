# MedPass — The Patient Intelligence Platform for Central Asia

A personal medical passport patients fill in once — every hospital visit after that is
auto-filled via QR scan. Week 1 MVP milestone: patient profile + QR check-in.

## Run it

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY="your-key-here"   # needed for the AI summary feature
python app.py
```

Opens on `http://localhost:5001`.

- `/` — patient fills their medical profile once, gets a QR code
- `/patients/<token>/qr` — the QR code screen (what the patient shows at reception)
- `/reception/<token>` — what reception sees after scanning (the auto-filled paperwork)
- `/patients/<token>/summary/new` — doctor enters consultation notes
- `/patients/<token>/summary/<id>` — the generated plain-language explanation (Uzbek + Russian toggle): what the diagnosis means, medications, next steps, when to return
- `/patients/<token>/history` — all past appointment summaries for a patient

Without `ANTHROPIC_API_KEY` set, the summary form still works but shows a clear error instead of
generating — doesn't crash, notes are preserved so nothing is lost.

## Next up

Hospital-side reception QR scanner UI (currently the reception view is reached by URL/manual
scan simulation, not a real camera scanner) — not started yet.
