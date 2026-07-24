import os

from flask import Flask, jsonify, request

from models import PresenceEvent, Tag, db

HUB_API_KEY = os.environ.get("PINIT_HUB_API_KEY", "dev-secret-change-me")


def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///pinit.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)

    with app.app_context():
        db.create_all()

    @app.get("/api/status")
    def status():
        return jsonify(status="ok")

    @app.post("/api/tags")
    def create_tag():
        data = request.get_json(force=True) or {}
        tag_id = data.get("tag_id")
        name = data.get("name")
        item_type = data.get("item_type", "keychain")

        if not tag_id or not name:
            return jsonify(error="tag_id and name are required"), 400
        if Tag.query.filter_by(tag_id=str(tag_id)).first():
            return jsonify(error="tag_id already registered"), 409

        tag = Tag(tag_id=str(tag_id), name=name, item_type=item_type)
        db.session.add(tag)
        db.session.commit()
        return jsonify(id=tag.id, tag_id=tag.tag_id, name=tag.name, item_type=tag.item_type), 201

    @app.get("/api/tags")
    def list_tags():
        result = []
        for tag in Tag.query.all():
            latest = (
                PresenceEvent.query.filter_by(tag_id=tag.tag_id)
                .order_by(PresenceEvent.timestamp.desc())
                .first()
            )
            result.append(
                {
                    "tag_id": tag.tag_id,
                    "name": tag.name,
                    "item_type": tag.item_type,
                    "present": latest.present if latest else None,
                    "last_seen": latest.timestamp.isoformat() if latest else None,
                    "last_rssi": latest.rssi if latest else None,
                    "battery_pct": latest.battery_pct if latest else None,
                }
            )
        return jsonify(result)

    @app.get("/api/tags/<tag_id>/history")
    def tag_history(tag_id):
        limit = request.args.get("limit", 200, type=int)
        events = (
            PresenceEvent.query.filter_by(tag_id=tag_id)
            .order_by(PresenceEvent.timestamp.desc())
            .limit(limit)
            .all()
        )
        return jsonify(
            [
                {
                    "present": e.present,
                    "rssi": e.rssi,
                    "battery_pct": e.battery_pct,
                    "timestamp": e.timestamp.isoformat(),
                }
                for e in events
            ]
        )

    @app.post("/api/events")
    def post_events():
        if request.headers.get("X-Pinit-Hub-Key") != HUB_API_KEY:
            return jsonify(error="unauthorized"), 401

        data = request.get_json(force=True) or {}
        events = data.get("events", [])
        if not isinstance(events, list) or not events:
            return jsonify(error="events must be a non-empty list"), 400

        created = 0
        for e in events:
            tag_id = e.get("tag_id")
            present = e.get("present")
            if tag_id is None or present is None:
                continue

            tag_id = str(tag_id)
            if not Tag.query.filter_by(tag_id=tag_id).first():
                # Auto-register unknown tags so the hub never blocks on manual setup.
                db.session.add(Tag(tag_id=tag_id, name=f"Unnamed tag {tag_id}"))

            db.session.add(
                PresenceEvent(
                    tag_id=tag_id,
                    present=bool(present),
                    rssi=e.get("rssi"),
                    battery_pct=e.get("battery_pct"),
                )
            )
            created += 1

        db.session.commit()
        return jsonify(created=created), 201

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
