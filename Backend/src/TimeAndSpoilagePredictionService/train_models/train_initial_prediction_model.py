"""Train the initial (pre-drying) temperature + time prediction model.

Reads `datasets/fish_drying_synthetic_3000.csv` and trains a candidate set of
3 multi-output regressors that jointly predict, from conditions known BEFORE
drying starts:

    - recommended_temperature_c
    - estimated_total_drying_time_hours

given: fish_type, initial_weight_kg, humidity_percent, mq136_value.

Picks the best candidate by 5-fold cross-validation R^2 (averaged across both
targets).

Outputs (in app/ml_models/):
    initial_prediction_<Model>.pkl     # each candidate
    initial_prediction_model.pkl       # best (canonical, used by API)
    comparison_initial_prediction.csv  # full metrics table

Run from the service root:
    python -m train_models.train_initial_prediction_model
"""
from __future__ import annotations

import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import KFold, cross_val_score
from sklearn.multioutput import MultiOutputRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "datasets" / "fish_drying_synthetic_3000.csv"
MODELS_DIR = ROOT / "app" / "ml_models"
COMPARISON_OUT = MODELS_DIR / "comparison_initial_prediction.csv"

# Fish-type encoding shared with the API. Keep in sync with
# app/services/initial_prediction_service.py and app/config.ALLOWED_FISH_TYPES.
FISH_TYPE_ENCODING = {
    "sprats": 0, "salaya": 1, "hurulla": 2, "kumbalawa": 3,
    "kelawalla": 4, "balaya": 5, "mora": 6, "linna": 7,
    "paraw": 8, "thalapath": 9, "tuna": 10, "mackerel": 11,
}

FEATURES = [
    "fish_type_code",
    "initial_weight_kg",
    "humidity_percent",
    "mq136_value",
]
TARGETS = ["recommended_temperature_c", "estimated_total_drying_time_hours"]

CV_FOLDS = 5
RANDOM_STATE = 42


def _build_candidates() -> dict:
    return {
        "LinearRegression": Pipeline(
            [("scaler", StandardScaler()), ("model", MultiOutputRegressor(LinearRegression()))]
        ),
        "RandomForestRegressor": MultiOutputRegressor(
            RandomForestRegressor(n_estimators=200, max_depth=20, random_state=RANDOM_STATE, n_jobs=-1)
        ),
        "GradientBoostingRegressor": MultiOutputRegressor(
            GradientBoostingRegressor(n_estimators=200, max_depth=5, random_state=RANDOM_STATE)
        ),
    }


def _encode_fish_type(series: pd.Series) -> pd.Series:
    normalized = series.astype(str).str.strip().str.lower()
    unknown = sorted(set(normalized) - set(FISH_TYPE_ENCODING))
    if unknown:
        print(f"  ! Warning: unknown fish_type values mapped to 0: {unknown}")
    return normalized.map(FISH_TYPE_ENCODING).fillna(0).astype(int)


def _load_dataset() -> pd.DataFrame:
    df = pd.read_csv(DATASET_PATH)
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


def _print_table(rows: list[dict]) -> None:
    print("\n=== Initial prediction (temperature + time) : 5-fold CV comparison ===")
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


def main() -> None:
    if not DATASET_PATH.exists():
        raise FileNotFoundError(
            f"Dataset not found at {DATASET_PATH}. "
            "Place the CSV file in datasets/ before running."
        )
    print(f"Loading dataset: {DATASET_PATH}")
    os.makedirs(MODELS_DIR, exist_ok=True)

    df = _load_dataset()
    missing = [c for c in FEATURES + TARGETS if c not in df.columns]
    if missing:
        raise ValueError(f"Dataset missing columns: {missing}")

    X = df[FEATURES].values
    y = df[TARGETS].values

    rows: list[dict] = []
    for name, model in _build_candidates().items():
        # scikit-learn's multi-output R^2 scoring averages across targets
        # when y has 2 columns, which is what we want here.
        metrics = _evaluate_one(model, X, y)

        model.fit(X, y)
        out_path = MODELS_DIR / f"initial_prediction_{name}.pkl"
        joblib.dump(model, out_path)

        rows.append({
            "model": name,
            **metrics,
            "saved_path": str(out_path.relative_to(ROOT)),
            "_estimator": model,
        })

    rows.sort(key=lambda r: r["r2_mean"], reverse=True)
    rows[0]["is_best"] = True

    canonical_path = MODELS_DIR / "initial_prediction_model.pkl"
    joblib.dump(rows[0]["_estimator"], canonical_path)
    print(f"\nBest = {rows[0]['model']} -> {canonical_path.name}")

    _print_table(rows)
    for r in rows:
        r.pop("_estimator", None)

    pd.DataFrame(rows).to_csv(COMPARISON_OUT, index=False)
    print(f"\nComparison report -> {COMPARISON_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
