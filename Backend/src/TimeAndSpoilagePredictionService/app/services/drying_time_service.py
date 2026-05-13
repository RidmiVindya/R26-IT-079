"""Drying-time prediction service.

Loads a trained scikit-learn RandomForestRegressor on startup. If the .pkl
file is missing or fails to load, falls back to a deterministic rule-based
predictor so the API remains usable while the IoT side is being built.
"""
from __future__ import annotations

import logging
import os
from typing import Optional, Tuple

import joblib
import numpy as np

from app.config import settings
from app.schemas.prediction_schema import DryingTimeRequest

logger = logging.getLogger(__name__)

# Encoded fish types - kept stable for fallback math AND must match training script
# (train_models/train_drying_time_model.py).
FISH_TYPE_ENCODING = {
    "sprats": 0,
    "salaya": 1,
    "hurulla": 2,
    "kumbalawa": 3,
    "kelawalla": 4,
    "balaya": 5,
    "mora": 6,
    "linna": 7,
    "paraw": 8,
    "thalapath": 9,
    "tuna": 10,
    "mackerel": 11,
}

TARGET_WEIGHT_LOSS_PERCENT = 65.0  # Considered "fully dried"


class DryingTimeService:
    def __init__(self) -> None:
        self._model = None
        self._model_path = settings.DRYING_TIME_MODEL_PATH
        self._load_model()

    def _load_model(self) -> None:
        if not os.path.exists(self._model_path):
            logger.warning(
                "Drying time model not found at %s — using rule-based fallback.",
                self._model_path,
            )
            self._model = None
            return
        try:
            self._model = joblib.load(self._model_path)
            logger.info("Drying time model loaded from %s", self._model_path)
        except Exception as exc:
            logger.error("Failed to load drying time model: %s — using fallback.", exc)
            self._model = None

    @property
    def model_name(self) -> str:
        if self._model is None:
            return "RuleBasedFallback"
        if hasattr(self._model, "named_steps") and "model" in self._model.named_steps:
            return type(self._model.named_steps["model"]).__name__
        return type(self._model).__name__

    def predict(self, payload: DryingTimeRequest) -> Tuple[float, str]:
        features = self._build_features(payload)
        if self._model is not None:
            try:
                pred = float(self._model.predict(features)[0])
                pred = max(0.0, round(pred, 2))
                return pred, self.model_name
            except Exception as exc:
                logger.error("Model prediction failed (%s) — falling back.", exc)

        return self._rule_based_predict(payload), "RuleBasedFallback"

    def _build_features(self, p: DryingTimeRequest) -> np.ndarray:
        fish_code = FISH_TYPE_ENCODING.get(p.fish_type, 0)
        return np.array(
            [
                [
                    fish_code,
                    p.initial_weight_kg,
                    p.current_weight_kg,
                    p.temperature_c,
                    p.humidity_percent,
                    p.elapsed_drying_time_hours,
                    p.weight_loss_rate,
                ]
            ],
            dtype=float,
        )

    @staticmethod
    def _rule_based_predict(p: DryingTimeRequest) -> float:
        """Estimate remaining drying hours from physical heuristics.

        - Compute remaining mass to lose to reach TARGET_WEIGHT_LOSS_PERCENT.
        - Adjust effective rate by humidity + temperature factors.
        """
        target_weight = p.initial_weight_kg * (1 - TARGET_WEIGHT_LOSS_PERCENT / 100.0)
        remaining_mass = max(0.0, p.current_weight_kg - target_weight)
        if remaining_mass <= 0:
            return 0.0

        base_rate = max(p.weight_loss_rate, 0.05)  # avoid div-by-zero
        humidity_factor = 1.0 + max(0.0, (p.humidity_percent - 50.0) / 100.0)
        temp_factor = 1.0 - max(-0.4, min(0.4, (p.temperature_c - 35.0) / 100.0))
        adjusted_rate = base_rate / (humidity_factor * temp_factor)
        adjusted_rate = max(adjusted_rate, 0.02)

        hours = remaining_mass / adjusted_rate
        return round(min(hours, 240.0), 2)


_service: Optional[DryingTimeService] = None


def get_drying_time_service() -> DryingTimeService:
    global _service
    if _service is None:
        _service = DryingTimeService()
    return _service
