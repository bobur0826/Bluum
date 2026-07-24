# Pinit Backend

Flask + SQLite service that logs tag presence/absence events reported by the hub.

## Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Runs on `http://0.0.0.0:5000`. SQLite file `instance/pinit.db` is created automatically on first run (Flask-SQLAlchemy puts relative sqlite paths under the instance folder).

Set a real shared secret before pointing a hub at this (matches `HUB_API_KEY` in `firmware/hub/config.h`):

```bash
export PINIT_HUB_API_KEY="something-long-and-random"
```

## API

- `GET /api/status` — health check
- `POST /api/tags` — register a tag: `{"tag_id": "1001", "name": "Keys", "item_type": "keychain"}`
- `GET /api/tags` — list tags with their latest known presence/rssi/battery
- `GET /api/tags/<tag_id>/history?limit=200` — recent presence events for one tag
- `POST /api/events` — hub-only, requires header `X-Pinit-Hub-Key: <HUB_API_KEY>`. Body: `{"events": [{"tag_id": "1001", "present": true, "rssi": -60, "battery_pct": 90}, ...]}`. Unknown `tag_id`s are auto-registered as "Unnamed tag <id>" so the hub never blocks on manual setup.
