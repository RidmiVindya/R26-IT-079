"""Business logic helper functions used across services."""
from __future__ import annotations

import uuid
from typing import Literal

SpoilageRisk = Literal["Low", "Medium", "High"]
SmellLevel = Literal["Low", "Medium", "High"]


def calculate_weight_loss_percentage(initial_weight_kg: float, current_weight_kg: float) -> float:
    if initial_weight_kg <= 0:
        raise ValueError("initial_weight_kg must be greater than 0")
    if current_weight_kg < 0:
        raise ValueError("current_weight_kg cannot be negative")
    if current_weight_kg > initial_weight_kg:
        return 0.0
    return round(((initial_weight_kg - current_weight_kg) / initial_weight_kg) * 100.0, 2)


def calculate_weight_loss_rate(
    initial_weight_kg: float, current_weight_kg: float, elapsed_drying_time_hours: float
) -> float:
    if elapsed_drying_time_hours <= 0:
        return 0.0
    if initial_weight_kg <= 0:
        raise ValueError("initial_weight_kg must be greater than 0")
    weight_loss = max(0.0, initial_weight_kg - current_weight_kg)
    return round(weight_loss / elapsed_drying_time_hours, 4)


def classify_smell_level(mq136_value: float) -> SmellLevel:
    if mq136_value < 0:
        raise ValueError("mq136_value cannot be negative")
    if mq136_value <= 300:
        return "Low"
    if mq136_value <= 600:
        return "Medium"
    return "High"


def generate_drying_status(
    weight_loss_percentage: float,
    elapsed_drying_time_hours: float,
    spoilage_risk: SpoilageRisk,
) -> str:
    if spoilage_risk == "High":
        return "At Risk - Immediate Inspection Required"
    if weight_loss_percentage >= 60:
        return "Drying Almost Complete"
    if weight_loss_percentage >= 40:
        return "Drying In Progress - Mid Stage"
    if weight_loss_percentage >= 15:
        return "Drying In Progress - Early Stage"
    if elapsed_drying_time_hours < 2:
        return "Drying Just Started"
    return "Slow Drying - Monitor Conditions"


def generate_recommendation(
    temperature_c: float,
    humidity_percent: float,
    weight_loss_percentage: float,
    weight_loss_rate: float,
    smell_level: SmellLevel,
    spoilage_risk: SpoilageRisk,
) -> str:
    if spoilage_risk == "High" or smell_level == "High":
        return "Inspect batch and reduce humidity"

    if humidity_percent > 75:
        return "Increase airflow and reduce humidity"

    if temperature_c < 30:
        return "Increase temperature slightly"

    if spoilage_risk == "Medium" or smell_level == "Medium":
        return "Continue monitoring closely"

    if weight_loss_percentage >= 55 and weight_loss_rate > 0:
        return "Prepare for completion check"

    return "Maintain current conditions"


def new_batch_id() -> str:
    return f"BATCH-{uuid.uuid4().hex[:10].upper()}"
