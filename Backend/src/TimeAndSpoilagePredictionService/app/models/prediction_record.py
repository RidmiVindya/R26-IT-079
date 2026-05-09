"""MongoDB persistence model (document shape) for prediction records."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional


def build_prediction_record(
    *,
    batch_id: str,
    prediction_type: str,
    inputs: Dict[str, Any],
    predicted_drying_time_hours: Optional[float] = None,
    smell_level: Optional[str] = None,
    spoilage_risk: Optional[str] = None,
    drying_status: Optional[str] = None,
    smart_recommendation: Optional[str] = None,
    model_used: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "batch_id": batch_id,
        "prediction_type": prediction_type,
        "inputs": inputs,
        "predicted_drying_time_hours": predicted_drying_time_hours,
        "smell_level": smell_level,
        "spoilage_risk": spoilage_risk,
        "drying_status": drying_status,
        "smart_recommendation": smart_recommendation,
        "model_used": model_used,
        "created_at": datetime.now(timezone.utc),
    }
