"""Spoilage risk classification service."""
from __future__ import annotations

import logging
import os
from typing import Optional, Tuple

import joblib
import numpy as np

from app.config import settings
from app.schemas.prediction_schema import SpoilageRiskRequest
from app.utils.helper import classify_smell_level

logger = logging.getLogger(__name__)

RISK_LABELS = ("Low", "Medium", "High")

# Must match train_models/train_spoilage_risk_model.py
SMELL_LEVEL_ENCODING = {"Low": 0, "Medium": 1, "High": 2}


class SpoilageRiskService:
    def __init__(self) -> None:
        self._model = None
        self._model_path = settings.SPOILAGE_RISK_MODEL_PATH
        self._load_model()

    def _load_model(self) -> None:
        if not os.path.exists(self._model_path):
            logger.warning(
                "Spoilage risk model not found at %s — using rule-based fallback.",
                self._model_path,
            )
            self._model = None
            return
        try:
            self._model = joblib.load(self._model_path)
            logger.info("Spoilage risk model loaded from %s", self._model_path)
        except Exception as exc:
            logger.error("Failed to load spoilage risk model: %s — using fallback.", exc)
            self._model = None

    @property
    def model_name(self) -> str:
        if self._model is None:
            return "RuleBasedFallback"
        if hasattr(self._model, "named_steps") and "model" in self._model.named_steps:
            return type(self._model.named_steps["model"]).__name__
        return type(self._model).__name__

    def predict(self, payload: SpoilageRiskRequest) -> Tuple[str, str, str]:
        smell_level = classify_smell_level(payload.mq136_value)

        if self._model is not None:
            try:
                features = self._build_features(payload, smell_level)
                raw = self._model.predict(features)[0]
                risk = self._normalize_label(raw)
                return smell_level, risk, self.model_name
            except Exception as exc:
                logger.error("Spoilage classifier failed (%s) — falling back.", exc)

        return smell_level, self._rule_based_predict(payload, smell_level), "RuleBasedFallback"

    def _build_features(self, p: SpoilageRiskRequest, smell_level: str) -> np.ndarray:
        smell_code = SMELL_LEVEL_ENCODING.get(smell_level, 0)
        return np.array(
            [
                [
                    p.temperature_c,
                    p.humidity_percent,
                    p.elapsed_drying_time_hours,
                    p.weight_loss_percentage,
                    smell_code,
                ]
            ],
            dtype=float,
        )

    @staticmethod
    def _normalize_label(raw) -> str:
        # Models trained on either string or integer labels
        if isinstance(raw, (int, np.integer)):
            idx = int(raw)
            return RISK_LABELS[idx] if 0 <= idx < len(RISK_LABELS) else "Low"
        label = str(raw).strip().capitalize()
        return label if label in RISK_LABELS else "Low"

    @staticmethod
    def _rule_based_predict(p: SpoilageRiskRequest, smell_level: str) -> str:
        score = 0
        if smell_level == "High":
            score += 3
        elif smell_level == "Medium":
            score += 1

        if p.humidity_percent >= 80:
            score += 2
        elif p.humidity_percent >= 65:
            score += 1

        if p.temperature_c >= 45:
            score += 2
        elif p.temperature_c <= 20:
            score += 1

        if p.elapsed_drying_time_hours >= 36 and p.weight_loss_percentage < 30:
            score += 2

        if score >= 4:
            return "High"
        if score >= 2:
            return "Medium"
        return "Low"


_service: Optional[SpoilageRiskService] = None


def get_spoilage_risk_service() -> SpoilageRiskService:
    global _service
    if _service is None:
        _service = SpoilageRiskService()
    return _service
