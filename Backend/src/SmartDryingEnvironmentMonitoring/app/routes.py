from fastapi import APIRouter, HTTPException, Query, status

from app.alert_service import check_alerts, save_alerts
from app.database import get_active_session, get_events, get_sensor_history
from app.drying_controller import ConflictError, ControllerError, controller
from app.models import (
    CommandRequest,
    ControlProfileRequest,
    ManualActuatorRequest,
    SetModeRequest,
    StartDryingRequest,
    TareRequest,
)
from app.sensor_parser import get_live_sensor_data, raw_to_kg, set_raw_zero
from app.serial_reader import read_sensor_block

router = APIRouter()


def _controller_http_error(exc: ControllerError) -> HTTPException:
    code = status.HTTP_409_CONFLICT if isinstance(exc, ConflictError) else status.HTTP_422_UNPROCESSABLE_ENTITY
    return HTTPException(status_code=code, detail=str(exc))


@router.get("/iot/live")
def get_live_data():
    """Read, validate, persist, and—when AUTO is active—control from one sensor sample."""
    try:
        data = controller.process_reading(get_live_sensor_data())
    except ControllerError as exc:
        raise _controller_http_error(exc)
    active = get_active_session()
    # Keep the original reading fields at the top level for existing dashboard clients.
    response = {**data, "session": active}
    if active:
        response["target_temperature"] = active["target_temperature_c"]
        response["target_humidity"] = active["target_humidity_percent"]
        response["drying_status"] = active["status"]
        response["mode"] = active["mode"]
        initial = active.get("initial_weight_kg")
        completion = active.get("completion_weight_kg")
        current = data.get("weight")
        if all(isinstance(value, (int, float)) for value in (initial, completion, current)) and initial > completion:
            response["progress"] = round(max(0, min(100, (initial - current) / (initial - completion) * 100)), 1)
        else:
            response["progress"] = None
    else:
        response.update({
            "target_temperature": None,
            "target_humidity": None,
            "drying_status": None,
            "mode": None,
            "progress": None,
        })
    return response


@router.get("/iot/raw")
def get_raw_sensor_data():
    return {"raw_data": read_sensor_block()}


@router.post("/iot/control-profiles", status_code=status.HTTP_201_CREATED)
def receive_control_profile(profile: ControlProfileRequest):
    """Integration point for Ridmi's parameter/prediction module."""
    try:
        return controller.create_profile(profile)
    except ControllerError as exc:
        raise _controller_http_error(exc)


@router.get("/iot/sessions/{batch_id}")
def get_drying_session(batch_id: str):
    try:
        return controller.get_session(batch_id)
    except ControllerError as exc:
        raise _controller_http_error(exc)


@router.get("/iot/sessions/{batch_id}/events")
def get_drying_events(batch_id: str, limit: int = Query(default=100, ge=1, le=1_000)):
    # Flutter can turn WEIGHT_COMPLETION_REACHED / DRYING_COMPLETED into a local notification.
    return {"batch_id": batch_id, "events": get_events(batch_id, limit)}


@router.post("/iot/sessions/{batch_id}/start")
def start_drying(batch_id: str, request: StartDryingRequest):
    reading = controller.process_reading(get_live_sensor_data())
    try:
        return controller.start(batch_id, request.mode, reading)
    except ControllerError as exc:
        raise _controller_http_error(exc)


@router.post("/iot/sessions/{batch_id}/stop")
def stop_drying(batch_id: str):
    try:
        return controller.stop(batch_id)
    except ControllerError as exc:
        raise _controller_http_error(exc)


@router.put("/iot/sessions/{batch_id}/mode")
def set_drying_mode(batch_id: str, request: SetModeRequest):
    try:
        return controller.set_mode(batch_id, request.mode)
    except ControllerError as exc:
        raise _controller_http_error(exc)


@router.put("/iot/sessions/{batch_id}/manual-actuators")
def set_manual_actuators(batch_id: str, request: ManualActuatorRequest):
    try:
        return controller.manual_actuators(batch_id, request.heater, request.fan, request.light)
    except ControllerError as exc:
        raise _controller_http_error(exc)


@router.post("/iot/tare")
def tare_scale(request: TareRequest):
    try:
        result = controller.tare(request.batch_id)
        # Capture the empty tray after the firmware tare command. This works
        # whether firmware reports absolute HX711 counts or tare-relative
        # counts, and keeps the backend conversion aligned with the device.
        reading = get_live_sensor_data()
        raw = reading.get("raw_weight")
        if not isinstance(raw, int):
            raise ControllerError(
                "Tare command was sent, but no valid load-cell reading was received"
            )
        set_raw_zero(raw)
        result.update({
            "raw_zero": raw,
            "weight": raw_to_kg(raw),
            "verified": True,
        })
        return result
    except ControllerError as exc:
        raise _controller_http_error(exc)


@router.get("/iot/readings")
def get_readings(
    batch_id: str | None = None,
    limit: int = Query(default=300, ge=1, le=2_000),
):
    return {"batch_id": batch_id, "readings": get_sensor_history(batch_id, limit)}


@router.post("/iot/save-reading")
def save_live_sensor_reading():
    """Compatibility endpoint; readings are already persisted by the controller."""
    try:
        data = controller.process_reading(get_live_sensor_data())
    except ControllerError as exc:
        raise _controller_http_error(exc)
    return {"success": True, "message": "Sensor reading saved", "data": data}


@router.get("/iot/alerts/check")
def check_current_alerts():
    try:
        data = controller.process_reading(get_live_sensor_data())
    except ControllerError as exc:
        raise _controller_http_error(exc)
    active = get_active_session()
    alerts = check_alerts(data)
    saved_ids = save_alerts(alerts, data["device_id"], active["batch_id"] if active else None)
    return {"sensor_data": data, "alert_count": len(alerts), "alerts": alerts, "saved_alert_ids": saved_ids}


@router.post("/iot/command", deprecated=True)
def legacy_iot_command(data: CommandRequest):
    """Temporary bridge for old clients; actuator calls must use a MANUAL session."""
    if data.command == "tare":
        return tare_scale(TareRequest())
    active = get_active_session()
    if not active:
        raise HTTPException(status_code=409, detail="Create and start a MANUAL drying session before commanding actuators")
    mapping = {
        "heater_on": {"heater": True}, "heater_off": {"heater": False},
        "fan_on": {"fan": True}, "fan_off": {"fan": False},
    }
    if data.command not in mapping:
        raise HTTPException(status_code=422, detail="Unsupported legacy command; use session APIs")
    try:
        values = mapping[data.command]
        return controller.manual_actuators(active["batch_id"], values.get("heater"), values.get("fan"))
    except ControllerError as exc:
        raise _controller_http_error(exc)
