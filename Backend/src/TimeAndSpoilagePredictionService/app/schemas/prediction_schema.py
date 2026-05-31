"""Pydantic schemas for request/response validation."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import settings

SpoilageRiskLiteral = Literal["Low", "Medium", "High"]


# ---------------------------------------------------------------------------
# Drying time prediction
# ---------------------------------------------------------------------------
class DryingTimeRequest(BaseModel):
    fish_type: str = Field(..., description="Type of fish, e.g. salaya, sprats, mackerel")
    initial_weight_kg: float = Field(..., gt=0, le=500, description="Initial batch weight in kg")
    current_weight_kg: float = Field(..., ge=0, le=500, description="Current batch weight in kg")
    temperature_c: float = Field(..., ge=-10, le=120, description="Drying chamber temperature in Celsius")
    humidity_percent: float = Field(..., ge=0, le=100, description="Relative humidity percentage")
    elapsed_drying_time_hours: float = Field(..., ge=0, le=240, description="Hours elapsed since drying started")
    weight_loss_rate: float = Field(..., ge=0, description="kg lost per hour")

    @field_validator("fish_type")
    @classmethod
    def _validate_fish_type(cls, v: str) -> str:
        v_norm = v.strip().lower()
        if not v_norm:
            raise ValueError("fish_type cannot be empty")
        if v_norm not in settings.ALLOWED_FISH_TYPES:
            raise ValueError(
                f"Unsupported fish_type '{v}'. Allowed: {', '.join(settings.ALLOWED_FISH_TYPES)}"
            )
        return v_norm

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "fish_type": "salaya",
                "initial_weight_kg": 10.0,
                "current_weight_kg": 7.5,
                "temperature_c": 35.0,
                "humidity_percent": 55.0,
                "elapsed_drying_time_hours": 6.0,
                "weight_loss_rate": 0.42,
            }
        }
    )


class DryingTimeResponse(BaseModel):
    batch_id: str
    predicted_remaining_drying_time_hours: float
    model_used: str
    created_at: datetime

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "batch_id": "BATCH-9F12A4B6CD",
                "predicted_remaining_drying_time_hours": 8.42,
                "model_used": "RandomForestRegressor",
                "created_at": "2026-05-09T12:34:56Z",
            }
        }
    )


# ---------------------------------------------------------------------------
# Spoilage risk prediction
# ---------------------------------------------------------------------------
class SpoilageRiskRequest(BaseModel):
    temperature_c: float = Field(..., ge=-10, le=120)
    humidity_percent: float = Field(..., ge=0, le=100)
    elapsed_drying_time_hours: float = Field(..., ge=0, le=240)
    weight_loss_percentage: float = Field(..., ge=0, le=100)
    mq136_value: float = Field(..., ge=0, le=4096, description="Raw MQ-136 sensor reading")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "temperature_c": 32.5,
                "humidity_percent": 65.0,
                "elapsed_drying_time_hours": 8.0,
                "weight_loss_percentage": 28.5,
                "mq136_value": 410,
            }
        }
    )


class SpoilageRiskResponse(BaseModel):
    batch_id: str
    smell_level: SpoilageRiskLiteral
    spoilage_risk: SpoilageRiskLiteral
    model_used: str
    created_at: datetime

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "batch_id": "BATCH-9F12A4B6CD",
                "smell_level": "Medium",
                "spoilage_risk": "Medium",
                "model_used": "RandomForestClassifier",
                "created_at": "2026-05-09T12:34:56Z",
            }
        }
    )


# ---------------------------------------------------------------------------
# Smart recommendation
# ---------------------------------------------------------------------------
class RecommendationRequest(BaseModel):
    temperature_c: float = Field(..., ge=-10, le=120)
    humidity_percent: float = Field(..., ge=0, le=100)
    elapsed_drying_time_hours: float = Field(..., ge=0, le=240)
    weight_loss_percentage: float = Field(..., ge=0, le=100)
    weight_loss_rate: float = Field(..., ge=0)
    mq136_value: float = Field(..., ge=0, le=4096)
    spoilage_risk: SpoilageRiskLiteral

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "temperature_c": 31.0,
                "humidity_percent": 72.0,
                "elapsed_drying_time_hours": 10.0,
                "weight_loss_percentage": 35.0,
                "weight_loss_rate": 0.38,
                "mq136_value": 250,
                "spoilage_risk": "Low",
            }
        }
    )


class RecommendationResponse(BaseModel):
    batch_id: str
    drying_status: str
    smart_recommendation: str
    smell_level: SpoilageRiskLiteral
    created_at: datetime

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "batch_id": "BATCH-9F12A4B6CD",
                "drying_status": "Drying In Progress - Early Stage",
                "smart_recommendation": "Increase airflow and reduce humidity",
                "smell_level": "Low",
                "created_at": "2026-05-09T12:34:56Z",
            }
        }
    )


# ---------------------------------------------------------------------------
# Common error response
# ---------------------------------------------------------------------------
class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    detail: Optional[str] = None
