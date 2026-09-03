"""Train the dynamic (in-progress) drying-time model.

Reads datasets/dynamic_drying_time_simulated.csv and saves the best model as
app/ml_models/drying_time_model.pkl - the path DryingTimeService loads.

    *** Trained on SIMULATED data. See the dataset generator's docstring. ***

Units
-----
The dataset is stored in grams / minutes because that is how the drying rig
reports and how the rows read. The FastAPI service predicts in kilograms /
hours (see DryingTimeService._build_features). This script converts, so the
saved model speaks the service's units. Getting this wrong does not raise -
it silently returns predictions off by orders of magnitude.

Feature order is fixed by the service and must not be reordered:

    [fish_code, initial_weight_kg, current_weight_kg, temperature_c,
     humidity_percent, elapsed_hours, weight_loss_rate_kg_per_h]

Target: remaining drying time in HOURS.

Validation
----------
Rows from one drying run are highly correlated - the same batch observed a few
minutes apart. Splitting rows at random would put a run's early observations in
train and its later ones in test, letting a model score well by recognising the
run rather than learning drying. Every split here is therefore by run_id, so a
run appears wholly in train or wholly in test.

Run from the service root:
    python train_models/train_dynamic_drying_time_model.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "datasets" / "dynamic_drying_time_simulated.csv"
MODELS_DIR = ROOT / "app" / "ml_models"
CANONICAL_OUT = MODELS_DIR / "drying_time_model.pkl"
COMPARISON_OUT = MODELS_DIR / "comparison_dynamic_drying_time.csv"

RANDOM_SEED = 42
N_SPLITS = 5

# Must match FISH_TYPE_ENCODING in app/services/drying_time_service.py.
FISH_TYPE_ENCODING = {
    "sprats": 0, "salaya": 1, "hurulla": 2, "kumbalawa": 3,
    "kelawalla": 4, "balaya": 5, "mora": 6, "linna": 7,
    "paraw": 8, "thalapath": 9, "tuna": 10, "mackerel": 11,
}

FEATURE_NAMES = [
    "fish_code",
    "initial_weight_kg",
    "current_weight_kg",
    "temperature_c",
    "humidity_percent",
    "elapsed_hours",
    "weight_loss_rate_kg_per_h",
]


def build_xy(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Convert the g/min dataset into the service's kg/hour feature contract."""
    unknown = set(df.fish_type.unique()) - set(FISH_TYPE_ENCODING)
    if unknown:
        raise ValueError(f"fish types missing from FISH_TYPE_ENCODING: {sorted(unknown)}")

    x = pd.DataFrame(
        {
            "fish_code": df.fish_type.map(FISH_TYPE_ENCODING).astype(float),
            "initial_weight_kg": df.initial_weight_g / 1000.0,
            "current_weight_kg": df.current_weight_g / 1000.0,
            "temperature_c": df.temperature_c,
            "humidity_percent": df.humidity_percent,
            "elapsed_hours": df.elapsed_time_min / 60.0,
            # g/min -> kg/h : (g/1000) per (min/60) = g * 60 / 1000 / min
            "weight_loss_rate_kg_per_h": df.weight_loss_rate_g_per_min * 60.0 / 1000.0,
        }
    )[FEATURE_NAMES]

    y = (df.remaining_drying_time_min / 60.0).to_numpy()
    groups = df.run_id.to_numpy()
    return x.to_numpy(dtype=float), y, groups


def candidates() -> dict[str, Pipeline]:
    return {
        "LinearRegression": Pipeline(
            [("scaler", StandardScaler()), ("model", LinearRegression())]
        ),
        "RandomForestRegressor": Pipeline(
            [(
                "model",
                RandomForestRegressor(
                    n_estimators=300,
                    min_samples_leaf=2,
                    random_state=RANDOM_SEED,
                    n_jobs=-1,
                ),
            )]
        ),
        "GradientBoostingRegressor": Pipeline(
            [(
                "model",
                GradientBoostingRegressor(random_state=RANDOM_SEED),
            )]
        ),
    }


def main() -> None:
    if not DATASET_PATH.exists():
        raise SystemExit(
            f"Dataset not found: {DATASET_PATH}\n"
            "Run train_models/generate_dynamic_drying_dataset.py first."
        )

    df = pd.read_csv(DATASET_PATH)
    x, y, groups = build_xy(df)
    print(f"Loaded {len(df)} rows across {df.run_id.nunique()} runs -> {DATASET_PATH.name}")
    print("*** SIMULATED training data - predictions inherit its assumptions. ***\n")

    splitter = GroupKFold(n_splits=N_SPLITS)
    folds = list(splitter.split(x, y, groups))

    results: list[dict] = []
    for name, pipeline in candidates().items():
        r2s, maes, rmses = [], [], []
        for train_idx, test_idx in folds:
            model = clone(pipeline)  # fresh unfitted copy per fold
            model.fit(x[train_idx], y[train_idx])
            pred = model.predict(x[test_idx])
            r2s.append(r2_score(y[test_idx], pred))
            maes.append(mean_absolute_error(y[test_idx], pred))
            rmses.append(float(np.sqrt(mean_squared_error(y[test_idx], pred))))
        results.append(
            {
                "model": name,
                "r2_mean": float(np.mean(r2s)),
                "r2_std": float(np.std(r2s)),
                "mae_hours_mean": float(np.mean(maes)),
                "mae_minutes_mean": float(np.mean(maes)) * 60.0,
                "rmse_hours_mean": float(np.mean(rmses)),
                "rmse_minutes_mean": float(np.mean(rmses)) * 60.0,
            }
        )

    table = pd.DataFrame(results).sort_values("r2_mean", ascending=False).reset_index(drop=True)
    best_name = str(table.loc[0, "model"])

    print(f"=== Dynamic remaining-time : {N_SPLITS}-fold GroupKFold by run_id ===")
    print(f"{'Model':<28}| {'R^2':>18} | {'MAE (min)':>10} | {'RMSE (min)':>10}")
    print("-" * 78)
    for _, row in table.iterrows():
        marker = "  <-- BEST" if row["model"] == best_name else ""
        print(
            f"{row['model']:<28}| {row['r2_mean']:>+8.3f} +/- {row['r2_std']:<5.3f} | "
            f"{row['mae_minutes_mean']:>10.2f} | {row['rmse_minutes_mean']:>10.2f}{marker}"
        )

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    table.to_csv(COMPARISON_OUT, index=False)

    # Refit the winner on every run before saving.
    best = candidates()[best_name]
    best.fit(x, y)
    joblib.dump(best, CANONICAL_OUT)

    print(f"\nSelected : {best_name} (highest cross-validated R^2)")
    print(f"Saved    : {CANONICAL_OUT.relative_to(ROOT)}")
    print(f"Report   : {COMPARISON_OUT.relative_to(ROOT)}")

    # Sanity check in the service's own units.
    probe = np.array([[7, 0.150, 0.110, 120.0, 30.0, 0.20, 0.12]], dtype=float)
    print(
        "\nProbe (linna, 150g -> 110g, 120C, 30%RH, 12min elapsed): "
        f"{float(best.predict(probe)[0]) * 60:.1f} min remaining"
    )


if __name__ == "__main__":
    main()
