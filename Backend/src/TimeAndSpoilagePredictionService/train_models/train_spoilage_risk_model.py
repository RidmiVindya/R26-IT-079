"""Train RandomForestClassifier for spoilage-risk prediction.

Reads `datasets/spoilage_risk_dataset.xlsx` (sheet `Spoilage_Risk_Dataset`).

Dataset features:
    temperature_c, humidity_percent, elapsed_drying_time_hours,
    weight_loss_percentage, smell_sensor_output (categorical: Low/Medium/High)
Target:
    spoilage_risk (Low / Medium / High)

The categorical `smell_sensor_output` is label-encoded to a numeric
`smell_level_code` (Low=0, Medium=1, High=2). At inference time the API
converts its raw MQ-136 reading to the same Low/Medium/High bucket via
`app.utils.helper.classify_smell_level`, then encodes it the same way.

Run from the service root:
    python -m train_models.train_spoilage_risk_model
"""
from __future__ import annotations

import os
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "datasets" / "spoilage_risk_dataset.xlsx"
MODEL_OUT = ROOT / "app" / "ml_models" / "spoilage_risk_model.pkl"
SHEET_NAME = "Spoilage_Risk_Dataset"

# Shared with app/services/spoilage_risk_service.py — keep in sync.
SMELL_LEVEL_ENCODING = {"low": 0, "medium": 1, "high": 2}

FEATURES = [
    "temperature_c",
    "humidity_percent",
    "elapsed_drying_time_hours",
    "weight_loss_percentage",
    "smell_level_code",
]
TARGET = "spoilage_risk"


def _encode_smell(series: pd.Series) -> pd.Series:
    normalized = series.astype(str).str.strip().str.lower()
    unknown = sorted(set(normalized) - set(SMELL_LEVEL_ENCODING))
    if unknown:
        raise ValueError(f"Unknown smell_sensor_output values: {unknown}")
    return normalized.map(SMELL_LEVEL_ENCODING).astype(int)


def _load_dataset() -> pd.DataFrame:
    if not DATASET_PATH.exists():
        raise FileNotFoundError(
            f"Dataset not found at {DATASET_PATH}. "
            "Place the Excel file in datasets/ before running."
        )
    print(f"Loading dataset: {DATASET_PATH} (sheet: {SHEET_NAME})")
    df = pd.read_excel(DATASET_PATH, sheet_name=SHEET_NAME)
    df["smell_level_code"] = _encode_smell(df["smell_sensor_output"])
    return df


def main() -> None:
    df = _load_dataset()
    missing = [c for c in FEATURES + [TARGET] if c not in df.columns]
    if missing:
        raise ValueError(f"Dataset missing columns: {missing}")

    X = df[FEATURES].values
    y = df[TARGET].astype(str).str.strip().str.capitalize().values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=18,
        random_state=42,
        n_jobs=-1,
        class_weight="balanced",
    )
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    print("\nSpoilage-risk classifier:")
    print(classification_report(y_test, preds))

    os.makedirs(MODEL_OUT.parent, exist_ok=True)
    joblib.dump(model, MODEL_OUT)
    print(f"Saved model -> {MODEL_OUT}")


if __name__ == "__main__":
    main()
