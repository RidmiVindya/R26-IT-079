"""Train and compare spoilage-risk classifiers.

Reads `datasets/spoilage_risk_dataset.xlsx` (sheet `Spoilage_Risk_Dataset`)
and trains 3 candidate classifiers, picking the best by stratified 5-fold
cross-validation weighted F1.

The categorical `smell_sensor_output` is label-encoded to a numeric
`smell_level_code` (Low=0, Medium=1, High=2). At inference time the API
converts its raw MQ-136 reading to the same Low/Medium/High bucket via
`app.utils.helper.classify_smell_level`, then encodes it the same way.

Outputs (in app/ml_models/):
    spoilage_risk_<Model>.pkl     # each candidate
    spoilage_risk_model.pkl       # best (canonical, used by API)
    comparison_spoilage_risk.csv  # full metrics table

Run from the service root:
    python -m train_models.train_spoilage_risk_model
"""
from __future__ import annotations

import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "datasets" / "spoilage_risk_dataset.xlsx"
MODELS_DIR = ROOT / "app" / "ml_models"
COMPARISON_OUT = MODELS_DIR / "comparison_spoilage_risk.csv"
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

CV_FOLDS = 5
RANDOM_STATE = 42


def _build_candidates() -> dict:
    return {
        "LogisticRegression": Pipeline([
            ("scaler", StandardScaler()),
            ("model", LogisticRegression(
                max_iter=2000, class_weight="balanced",
                random_state=RANDOM_STATE,
            )),
        ]),
        "RandomForestClassifier": RandomForestClassifier(
            n_estimators=200, max_depth=18, random_state=RANDOM_STATE,
            n_jobs=-1, class_weight="balanced",
        ),
        "GradientBoostingClassifier": GradientBoostingClassifier(
            n_estimators=200, max_depth=5, random_state=RANDOM_STATE,
        ),
    }


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


def _evaluate_one(model, X: np.ndarray, y: np.ndarray) -> dict:
    cv = StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    acc = cross_val_score(model, X, y, cv=cv, scoring="accuracy")
    f1w = cross_val_score(model, X, y, cv=cv, scoring="f1_weighted")
    prec = cross_val_score(model, X, y, cv=cv, scoring="precision_weighted")
    rec = cross_val_score(model, X, y, cv=cv, scoring="recall_weighted")
    return {
        "accuracy_mean": acc.mean(), "accuracy_std": acc.std(),
        "f1_weighted_mean": f1w.mean(), "f1_weighted_std": f1w.std(),
        "precision_weighted_mean": prec.mean(), "precision_weighted_std": prec.std(),
        "recall_weighted_mean": rec.mean(), "recall_weighted_std": rec.std(),
    }


def _print_table(rows: list[dict]) -> None:
    print("\n=== Spoilage risk : stratified 5-fold CV comparison ===")
    print(f"{'Model':28s} | {'Accuracy':18s} | {'F1 (weighted)':18s} | {'Precision':18s} | {'Recall':18s}")
    print("-" * 116)
    for r in rows:
        marker = "  <-- BEST" if r.get("is_best") else ""
        print(
            f"{r['model']:28s} | "
            f"{r['accuracy_mean']:.3f} +/- {r['accuracy_std']:.3f} | "
            f"{r['f1_weighted_mean']:.3f} +/- {r['f1_weighted_std']:.3f} | "
            f"{r['precision_weighted_mean']:.3f} +/- {r['precision_weighted_std']:.3f} | "
            f"{r['recall_weighted_mean']:.3f} +/- {r['recall_weighted_std']:.3f}{marker}"
        )


def main() -> None:
    df = _load_dataset()
    missing = [c for c in FEATURES + [TARGET] if c not in df.columns]
    if missing:
        raise ValueError(f"Dataset missing columns: {missing}")

    X = df[FEATURES].values
    y = df[TARGET].astype(str).str.strip().str.capitalize().values
    os.makedirs(MODELS_DIR, exist_ok=True)

    rows: list[dict] = []
    for name, model in _build_candidates().items():
        metrics = _evaluate_one(model, X, y)
        model.fit(X, y)
        out_path = MODELS_DIR / f"spoilage_risk_{name}.pkl"
        joblib.dump(model, out_path)
        rows.append({
            "task": "Spoilage risk",
            "model": name,
            **metrics,
            "saved_path": str(out_path.relative_to(ROOT)),
            "_estimator": model,
        })

    rows.sort(key=lambda r: r["f1_weighted_mean"], reverse=True)
    rows[0]["is_best"] = True

    canonical_path = MODELS_DIR / "spoilage_risk_model.pkl"
    joblib.dump(rows[0]["_estimator"], canonical_path)
    print(f"\nBest = {rows[0]['model']} -> {canonical_path.name}")

    _print_table(rows)
    for r in rows:
        r.pop("_estimator", None)

    pd.DataFrame(rows).to_csv(COMPARISON_OUT, index=False)
    print(f"\nComparison report -> {COMPARISON_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
