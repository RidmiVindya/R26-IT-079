"""Smart drying recommendation service.

Pure rule-based: combines current sensor readings, derived smell level and
the spoilage risk to produce drying status + recommendation strings.
"""
from __future__ import annotations

from typing import Tuple

from app.schemas.prediction_schema import RecommendationRequest
from app.utils.helper import (
    classify_smell_level,
    generate_drying_status,
    generate_recommendation,
)


class RecommendationService:
    def generate(self, payload: RecommendationRequest) -> Tuple[str, str, str]:
        smell_level = classify_smell_level(payload.mq136_value)

        drying_status = generate_drying_status(
            weight_loss_percentage=payload.weight_loss_percentage,
            elapsed_drying_time_hours=payload.elapsed_drying_time_hours,
            spoilage_risk=payload.spoilage_risk,
        )

        recommendation = generate_recommendation(
            temperature_c=payload.temperature_c,
            humidity_percent=payload.humidity_percent,
            weight_loss_percentage=payload.weight_loss_percentage,
            weight_loss_rate=payload.weight_loss_rate,
            smell_level=smell_level,
            spoilage_risk=payload.spoilage_risk,
        )
        return drying_status, recommendation, smell_level


_service: RecommendationService | None = None


def get_recommendation_service() -> RecommendationService:
    global _service
    if _service is None:
        _service = RecommendationService()
    return _service
