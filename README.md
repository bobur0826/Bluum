# Pinit — Pin it and never worry

Ultra-affordable local BLE item tracker for Central Asia. This repo currently covers the
Week 1 MVP milestone: a hub that detects when tagged items are home or gone, and a backend
that logs that history.

## Layout

- `firmware/tag_simulator/` — ESP32 sketch that stands in for the real nRF52810 tag PCB. Flash
  onto any spare ESP32/ESP32-C3 board and carry it around; walking it out of BLE range *is*
  the "item left the house" test, no faking needed.
- `firmware/hub/` — ESP32-C3 sketch that scans for tag advertisements, decides present/absent
  per tag (RSSI threshold + hysteresis so it doesn't flap), and reports state changes to the
  backend over WiFi.
- `backend/` — Flask + SQLite API that stores tags and their presence event history. See
  [backend/README.md](backend/README.md) for the endpoint list.

Mobile app and the intelligence/pattern-analysis layer are Week 2+ per the MVP plan and aren't
built yet.

## Running the Week 1 demo end-to-end

You'll need two boards: one running `tag_simulator`, one running `hub`. A laptop runs the backend.

1. **Backend**
   ```bash
   cd backend
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   export PINIT_HUB_API_KEY="dev-secret-change-me"   # match this in config.h below
   python app.py
   ```
   Note your laptop's LAN IP (`ipconfig getifaddr en0` on macOS) — the hub needs it.

2. **Tag simulator** — open `firmware/tag_simulator/tag_simulator.ino` in Arduino IDE, install
   the `esp32` board package (Espressif Systems) if you haven't, set `TAG_ID` to something
   unique, and flash it to a spare ESP32 board. No WiFi needed — it just advertises over BLE.

3. **Hub** — in `firmware/hub/`, copy `config.h.example` to `config.h` and fill in your WiFi
   SSID/password, `BACKEND_BASE_URL` (`http://<laptop-LAN-IP>:5000`), and `HUB_API_KEY`
   (matching the backend's env var). Install the `ArduinoJson` library via Library Manager,
   then open `hub.ino` and flash it to the ESP32-C3.

4. **Register the tag** (optional — the hub auto-registers unknown tags, but naming it first
   is nicer):
   ```bash
   curl -X POST http://localhost:5000/api/tags \
     -H "Content-Type: application/json" \
     -d '{"tag_id": "1001", "name": "Keys", "item_type": "keychain"}'
   ```

5. **Watch it work** — with both boards powered and the tag simulator near the hub, poll:
   ```bash
   curl http://localhost:5000/api/tags
   ```
   `present` should flip to `true` within a couple of scan cycles. Walk the tag simulator out
   of range (or turn it off) — after ~30s of no sightings, `present` flips to `false` and the
   event lands in `/api/tags/1001/history`.

## Protocol notes

Tag → hub payload is BLE manufacturer-specific data, little-endian:
`[companyId:2][version:1][tagId:4][battery:1][flags:1]`. Company ID `0xFFFF` is the Bluetooth
SIG's reserved-for-testing value — get a real assigned company ID before any production run.
