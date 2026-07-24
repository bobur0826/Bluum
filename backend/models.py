from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Tag(db.Model):
    __tablename__ = "tags"

    id = db.Column(db.Integer, primary_key=True)
    tag_id = db.Column(db.String(32), unique=True, nullable=False)
    name = db.Column(db.String(64), nullable=False)
    item_type = db.Column(db.String(32), nullable=False, default="keychain")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class PresenceEvent(db.Model):
    __tablename__ = "presence_events"

    id = db.Column(db.Integer, primary_key=True)
    tag_id = db.Column(db.String(32), db.ForeignKey("tags.tag_id"), nullable=False, index=True)
    present = db.Column(db.Boolean, nullable=False)
    rssi = db.Column(db.Integer, nullable=True)
    battery_pct = db.Column(db.Integer, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
