"""Initial (pre-drying) temperature + total-drying-time prediction service.

Loads a trained scikit-learn MultiOutputRegressor on startup that jointly
predicts, from conditions known BEFORE drying starts:

    - recommended_temperature_c
    - estimated_total_drying_time_hours

If the .pkl file is missing or fails to load, falls back to a deterministic
rule-based predictor so the API remains usable.
"""
from __future__ import annotations

import logging
import os
from typing import Optional, Tuple

import joblib
import numpy as np

from app.config import settings
from app.schemas.prediction_schema import InitialPredictionRequest

logger = logging.getLogger(__name__)

# Encoded fish types - kept stable for fallback math AND must match training
# script (train_models/train_initial_prediction_model.py).
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

# Fish types accepted by the API that have no dedicated training data yet.
# Predictions for these fall back to the closest trained species until
# real data is collected and the model is retrained.
# "thora" (Seer/Spanish mackerel) is a distinct species from "thalapath"
# (Sailfish) but shares similar size/texture, so it borrows that model.
FISH_TYPE_ALIASES = {
    "thora": "thalapath",
}


def _resolve_fish_type(fish_type: str) -> str:
    normalized = fish_type.strip().lower()
    return FISH_TYPE_ALIASES.get(normalized, normalized)


class InitialPredictionService:
    def __init__(self) -> None:
        self._model = None
        self._model_path = settings.INITIAL_PREDICTION_MODEL_PATH
        self._load_model()

    def _load_model(self) -> None:
        if not os.path.exists(self._model_path):
            logger.warning(
                "Initial prediction model not found at %s — using rule-based fallback.",
                self._model_path,
            )
            self._model = None
            return
        try:
            self._model = joblib.load(self._model_path)
            logger.info("Initial prediction model loaded from %s", self._model_path)
        except Exception as exc:
            logger.error("Failed to load initial prediction model: %s — using fallback.", exc)
            self._model = None

    @property
    def model_name(self) -> str:
        if self._model is None:
            return "RuleBasedFallback"

        model = self._model
        if hasattr(model, "named_steps") and "model" in model.named_steps:
            model = model.named_steps["model"]

        # MultiOutputRegressor wraps a single-output estimator in `.estimator`.
        inner = getattr(model, "estimator", None)
        if inner is not None:
            return type(inner).__name__
        return type(model).__name__

    @staticmethod
    def apply_safety_limits(temperature: float, hours: float) -> Tuple[float, float]:
        """Clamp a recommendation to the configured safe operating envelope.

        The oven drives its heater toward whatever target temperature it is
        given, so a prediction is never handed onward unclamped. Limits live
        in config (MAX/MIN_DRYING_TEMPERATURE_C, MAX_DRYING_DURATION_HOURS)
        and can be overridden via .env.
        """
        safe_temperature = min(
            max(temperature, settings.MIN_DRYING_TEMPERATURE_C),
            settings.MAX_DRYING_TEMPERATURE_C,
        )
        safe_hours = min(max(hours, 0.0), settings.MAX_DRYING_DURATION_HOURS)

        if safe_temperature != temperature:
            logger.warning(
                "Predicted temperature %.2f C outside safe range %.1f-%.1f C — clamped to %.2f C.",
                temperature,
                settings.MIN_DRYING_TEMPERATURE_C,
                settings.MAX_DRYING_TEMPERATURE_C,
                safe_temperature,
            )
        if safe_hours != hours:
            logger.warning(
                "Predicted drying time %.2f h exceeds max %.1f h — clamped to %.2f h.",
                hours,
                settings.MAX_DRYING_DURATION_HOURS,
                safe_hours,
            )

        return round(safe_temperature, 2), round(safe_hours, 2)

    def predict(self, payload: InitialPredictionRequest) -> Tuple[float, float, str]:
        """Returns (recommended_temperature_c, estimated_total_drying_time_hours, model_used).

        The returned temperature/time are always within the configured safe
        limits — callers can hand them straight to the oven.
        """
        features = self._build_features(payload)
        if self._model is not None:
            try:
                pred = self._model.predict(features)[0]
                temperature = max(0.0, round(float(pred[0]), 2))
                hours = max(0.0, round(float(pred[1]), 2))
                temperature, hours = self.apply_safety_limits(temperature, hours)
                return temperature, hours, self.model_name
            except Exception as exc:
                logger.error("Model prediction failed (%s) — falling back.", exc)

        temperature, hours = self._rule_based_predict(payload)
        temperature, hours = self.apply_safety_limits(temperature, hours)
        return temperature, hours, "RuleBasedFallback"

    def _build_features(self, p: InitialPredictionRequest) -> np.ndarray:
        fish_code = FISH_TYPE_ENCODING.get(_resolve_fish_type(p.fish_type), 0)
        return np.array(
            [[fish_code, p.initial_weight_kg, p.humidity_percent, p.mq136_value]],
            dtype=float,
        )

    @staticmethod
    def _rule_based_predict(p: InitialPredictionRequest) -> Tuple[float, float]:
        """Heuristic estimate used only if no trained model is available."""
        normalized = _resolve_fish_type(p.fish_type)

        if normalized in ("salaya", "sprats", "kumbalawa"):
            temperature = 33.0 + (p.initial_weight_kg / 20.0)
        elif normalized in ("hurulla", "balaya"):
            temperature = 31.0 + (p.initial_weight_kg / 18.0)
        else:
            temperature = 32.0 + (p.initial_weight_kg / 25.0)

        # Humidity above 50% slows drying; nudge temperature up slightly to compensate.
        temperature += max(0.0, (p.humidity_percent - 50.0) / 20.0)
        temperature = round(temperature, 2)

        # Larger batches and higher humidity both extend total drying time.
        base_hours = p.initial_weight_kg * 0.7
        humidity_factor = 1.0 + max(0.0, (p.humidity_percent - 50.0) / 100.0)
        hours = round(min(base_hours * humidity_factor, 240.0), 2)

        return temperature, hours


_service: Optional[InitialPredictionService] = None


def get_initial_prediction_service() -> InitialPredictionService:
    global _service
    if _service is None:
        _service = InitialPredictionService()
    return _service
