import json
import time

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, top_k_accuracy_score

DATA_PATH = "/Users/boburburkhoniddinnov/Downloads/dataset.csv"
OUT_DIR = "/Users/boburburkhoniddinnov/MedPass/backend/ml"

df = pd.read_csv(DATA_PATH)
symptom_cols = [c for c in df.columns if c != "diseases"]
X = df[symptom_cols]
y = df["diseases"]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.15, random_state=42, stratify=None)

start = time.time()
clf = RandomForestClassifier(
    n_estimators=100, max_depth=30, min_samples_leaf=2, n_jobs=-1, random_state=42
)
clf.fit(X_train, y_train)
train_time = time.time() - start

joblib.dump(clf, f"{OUT_DIR}/symptom_model.joblib", compress=3)
with open(f"{OUT_DIR}/symptom_columns.json", "w") as f:
    json.dump(symptom_cols, f)

pred = clf.predict(X_test)
acc = accuracy_score(y_test, pred)
try:
    proba = clf.predict_proba(X_test)
    top3 = top_k_accuracy_score(y_test, proba, k=3, labels=clf.classes_)
except ValueError:
    top3 = None

print(f"train_time={train_time:.1f}s rows={len(df)} classes={y.nunique()}")
print(f"top1_accuracy={acc:.3f} top3_accuracy={top3}")
