import json
import os

import joblib

_DIR = os.path.join(os.path.dirname(__file__), "ml")
_model = None
_columns = None


def _load():
    global _model, _columns
    if _model is None:
        _model = joblib.load(os.path.join(_DIR, "symptom_model.joblib"))
        with open(os.path.join(_DIR, "symptom_columns.json")) as f:
            _columns = json.load(f)
    return _model, _columns


def predict_diseases(free_text: str, top_n: int = 3):
    """Match free-text symptoms against the known vocabulary, run the trained
    classifier, return the top_n most likely diseases with probability."""
    model, columns = _load()
    text = free_text.lower()
    vector = [1 if symptom in text else 0 for symptom in columns]

    if sum(vector) == 0:
        return []

    proba = model.predict_proba([vector])[0]
    ranked = sorted(zip(model.classes_, proba), key=lambda x: x[1], reverse=True)[:top_n]
    return [{"disease": d, "confidence": round(p, 2)} for d, p in ranked if p > 0]
