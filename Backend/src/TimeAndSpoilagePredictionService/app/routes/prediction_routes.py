"""FastAPI routes for the prediction microservice."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.database import get_predictions_collection
from app.models.prediction_record import build_prediction_record
from app.schemas.prediction_schema import (
    DryingTimeRequest,
    DryingTimeResponse,
    ErrorResponse,
    RecommendationRequest,
    RecommendationResponse,
    SpoilageRiskRequest,
    SpoilageRiskResponse,
)
from app.services.drying_time_service import DryingTimeService, get_drying_time_service
from app.services.recommendation_service import RecommendationService, get_recommendation_service
from app.services.spoilage_risk_service import SpoilageRiskService, get_spoilage_risk_service
from app.utils.helper import new_batch_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/predict", tags=["Predictions"])


async def _persist(record: dict) -> None:
    coll = get_predictions_collection()
    if coll is None:
        return
    try:
        await coll.insert_one(record)
    except Exception as exc:
        logger.warning("Could not persist prediction record: %s", exc)


@router.post(
    "/drying-time",
    response_model=DryingTimeResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Predict remaining drying time",
)
async def predict_drying_time(
    payload: DryingTimeRequest,
    service: DryingTimeService = Depends(get_drying_time_service),
):
    if payload.current_weight_kg > payload.initial_weight_kg:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="current_weight_kg cannot exceed initial_weight_kg",
        )
    try:
        predicted_hours, model_used = service.predict(payload)
    except Exception as exc:
        logger.exception("Drying time prediction failed")
        raise HTTPException(status_code=500, detail=f"Prediction error: {exc}")

    batch_id = new_batch_id()
    created_at = datetime.now(timezone.utc)

    await _persist(
        build_prediction_record(
            batch_id=batch_id,
            prediction_type="drying_time",
            inputs=payload.model_dump(),
            predicted_drying_time_hours=predicted_hours,
            model_used=model_used,
        )
    )

    return DryingTimeResponse(
        batch_id=batch_id,
        predicted_remaining_drying_time_hours=predicted_hours,
        model_used=model_used,
        created_at=created_at,
    )


@router.post(
    "/spoilage-risk",
    response_model=SpoilageRiskResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Classify spoilage risk and smell level",
)
async def predict_spoilage_risk(
    payload: SpoilageRiskRequest,
    service: SpoilageRiskService = Depends(get_spoilage_risk_service),
):
    try:
        smell_level, risk, model_used = service.predict(payload)
    except Exception as exc:
        logger.exception("Spoilage risk prediction failed")
        raise HTTPException(status_code=500, detail=f"Prediction error: {exc}")

    batch_id = new_batch_id()
    created_at = datetime.now(timezone.utc)

    await _persist(
        build_prediction_record(
            batch_id=batch_id,
            prediction_type="spoilage_risk",
            inputs=payload.model_dump(),
            smell_level=smell_level,
            spoilage_risk=risk,
            model_used=model_used,
        )
    )

    return SpoilageRiskResponse(
        batch_id=batch_id,
        smell_level=smell_level,
        spoilage_risk=risk,
        model_used=model_used,
        created_at=created_at,
    )


@router.post(
    "/recommendation",
    response_model=RecommendationResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Generate smart drying recommendation",
)
async def generate_recommendation_endpoint(
    payload: RecommendationRequest,
    service: RecommendationService = Depends(get_recommendation_service),
):
    try:
        drying_status, recommendation, smell_level = service.generate(payload)
    except Exception as exc:
        logger.exception("Recommendation generation failed")
        raise HTTPException(status_code=500, detail=f"Recommendation error: {exc}")

    batch_id = new_batch_id()
    created_at = datetime.now(timezone.utc)

    await _persist(
        build_prediction_record(
            batch_id=batch_id,
            prediction_type="recommendation",
            inputs=payload.model_dump(),
            smell_level=smell_level,
            spoilage_risk=payload.spoilage_risk,
            drying_status=drying_status,
            smart_recommendation=recommendation,
        )
    )

    return RecommendationResponse(
        batch_id=batch_id,
        drying_status=drying_status,
        smart_recommendation=recommendation,
        smell_level=smell_level,
        created_at=created_at,
    )
