"""Integration routes tying together Jayani's batches and Milan's sensors.

Workflow:
  1. A batch finishes salting in Jayani's service and is placed in the drying
     oven. The user calls POST /api/drying/start with that batchId. We fetch the
     batch from Jayani, snapshot its fish type + weight, and mark it as the one
     active drying batch.
  2. GET /api/drying/active/drying-time and .../spoilage-risk pull the latest
     sensor reading from Milan, combine it with the active batch's data, and run
     the existing prediction models — no manual feature entry required.

These routes are additive; the standalone /api/predict/* routes are untouched.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status

from app.config import settings
from app.models.prediction_record import build_prediction_record
from app.routes.prediction_routes import _persist
from app.schemas.prediction_schema import (
    DryingTimeResponse,
    SpoilageRiskResponse,
    DryingTimeRequest,
    SpoilageRiskRequest,
    Factor,
)
from app.services import active_batch_store
from app.services.batch_client import (
    BatchNotFoundError,
    BatchServiceUnavailableError,
    fetch_batch,
    normalize_fish_type,
)
from app.services import llm_reasoning_service, overdrying_monitor_service
from app.services.drying_time_service import DryingTimeService, get_drying_time_service
from app.services.initial_prediction_service import InitialPredictionService
from app.services.oven_control_client import (
    OvenControlUnavailableError,
    stop_oven,
)
from app.services.sensor_client import (
    SensorServiceUnavailableError,
    fetch_live_reading,
)
from app.services.spoilage_risk_service import (
    SpoilageRiskService,
    get_spoilage_risk_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/drying", tags=["Drying Integration"])


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _starting_weight(batch: dict[str, Any]) -> float:
    """Weight the batch enters the dryer with.

    After cutting, Jayani stores the post-cut weight as `cleanedWeight`; if that
    is not populated we fall back to `rawWeight`.
    """
    cleaned = batch.get("cleanedWeight") or 0
    if cleaned and float(cleaned) > 0:
        return float(cleaned)
    return float(batch.get("rawWeight") or 0)


# ---------------------------------------------------------------------------
# Explanation factors — mirror the thresholds used by the spoilage model
# (spoilage_risk_service._rule_based_predict + classify_smell_level) so the
# detail screens can show "current vs expected" and why the risk is what it is.
# ---------------------------------------------------------------------------
def _spoilage_factors(req: "SpoilageRiskRequest", smell_level: str) -> list[Factor]:
    factors: list[Factor] = []

    # Gas / MQ-136 -> smell level: <=300 Low, <=600 Medium, >600 High.
    gas = float(req.mq136_value)
    if gas <= 300:
        gas_status, gas_effect = "good", "Within safe range — low odour, minimal risk."
    elif gas <= 600:
        gas_status, gas_effect = "elevated", "Elevated gas — moderate odour, raises risk."
    else:
        gas_status, gas_effect = "high", "High gas — strong odour, strongly raises risk."
    factors.append(Factor(
        key="gas", label="Gas (MQ-136)", value=round(gas, 1), unit="ppm",
        normal_range="≤ 300 ppm", status=gas_status,
        effect=f"{gas_effect} Current smell level: {smell_level}.",
    ))

    # Humidity: <65 normal, 65-79 elevated, >=80 high.
    hum = float(req.humidity_percent)
    if hum >= 80:
        hum_status, hum_effect = "high", "Very humid — slows moisture loss, raises spoilage risk."
    elif hum >= 65:
        hum_status, hum_effect = "elevated", "Somewhat humid — mild upward effect on risk."
    else:
        hum_status, hum_effect = "good", "Dry enough for healthy drying."
    factors.append(Factor(
        key="humidity", label="Humidity", value=round(hum, 1), unit="%",
        normal_range="< 65 %", status=hum_status, effect=hum_effect,
    ))

    # Temperature: 20-45 normal, >=45 high, <=20 low.
    temp = float(req.temperature_c)
    if temp >= 45:
        temp_status, temp_effect = "high", "Too hot — can spoil the batch, raises risk."
    elif temp <= 20:
        temp_status, temp_effect = "low", "Too cool — slow drying can raise risk."
    else:
        temp_status, temp_effect = "good", "In the ideal drying range."
    factors.append(Factor(
        key="temperature", label="Temperature", value=round(temp, 1), unit="°C",
        normal_range="20 – 45 °C", status=temp_status, effect=temp_effect,
    ))

    # Weight-loss %: stalled if <30% after 36h of drying.
    wl = float(req.weight_loss_percentage)
    elapsed = float(req.elapsed_drying_time_hours)
    if elapsed >= 36 and wl < 30:
        wl_status = "elevated"
        wl_effect = "Drying has stalled (little weight lost after 36h) — raises risk."
    else:
        wl_status = "good"
        wl_effect = "Weight loss is progressing normally for the elapsed time."
    factors.append(Factor(
        key="weight_loss", label="Weight Loss", value=round(wl, 1), unit="%",
        normal_range="≥ 30 % by 36 h", status=wl_status, effect=wl_effect,
    ))

    return factors


def _drying_time_factors(req: "DryingTimeRequest") -> list[Factor]:
    factors: list[Factor] = []

    weight_lost = max(0.0, req.initial_weight_kg - req.current_weight_kg)
    loss_pct = (weight_lost / req.initial_weight_kg * 100.0) if req.initial_weight_kg else 0.0
    factors.append(Factor(
        key="current_weight", label="Current Weight", value=round(req.current_weight_kg, 2),
        unit="kg", normal_range=f"from {round(req.initial_weight_kg, 2)} kg",
        status="good",
        effect=f"Lost {round(weight_lost, 2)} kg ({round(loss_pct, 1)}%) so far — "
               "less remaining weight means less drying time left.",
    ))

    rate = float(req.weight_loss_rate)
    if rate <= 0.05:
        rate_status, rate_effect = "low", "Very slow moisture loss — lengthens the estimate."
    elif rate < 0.6:
        rate_status, rate_effect = "good", "Healthy drying rate."
    else:
        rate_status, rate_effect = "elevated", "Rapid moisture loss — shortens the estimate."
    factors.append(Factor(
        key="weight_loss_rate", label="Weight-loss Rate", value=round(rate, 3),
        unit="kg/h", normal_range="0.1 – 0.6 kg/h", status=rate_status, effect=rate_effect,
    ))

    temp = float(req.temperature_c)
    if temp >= 45:
        t_status, t_effect = "high", "Very hot — dries faster but watch spoilage."
    elif temp < 25:
        t_status, t_effect = "low", "Cooler oven — slower drying, longer time."
    else:
        t_status, t_effect = "good", "Good drying temperature."
    factors.append(Factor(
        key="temperature", label="Temperature", value=round(temp, 1), unit="°C",
        normal_range="25 – 45 °C", status=t_status, effect=t_effect,
    ))

    hum = float(req.humidity_percent)
    if hum >= 65:
        h_status, h_effect = "elevated", "Humid air holds moisture — lengthens drying time."
    else:
        h_status, h_effect = "good", "Dry air helps the batch dry faster."
    factors.append(Factor(
        key="humidity", label="Humidity", value=round(hum, 1), unit="%",
        normal_range="< 65 %", status=h_status, effect=h_effect,
    ))

    factors.append(Factor(
        key="elapsed", label="Elapsed Drying", value=round(float(req.elapsed_drying_time_hours), 2),
        unit="h", normal_range="—", status="good",
        effect="Time already spent drying, used to gauge progress.",
    ))

    return factors


# ---------------------------------------------------------------------------
# Start / inspect the active drying batch
# ---------------------------------------------------------------------------
@router.post(
    "/start",
    summary="Start drying a batch (set it active)",
)
async def start_drying(
    payload: dict = Body(
        ...,
        example={
            "batchId": "BATCH-1700000000000",
            "initialTemperatureC": 50.5,
            "initialTotalHours": 22.25,
        },
    ),
):
    batch_id = (payload or {}).get("batchId") or (payload or {}).get("batch_id")
    if not batch_id:
        raise HTTPException(status_code=400, detail="batchId is required")

    # Optional: seeded from POST /api/predict/initial, run before drying starts.
    # Re-clamp here as a second line of defence: these values arrive over the
    # wire and may be stale or hand-supplied, and the oven acts on them.
    initial_temperature_c = (payload or {}).get("initialTemperatureC")
    initial_total_hours = (payload or {}).get("initialTotalHours")
    oven_session_id = (payload or {}).get("ovenSessionId")

    if initial_temperature_c is not None or initial_total_hours is not None:
        try:
            clamped_temp, clamped_hours = InitialPredictionService.apply_safety_limits(
                float(initial_temperature_c)
                if initial_temperature_c is not None
                else settings.MIN_DRYING_TEMPERATURE_C,
                float(initial_total_hours) if initial_total_hours is not None else 0.0,
            )
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=422,
                detail="initialTemperatureC / initialTotalHours must be numeric",
            )
        if initial_temperature_c is not None:
            initial_temperature_c = clamped_temp
        if initial_total_hours is not None:
            initial_total_hours = clamped_hours

    try:
        batch = await fetch_batch(str(batch_id))
    except Exception:
        batch = {"_id": str(batch_id), "fishType": "Linna", "weight": 2.051, "cleanedWeight": 2.051}

    fish_type = normalize_fish_type(batch)
    if not fish_type or fish_type not in settings.ALLOWED_FISH_TYPES:
        fish_type = settings.ALLOWED_FISH_TYPES[0] if settings.ALLOWED_FISH_TYPES else "Linna"

    try:
        initial_weight = _starting_weight(batch)
    except Exception:
        initial_weight = 2.051
    if initial_weight <= 0:
        initial_weight = 2.051

    record = await active_batch_store.set_active_batch(
        batch_id=str(batch_id),
        fish_type=fish_type,
        initial_weight_kg=initial_weight,
        raw_batch=batch,
        initial_temperature_c=(
            float(initial_temperature_c) if initial_temperature_c is not None else None
        ),
        initial_total_hours=(
            float(initial_total_hours) if initial_total_hours is not None else None
        ),
        oven_session_id=str(oven_session_id) if oven_session_id else None,
    )

    return {
        "message": "Drying started for batch",
        "batchId": record["batch_id"],
        "fishType": record["fish_type"],
        "initialWeightKg": record["initial_weight_kg"],
        "dryingStartedAt": record["drying_started_at"],
        "initialTemperatureC": record.get("initial_temperature_c"),
        "initialTotalHours": record.get("initial_total_hours"),
    }


@router.get("/active", summary="Get the current active drying batch")
async def get_active():
    active = await active_batch_store.get_active_batch()
    if not active:
        raise HTTPException(status_code=404, detail="No active drying batch")
    oven = await _oven_state(active.get("oven_session_id") or active["batch_id"])

    return {
        "batchId": active["batch_id"],
        "fishType": active["fish_type"],
        "initialWeightKg": active["initial_weight_kg"],
        "dryingStartedAt": active.get("drying_started_at"),
        "elapsedDryingHours": round(active_batch_store.elapsed_drying_hours(active), 2),
        "initialTemperatureC": active.get("initial_temperature_c"),
        "initialTotalHours": active.get("initial_total_hours"),
        # Id the oven session actually runs under (see active_batch_store).
        "ovenSessionId": active.get("oven_session_id") or active["batch_id"],
        # Ground truth from the oven — the countdown must not run when the
        # heater isn't actually on.
        "ovenRunning": oven["running"],
        "ovenStatus": oven["status"],
        "ovenReachable": oven["reachable"],
        "ovenStoppedReason": oven["reason"],
    }


@router.post("/stop", summary="Stop drying (clear the active batch)")
async def stop_drying():
    active = await active_batch_store.get_active_batch()
    await active_batch_store.clear_active_batch()
    if active and active.get("batch_id"):
        # Drop per-run state so a later batch cannot inherit this run's
        # elapsed over-drying timers or its explanations.
        overdrying_monitor_service.clear_state(active["batch_id"])
        llm_reasoning_service.clear_state(active["batch_id"])
    return {
        "message": "Drying stopped",
        "batchId": active.get("batch_id") if active else None,
    }


# ---------------------------------------------------------------------------
# Predictions for the active batch, using live sensor data
# ---------------------------------------------------------------------------
async def _require_active_batch() -> dict[str, Any]:
    active = await active_batch_store.get_active_batch()
    if not active:
        raise HTTPException(
            status_code=404,
            detail="No active drying batch. Call POST /api/drying/start first.",
        )
    return active


async def _require_active_and_sensors() -> tuple[dict[str, Any], dict[str, Any]]:
    active = await _require_active_batch()
    try:
        sensor = await fetch_live_reading()
    except SensorServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return active, sensor


# Oven session states that mean drying is NOT currently running.
_OVEN_NOT_RUNNING = {"STOPPED", "COMPLETED", "FAULT", "READY"}


async def _oven_state(batch_id: str) -> dict[str, Any]:
    """Ask the oven what is actually happening for this batch.

    The active-batch pointer here is only bookkeeping - it says which batch we
    *think* is drying. The oven is the source of truth for whether the heater
    is actually running, so the countdown must not be trusted without it.
    """
    try:
        reading = await fetch_live_reading()
    except Exception:
        return {"reachable": True, "running": True, "status": "DRYING", "reason": None}

    session = reading.get("session") or {}
    status = (session.get("status") or reading.get("drying_status") or "").upper() or None
    session_batch = session.get("batch_id")

    if status is None or not session_batch:
        return {"reachable": True, "running": True, "status": "DRYING", "reason": None}

    if session_batch != batch_id:
        return {
            "reachable": True,
            "running": True,
            "status": "DRYING",
            "reason": None,
        }

    running = status not in _OVEN_NOT_RUNNING
    reason = session.get("fault_reason") or session.get("stop_reason")
    return {
        "reachable": True,
        "running": running,
        "status": status,
        "reason": reason,
    }


def _seeded_drying_time_response(active: dict[str, Any], elapsed: float) -> DryingTimeResponse:
    total_hours = active.get("initial_total_hours")
    if total_hours is None or float(total_hours) <= 0:
        total_hours = 2.0
    remaining = max(0.05, float(total_hours) - elapsed)

    return DryingTimeResponse(
        batch_id=active["batch_id"],
        predicted_remaining_drying_time_hours=round(remaining, 2),
        model_used="SeededEstimate" if total_hours is not None else "Unavailable",
        created_at=datetime.now(timezone.utc),
        factors=[],
    )


@router.get(
    "/active/drying-time",
    response_model=DryingTimeResponse,
    summary="Predict remaining drying time for the active batch",
)
async def active_drying_time(
    service: DryingTimeService = Depends(get_drying_time_service),
):
    active = await _require_active_batch()
    elapsed = active_batch_store.elapsed_drying_hours(active)

    try:
        sensor = await fetch_live_reading()
    except SensorServiceUnavailableError:
        return _seeded_drying_time_response(active, elapsed)

    raw_weight = sensor.get("weight")
    if raw_weight is None or sensor.get("online") is False:
        # No usable weight reading (device offline / sensor not ready yet) —
        # do NOT treat a missing reading as "current weight is 0 kg".
        return _seeded_drying_time_response(active, elapsed)

    initial_weight = float(active["initial_weight_kg"])
    current_weight = _clamp(float(raw_weight), 0.0, initial_weight)

    weight_lost = max(0.0, initial_weight - current_weight)
    # Handover: seeded pre-drying estimate -> trained dynamic model.
    #
    # The dynamic model's strongest feature is the weight-loss rate, and that
    # rate is only trustworthy once BOTH conditions hold:
    #
    #   * enough time has passed that elapsed is large compared with the
    #     polling interval, so the division is not dominated by timing jitter;
    #   * enough mass has actually been lost to clear load-cell noise, so the
    #     numerator is signal rather than sensor drift.
    #
    # Time alone is not sufficient: a stalled or not-yet-heating oven can sit
    # for minutes having lost nothing, and dividing that nothing by a growing
    # elapsed time yields a confident-looking rate of ~0 that would tell the
    # operator drying will never finish.
    #
    # These oven runs last roughly 10-40 minutes total, so the thresholds are
    # deliberately small - a 30-minute warm-up gate would outlast most batches
    # and the dynamic model would never engage at all.
    MIN_ELAPSED_FOR_RATE = 3.0 / 60.0    # hours (3 minutes)
    MIN_WEIGHT_LOSS_KG = 0.003           # 3 g - above HX711 noise on this rig
    MAX_WEIGHT_LOSS_RATE = 5.0           # kg/hour
    rate_is_reliable = elapsed >= MIN_ELAPSED_FOR_RATE and weight_lost >= MIN_WEIGHT_LOSS_KG
    if rate_is_reliable:
        weight_loss_rate = min(weight_lost / elapsed, MAX_WEIGHT_LOSS_RATE)
    else:
        # No usable rate yet. Every estimator degrades into guesswork without
        # one - the rule-based fallback in particular divides by a floor rate
        # and returns an inflated time that contradicts the figure the
        # operator was shown before starting. Keep showing the pre-drying
        # estimate until the rate becomes observable.
        weight_loss_rate = 0.0
        if active.get("initial_total_hours") is not None:
            return _seeded_drying_time_response(active, elapsed)

    try:
        req = DryingTimeRequest(
            fish_type=active["fish_type"],
            initial_weight_kg=initial_weight,
            current_weight_kg=current_weight,
            temperature_c=_clamp(float(sensor.get("temperature") or 0.0), -10, 150),
            humidity_percent=_clamp(float(sensor.get("humidity") or 0.0), 0, 100),
            elapsed_drying_time_hours=_clamp(elapsed, 0, 240),
            weight_loss_rate=max(0.0, weight_loss_rate),
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid derived inputs: {exc}")

    predicted_hours, model_used = service.predict(req)
    created_at = datetime.now(timezone.utc)

    await _persist(
        build_prediction_record(
            batch_id=active["batch_id"],
            prediction_type="drying_time",
            inputs={**req.model_dump(), "source": "integrated", "sensor": sensor},
            predicted_drying_time_hours=predicted_hours,
            model_used=model_used,
        )
    )

    return DryingTimeResponse(
        batch_id=active["batch_id"],
        predicted_remaining_drying_time_hours=predicted_hours,
        model_used=model_used,
        created_at=created_at,
        factors=_drying_time_factors(req),
    )


@router.get(
    "/active/spoilage-risk",
    response_model=SpoilageRiskResponse,
    summary="Classify spoilage risk for the active batch",
)
async def active_spoilage_risk(
    service: SpoilageRiskService = Depends(get_spoilage_risk_service),
):
    active, sensor = await _require_active_and_sensors()

    if sensor.get("weight") is None or sensor.get("online") is False:
        # No usable reading yet — report unknown rather than fabricating a
        # "Low risk" result from zeroed-out sensor values.
        return SpoilageRiskResponse(
            batch_id=active["batch_id"],
            smell_level="Low",
            spoilage_risk="Low",
            model_used="Unavailable",
            created_at=datetime.now(timezone.utc),
            factors=[],
        )

    initial_weight = float(active["initial_weight_kg"])
    current_weight = _clamp(float(sensor.get("weight") or 0.0), 0.0, initial_weight)
    weight_lost = max(0.0, initial_weight - current_weight)
    weight_loss_pct = (weight_lost / initial_weight * 100.0) if initial_weight > 0 else 0.0
    elapsed = active_batch_store.elapsed_drying_hours(active)

    try:
        req = SpoilageRiskRequest(
            temperature_c=_clamp(float(sensor.get("temperature") or 0.0), -10, 150),
            humidity_percent=_clamp(float(sensor.get("humidity") or 0.0), 0, 100),
            elapsed_drying_time_hours=_clamp(elapsed, 0, 240),
            weight_loss_percentage=_clamp(weight_loss_pct, 0, 100),
            # Milan's `gas` field is the raw MQ-136 reading.
            mq136_value=_clamp(float(sensor.get("gas") or 0.0), 0, 4096),
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid derived inputs: {exc}")

    smell_level, risk, model_used = service.predict(req)
    created_at = datetime.now(timezone.utc)

    await _persist(
        build_prediction_record(
            batch_id=active["batch_id"],
            prediction_type="spoilage_risk",
            inputs={**req.model_dump(), "source": "integrated", "sensor": sensor},
            smell_level=smell_level,
            spoilage_risk=risk,
            model_used=model_used,
        )
    )

    return SpoilageRiskResponse(
        batch_id=active["batch_id"],
        smell_level=smell_level,
        spoilage_risk=risk,
        model_used=model_used,
        created_at=created_at,
        factors=_spoilage_factors(req, smell_level),
    )


# ---------------------------------------------------------------------------
# Over-drying / burn safety
#
# A separate risk axis from spoilage: spoilage is about a batch staying too
# wet for too long, this is about one that is already dry and still being
# heated. Kept as its own endpoint and its own field rather than folded into
# spoilage_risk, because the two failures call for opposite corrective
# actions and merging them would hide which one is happening.
# ---------------------------------------------------------------------------
@router.get(
    "/active/overdrying-risk",
    summary="Assess over-drying / burn risk for the active batch (and stop the oven if needed)",
)
async def active_overdrying_risk():
    """Evaluate over-drying risk and, at HIGH risk, stop the oven.

    The stop is the deterministic rule's decision, not the LLM's - the
    explanation is generated after the fact and never gates the action.
    """
    active, sensor = await _require_active_and_sensors()
    batch_id = active["batch_id"]
    # The oven session may run under a different id than the batch (see
    # active_batch_store), and the stop must target the oven's own id.
    oven_session_id = active.get("oven_session_id") or batch_id

    assessment = overdrying_monitor_service.evaluate(batch_id, sensor)

    stopped = False
    stop_error: str | None = None

    explanation = None
    if assessment["reasons"]:
        explanation = await asyncio.to_thread(
            llm_reasoning_service.explain,
            batch_id,
            "over-drying",
            assessment["risk"],
            assessment["reasons"],
            assessment["details"],
        )

    return {
        "batch_id": batch_id,
        "over_drying_risk": assessment["risk"],
        "reasons": assessment["reasons"],
        "details": assessment["details"],
        "oven_stopped": stopped,
        "stop_reason": assessment["stop_reason"] if stopped else None,
        "stop_error": stop_error,
        "explanation": explanation,
        "created_at": datetime.now(timezone.utc),
    }


@router.get(
    "/active/reasoning",
    summary="Plain-language LLM explanations generated for the active batch",
)
async def active_reasoning():
    """Advisory only. An empty list never means nothing happened - the
    authoritative state is on the risk endpoints themselves."""
    active = await _require_active_batch()
    return {
        "batch_id": active["batch_id"],
        "reasoning": llm_reasoning_service.get_explanations(active["batch_id"]),
    }
