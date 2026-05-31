"""Train and compare drying-time regression models.

Reads `datasets/drying_time__dataset.xlsx` with two sheets and trains a
candidate set of 3 regressors per sub-task, picking the best by 5-fold
cross-validation R^2.

Sub-tasks:
    - Initial_Time_Prediction  -> total drying time before drying starts
    - Dynamic_Time_Prediction  -> remaining drying time during drying

Outputs (in app/ml_models/):
    initial_drying_time_<Model>.pkl     # each candidate
    initial_drying_time_model.pkl       # best (canonical, used by API if added)
    drying_time_<Model>.pkl             # each candidate
    drying_time_model.pkl               # best (canonical, used by API)
    comparison_drying_time.csv          # full metrics table

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
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import KFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "datasets" / "drying_time__dataset.xlsx"
MODELS_DIR = ROOT / "app" / "ml_models"
COMPARISON_OUT = MODELS_DIR / "comparison_drying_time.csv"

INITIAL_SHEET = "Initial_Time_Prediction"
DYNAMIC_SHEET = "Dynamic_Time_Prediction"

# Fish-type encoding shared with the API. Keep in sync with
# app/services/drying_time_service.py and app/config.ALLOWED_FISH_TYPES.
FISH_TYPE_ENCODING = {
    "sprats": 0, "salaya": 1, "hurulla": 2, "kumbalawa": 3,
    "kelawalla": 4, "balaya": 5, "mora": 6, "linna": 7,
    "paraw": 8, "thalapath": 9, "tuna": 10, "mackerel": 11,
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

DYNAMIC_COLUMN_RENAMES = {
    "elapsed_time_hours": "elapsed_drying_time_hours",
    "weight_loss_rate_kg_per_hour": "weight_loss_rate",
}

CV_FOLDS = 5
RANDOM_STATE = 42


def _build_candidates() -> dict:
    return {
        "LinearRegression": Pipeline(
            [("scaler", StandardScaler()), ("model", LinearRegression())]
        ),
        "RandomForestRegressor": RandomForestRegressor(
            n_estimators=200, max_depth=20, random_state=RANDOM_STATE, n_jobs=-1
        ),
        "GradientBoostingRegressor": GradientBoostingRegressor(
            n_estimators=200, max_depth=5, random_state=RANDOM_STATE
        ),
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


def _evaluate_one(model, X: np.ndarray, y: np.ndarray) -> dict:
    cv = KFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    r2 = cross_val_score(model, X, y, cv=cv, scoring="r2")
    mae = -cross_val_score(model, X, y, cv=cv, scoring="neg_mean_absolute_error")
    rmse = -cross_val_score(model, X, y, cv=cv, scoring="neg_root_mean_squared_error")
    return {
        "r2_mean": r2.mean(), "r2_std": r2.std(),
        "mae_mean": mae.mean(), "mae_std": mae.std(),
        "rmse_mean": rmse.mean(), "rmse_std": rmse.std(),
    }


def _print_table(rows: list[dict], task: str) -> None:
    print(f"\n=== {task} : 5-fold CV comparison ===")
    print(f"{'Model':28s} | {'R^2 (mean+/-std)':22s} | {'MAE':18s} | {'RMSE':18s}")
    print("-" * 96)
    for r in rows:
        marker = "  <-- BEST" if r.get("is_best") else ""
        print(
            f"{r['model']:28s} | "
            f"{r['r2_mean']:+.3f} +/- {r['r2_std']:.3f}    | "
            f"{r['mae_mean']:5.3f} +/- {r['mae_std']:.3f}  | "
            f"{r['rmse_mean']:5.3f} +/- {r['rmse_std']:.3f}{marker}"
        )


def _run_task(
    df: pd.DataFrame,
    features: list[str],
    target: str,
    file_prefix: str,
    canonical_name: str,
    task_label: str,
) -> list[dict]:
    missing = [c for c in features + [target] if c not in df.columns]
    if missing:
        raise ValueError(f"[{task_label}] dataset missing columns: {missing}")

    X = df[features].values
    y = df[target].values

    rows: list[dict] = []
    for name, model in _build_candidates().items():
        metrics = _evaluate_one(model, X, y)

        # Train on full data and persist this candidate
        model.fit(X, y)
        out_path = MODELS_DIR / f"{file_prefix}_{name}.pkl"
        joblib.dump(model, out_path)

        rows.append({
            "task": task_label,
            "model": name,
            **metrics,
            "saved_path": str(out_path.relative_to(ROOT)),
            "_estimator": model,
        })

    rows.sort(key=lambda r: r["r2_mean"], reverse=True)
    rows[0]["is_best"] = True

    # Save best as the canonical name the API loads
    canonical_path = MODELS_DIR / canonical_name
    joblib.dump(rows[0]["_estimator"], canonical_path)
    print(f"\n[{task_label}] Best = {rows[0]['model']} -> {canonical_path.name}")

    _print_table(rows, task_label)
    # Drop the un-serializable estimator before returning for the CSV
    for r in rows:
        r.pop("_estimator", None)
    return rows


def main() -> None:
    if not DATASET_PATH.exists():
        raise FileNotFoundError(
            f"Dataset not found at {DATASET_PATH}. "
            "Place the Excel file in datasets/ before running."
        )
    print(f"Loading dataset: {DATASET_PATH}")
    os.makedirs(MODELS_DIR, exist_ok=True)

    initial_rows = _run_task(
        _load_initial_sheet(),
        INITIAL_FEATURES, INITIAL_TARGET,
        file_prefix="initial_drying_time",
        canonical_name="initial_drying_time_model.pkl",
        task_label="Initial drying time",
    )
    dynamic_rows = _run_task(
        _load_dynamic_sheet(),
        DYNAMIC_FEATURES, DYNAMIC_TARGET,
        file_prefix="drying_time",
        canonical_name="drying_time_model.pkl",
        task_label="Dynamic drying time",
    )

    pd.DataFrame(initial_rows + dynamic_rows).to_csv(COMPARISON_OUT, index=False)
    print(f"\nComparison report -> {COMPARISON_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
