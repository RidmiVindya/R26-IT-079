"""Train the spoilage-risk RandomForestClassifier.

Reads `datasets/spoilage_risk_dataset.xlsx` if present, else generates a
synthetic labelled dataset.

Run from the service root:
    python -m train_models.train_spoilage_risk_model
"""
from __future__ import annotations

import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "datasets" / "spoilage_risk_dataset.xlsx"
MODEL_OUT = ROOT / "app" / "ml_models" / "spoilage_risk_model.pkl"

FEATURES = [
    "temperature_c",
    "humidity_percent",
    "elapsed_drying_time_hours",
    "weight_loss_percentage",
    "mq136_value",
]
TARGET = "spoilage_risk"


def _label_from_rules(temp, humidity, elapsed, wlp, mq):
    score = 0
    # Smell score
    if mq > 600:
        score += 3
    elif mq > 300:
        score += 1
    # Humidity
    if humidity >= 80:
        score += 2
    elif humidity >= 65:
        score += 1
    # Temperature extremes
    if temp >= 45:
        score += 2
    elif temp <= 20:
        score += 1
    # Slow drying
    if elapsed >= 36 and wlp < 30:
        score += 2

    if score >= 4:
        return "High"
    if score >= 2:
        return "Medium"
    return "Low"


def _generate_synthetic(n: int = 5000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    temp = rng.uniform(15.0, 55.0, size=n)
    humidity = rng.uniform(20.0, 95.0, size=n)
    elapsed = rng.uniform(0.5, 60.0, size=n)
    wlp = rng.uniform(0.0, 70.0, size=n)
    mq = rng.uniform(0.0, 1000.0, size=n)

    labels = [_label_from_rules(t, h, e, w, m) for t, h, e, w, m in zip(temp, humidity, elapsed, wlp, mq)]

    return pd.DataFrame(
        {
            "temperature_c": temp,
            "humidity_percent": humidity,
            "elapsed_drying_time_hours": elapsed,
            "weight_loss_percentage": wlp,
            "mq136_value": mq,
            TARGET: labels,
        }
    )


def _load_dataset() -> pd.DataFrame:
    if DATASET_PATH.exists():
        print(f"Loading dataset from {DATASET_PATH}")
        return pd.read_excel(DATASET_PATH)
    print(f"Dataset not found at {DATASET_PATH}; generating synthetic data.")
    return _generate_synthetic()


def main() -> None:
    df = _load_dataset()
    missing = [c for c in FEATURES + [TARGET] if c not in df.columns]
    if missing:
        raise ValueError(f"Dataset missing columns: {missing}")

    X = df[FEATURES].values
    y = df[TARGET].astype(str).values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    model = RandomForestClassifier(
        n_estimators=200, max_depth=18, random_state=42, n_jobs=-1, class_weight="balanced"
    )
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    print("Spoilage-risk classifier:")
    print(classification_report(y_test, preds))

    os.makedirs(MODEL_OUT.parent, exist_ok=True)
    joblib.dump(model, MODEL_OUT)
    print(f"Saved model -> {MODEL_OUT}")


if __name__ == "__main__":
    main()
