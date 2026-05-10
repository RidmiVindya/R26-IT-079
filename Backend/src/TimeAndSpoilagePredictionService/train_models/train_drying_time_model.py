"""Train RandomForestRegressor models for fish-drying time prediction.

Reads `datasets/drying_time__dataset.xlsx` with two sheets:
    - Initial_Time_Prediction  → predicts total drying time before drying starts
    - Dynamic_Time_Prediction  → predicts remaining drying time during drying

Trains and saves two separate models:
    - app/ml_models/initial_drying_time_model.pkl
    - app/ml_models/drying_time_model.pkl   (used by the API)

Run from the service root:
    python -m train_models.train_drying_time_model
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "datasets" / "drying_time__dataset.xlsx"
INITIAL_MODEL_OUT = ROOT / "app" / "ml_models" / "initial_drying_time_model.pkl"
DYNAMIC_MODEL_OUT = ROOT / "app" / "ml_models" / "drying_time_model.pkl"

INITIAL_SHEET = "Initial_Time_Prediction"
DYNAMIC_SHEET = "Dynamic_Time_Prediction"

# Fish-type encoding shared with the API. Keep in sync with
# app/services/drying_time_service.py and app/config.ALLOWED_FISH_TYPES.
FISH_TYPE_ENCODING = {
    # Generic English names (kept for backward compatibility)
    "sardine": 0, "anchovy": 1, "mackerel": 2, "tuna": 3,
    "herring": 4, "salmon": 5, "cod": 6, "tilapia": 7,
    # Sri Lankan dataset names
    "balaya": 8, "hurulla": 9, "kumbalawa": 10, "salaya": 11, "sprats": 12,
}

INITIAL_FEATURES = [
    "fish_type_code",
    "initial_weight_kg",
    "temperature_c",
    "humidity_percent",
]
INITIAL_TARGET = "estimated_total_drying_time_hours"

DYNAMIC_FEATURES = [
    "fish_type_code",
    "initial_weight_kg",
    "current_weight_kg",
    "temperature_c",
    "humidity_percent",
    "elapsed_drying_time_hours",
    "weight_loss_rate",
]
DYNAMIC_TARGET = "remaining_drying_time_hours"

# Map raw dataset column names to the canonical names the API uses.
DYNAMIC_COLUMN_RENAMES = {
    "elapsed_time_hours": "elapsed_drying_time_hours",
    "weight_loss_rate_kg_per_hour": "weight_loss_rate",
}


def _encode_fish_type(series: pd.Series) -> pd.Series:
    normalized = series.astype(str).str.strip().str.lower()
    unknown = sorted(set(normalized) - set(FISH_TYPE_ENCODING))
    if unknown:
        print(f"  ! Warning: unknown fish_type values mapped to 0: {unknown}")
    return normalized.map(FISH_TYPE_ENCODING).fillna(0).astype(int)


def _load_initial_sheet() -> pd.DataFrame:
    df = pd.read_excel(DATASET_PATH, sheet_name=INITIAL_SHEET)
    df["fish_type_code"] = _encode_fish_type(df["fish_type"])
    return df


def _load_dynamic_sheet() -> pd.DataFrame:
    df = pd.read_excel(DATASET_PATH, sheet_name=DYNAMIC_SHEET)
    df = df.rename(columns=DYNAMIC_COLUMN_RENAMES)
    df["fish_type_code"] = _encode_fish_type(df["fish_type"])
    return df


def _train_and_save(
    df: pd.DataFrame,
    features: list[str],
    target: str,
    model_out: Path,
    label: str,
) -> Tuple[float, float]:
    missing = [c for c in features + [target] if c not in df.columns]
    if missing:
        raise ValueError(f"[{label}] dataset missing columns: {missing}")

    X = df[features].values
    y = df[target].values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )
    model = RandomForestRegressor(
        n_estimators=200, max_depth=20, random_state=42, n_jobs=-1
    )
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    mae = mean_absolute_error(y_test, preds)
    r2 = r2_score(y_test, preds)
    print(f"[{label}] MAE={mae:.3f} | R2={r2:.3f} | n_train={len(X_train)} n_test={len(X_test)}")

    os.makedirs(model_out.parent, exist_ok=True)
    joblib.dump(model, model_out)
    print(f"[{label}] Saved ->{model_out}")
    return mae, r2


def main() -> None:
    if not DATASET_PATH.exists():
        raise FileNotFoundError(
            f"Dataset not found at {DATASET_PATH}. "
            "Place the Excel file in datasets/ before running."
        )
    print(f"Loading dataset: {DATASET_PATH}")

    print("\n--- Initial drying time model (Sheet 1) ---")
    initial_df = _load_initial_sheet()
    _train_and_save(
        initial_df, INITIAL_FEATURES, INITIAL_TARGET, INITIAL_MODEL_OUT, "initial"
    )

    print("\n--- Dynamic drying time model (Sheet 2) ---")
    dynamic_df = _load_dynamic_sheet()
    _train_and_save(
        dynamic_df, DYNAMIC_FEATURES, DYNAMIC_TARGET, DYNAMIC_MODEL_OUT, "dynamic"
    )


if __name__ == "__main__":
    main()
