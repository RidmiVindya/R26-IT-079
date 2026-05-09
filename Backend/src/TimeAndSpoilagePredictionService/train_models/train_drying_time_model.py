"""Train the drying-time RandomForestRegressor.

Reads `datasets/drying_time_dataset.xlsx` if present. If not, generates a
synthetic dataset (since IoT hardware data is not yet available) so the
training pipeline can still produce a usable .pkl for the API.

Run from the service root:
    python -m train_models.train_drying_time_model
"""
from __future__ import annotations

import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "datasets" / "drying_time_dataset.xlsx"
MODEL_OUT = ROOT / "app" / "ml_models" / "drying_time_model.pkl"

FISH_TYPE_ENCODING = {
    "sardine": 0, "anchovy": 1, "mackerel": 2, "tuna": 3,
    "herring": 4, "salmon": 5, "cod": 6, "tilapia": 7,
}

FEATURES = [
    "fish_type_code",
    "initial_weight_kg",
    "current_weight_kg",
    "temperature_c",
    "humidity_percent",
    "elapsed_drying_time_hours",
    "weight_loss_rate",
]
TARGET = "remaining_drying_time_hours"


def _generate_synthetic(n: int = 4000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    fish_codes = rng.integers(0, len(FISH_TYPE_ENCODING), size=n)
    initial = rng.uniform(2.0, 50.0, size=n)
    weight_loss_pct = rng.uniform(0.0, 65.0, size=n)
    current = initial * (1 - weight_loss_pct / 100.0)
    temp = rng.uniform(20.0, 55.0, size=n)
    humidity = rng.uniform(20.0, 95.0, size=n)
    elapsed = rng.uniform(0.5, 48.0, size=n)
    rate = (initial - current) / np.maximum(elapsed, 0.1)

    target_weight = initial * (1 - 65.0 / 100.0)
    remaining_mass = np.maximum(0.0, current - target_weight)
    humidity_factor = 1.0 + np.maximum(0.0, (humidity - 50.0) / 100.0)
    temp_factor = 1.0 - np.clip((temp - 35.0) / 100.0, -0.4, 0.4)
    adjusted_rate = np.maximum(rate / (humidity_factor * temp_factor), 0.02)
    remaining_hours = remaining_mass / adjusted_rate
    noise = rng.normal(0, 0.8, size=n)
    remaining_hours = np.clip(remaining_hours + noise, 0.0, 240.0)

    return pd.DataFrame(
        {
            "fish_type_code": fish_codes,
            "initial_weight_kg": initial,
            "current_weight_kg": current,
            "temperature_c": temp,
            "humidity_percent": humidity,
            "elapsed_drying_time_hours": elapsed,
            "weight_loss_rate": rate,
            TARGET: remaining_hours,
        }
    )


def _load_dataset() -> pd.DataFrame:
    if DATASET_PATH.exists():
        print(f"Loading dataset from {DATASET_PATH}")
        df = pd.read_excel(DATASET_PATH)
        if "fish_type" in df.columns and "fish_type_code" not in df.columns:
            df["fish_type_code"] = df["fish_type"].str.lower().map(FISH_TYPE_ENCODING).fillna(0).astype(int)
        return df
    print(f"Dataset not found at {DATASET_PATH}; generating synthetic data.")
    return _generate_synthetic()


def main() -> None:
    df = _load_dataset()
    missing = [c for c in FEATURES + [TARGET] if c not in df.columns]
    if missing:
        raise ValueError(f"Dataset missing columns: {missing}")

    X = df[FEATURES].values
    y = df[TARGET].values

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    model = RandomForestRegressor(n_estimators=200, max_depth=20, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    mae = mean_absolute_error(y_test, preds)
    r2 = r2_score(y_test, preds)
    print(f"Drying-time model: MAE={mae:.3f}, R2={r2:.3f}")

    os.makedirs(MODEL_OUT.parent, exist_ok=True)
    joblib.dump(model, MODEL_OUT)
    print(f"Saved model -> {MODEL_OUT}")


if __name__ == "__main__":
    main()
