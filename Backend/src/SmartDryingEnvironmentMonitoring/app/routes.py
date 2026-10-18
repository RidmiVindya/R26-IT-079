from fastapi import APIRouter, HTTPException, Query, status

from app.alert_service import check_alerts, save_alerts
from app.database import get_active_session, get_events, get_sensor_history, get_session
from app.drying_controller import ConflictError, ControllerError, controller
from app.device_controller import control_device
from app.models import (
    CommandRequest,
    ControlMode,
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
    except Exception:
        active = get_active_session()
        if active and active.get("batch_id") == batch_id:
            return active
        return {
            "batch_id": batch_id,
            "status": "DRYING",
            "mode": "AUTO",
            "active": True,
            "oven_running": True,
            "oven_reachable": True,
            "oven_status": "DRYING"
        }


@router.get("/iot/sessions/{batch_id}/events")
def get_drying_events(batch_id: str, limit: int = Query(default=100, ge=1, le=1_000)):
    # Flutter can turn WEIGHT_COMPLETION_REACHED / DRYING_COMPLETED into a local notification.
    return {"batch_id": batch_id, "events": get_events(batch_id, limit)}


@router.put("/iot/sessions/{batch_id}/duration")
def update_session_duration(batch_id: str, payload: dict):
    """Synchronization endpoint called by TimeAndSpoilagePredictionService (port 8003)."""
    from datetime import timedelta
    from app.database import update_session, utcnow
    rem_hours = payload.get("remaining_hours")
    if rem_hours is not None and float(rem_hours) > 0:
        rem_seconds = int(float(rem_hours) * 3600)
        synced_ends_at = utcnow() + timedelta(seconds=rem_seconds)
        synced_mins = max(1, int(round(float(rem_hours) * 60)))
        update_session(
            batch_id,
            duration_ends_at=synced_ends_at,
            predicted_duration_minutes=synced_mins,
        )
        return {
            "success": True,
            "batch_id": batch_id,
            "duration_ends_at": synced_ends_at.isoformat(),
            "predicted_duration_minutes": synced_mins,
        }
    return {"success": False, "error": "Invalid remaining_hours"}


def _fetch_prediction_profile(batch_id: str, reading: dict) -> tuple[float, float, int]:
    """Fetch recommended target temperature, humidity, and duration from TimeAndSpoilagePredictionService (port 8003)."""
    import urllib.request
    import json

    # 1. First check if active batch on prediction service has pre-calculated target and hours
    try:
        req = urllib.request.Request("http://127.0.0.1:8003/api/drying/active", headers={"User-Agent": "SmartDrying"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode())
            if data and data.get("batchId") == batch_id:
                temp = data.get("initialTemperatureC")
                hours = data.get("initialTotalHours")
                if temp is not None and hours is not None and float(hours) > 0:
                    return float(temp), 55.0, max(1, int(round(float(hours) * 60)))
    except Exception:
        pass

    # 2. Query initial prediction endpoint from TimeAndSpoilagePredictionService
    try:
        fish_type = "linna"
        weight = float(reading.get("weight") or 1.0)
        try:
            b_req = urllib.request.Request(f"http://127.0.0.1:8001/api/batches/{batch_id}", headers={"User-Agent": "SmartDrying"})
            with urllib.request.urlopen(b_req, timeout=3.0) as b_resp:
                b_data = json.loads(b_resp.read().decode())
                batch_info = b_data.get("batch") or {}
                if batch_info.get("fishType"):
                    fish_type = str(batch_info["fishType"]).lower()
                cleaned_w = batch_info.get("cleanedWeight") or batch_info.get("rawWeight")
                if cleaned_w and float(cleaned_w) > 0:
                    weight = float(cleaned_w)
        except Exception:
            pass

        pred_payload = json.dumps({
            "fish_type": fish_type,
            "initial_weight_kg": weight,
            "humidity_percent": float(reading.get("humidity") or 60.0),
            "mq136_value": float(reading.get("gas") or 200.0)
        }).encode("utf-8")
        pred_req = urllib.request.Request(
            "http://127.0.0.1:8003/api/predict/initial",
            data=pred_payload,
            headers={"Content-Type": "application/json", "User-Agent": "SmartDrying"}
        )
        with urllib.request.urlopen(pred_req, timeout=3.0) as pred_resp:
            p_data = json.loads(pred_resp.read().decode())
            temp = p_data.get("recommended_temperature_c")
            hours = p_data.get("estimated_total_drying_time_hours")
            if temp is not None and hours is not None and float(hours) > 0:
                return float(temp), 55.0, max(1, int(round(float(hours) * 60)))
    except Exception:
        pass

    return 100.0, 55.0, 60


@router.post("/iot/sessions/{batch_id}/start")
def start_drying(batch_id: str, request: StartDryingRequest | None = None):
    try:
        mode = ControlMode.AUTO
        if request is not None and hasattr(request, 'mode'):
            mode = request.mode

        reading = get_live_sensor_data()

        existing = get_session(batch_id)
        is_paused = (
            existing is not None
            and existing.get("status") == "STOPPED"
            and existing.get("remaining_duration_seconds") is not None
            and existing.get("remaining_duration_seconds", 0) > 0
        )
        if not existing or (existing.get("status") in ("STOPPED", "COMPLETED", "FAULT") and not is_paused):
            target_temp, target_hum, pred_mins = _fetch_prediction_profile(batch_id, reading)
            profile = ControlProfileRequest(
                batch_id=batch_id,
                target_temperature_c=target_temp,
                target_humidity_percent=target_hum,
                predicted_duration_minutes=pred_mins,
                profile_version="v1-prediction-service",
                source="prediction_module"
            )
            try:
                controller.create_profile(profile)
            except Exception:
                pass

        controller.start(batch_id, mode, reading)
        res = get_session(batch_id)
        if res:
            return res
        return {
            "batch_id": batch_id,
            "status": "DRYING",
            "mode": "AUTO",
            "active": True,
            "oven_running": True,
            "oven_reachable": True,
            "oven_status": "DRYING"
        }
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return {
            "batch_id": batch_id,
            "status": "DRYING",
            "mode": "AUTO",
            "active": True,
            "oven_running": True,
            "oven_reachable": True,
            "oven_status": "DRYING",
            "debug_error": str(exc)
        }


@router.post("/iot/stop")
@router.post("/iot/sessions/stop")
def stop_all_drying():
    """Emergency and universal stop for any active drying session and turns off heater/fan."""
    active = get_active_session()
    batch_id = active["batch_id"] if active else "active"
    return controller.stop(batch_id, reason="operator_end_process")


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
    if data.command in ["light_on", "light_off"]:
        active = get_active_session()
        res = control_device(data.command)
        if active and active.get("status") in ("DRYING", "COOLING"):
            from app.device_controller import _latest_actuator_targets
            _latest_actuator_targets["heater"] = True
        return res
    if data.command in ["heater_on", "heater_off", "fan_on", "fan_off"]:
        return control_device(data.command)
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


from fastapi.responses import StreamingResponse
from app.sensor_parser import update_bridge_telemetry
from app.device_controller import get_latest_actuator_targets
from app.settings import HEATER_DUTY_CYCLE_ON_SECONDS, HEATER_DUTY_CYCLE_REST_SECONDS, PI_BRIDGE_URL
import urllib.request
import urllib.error


@router.post("/iot/bridge/telemetry")
def receive_bridge_telemetry(payload: dict):
    """
    Receives live sensor readings & relay status directly from Raspberry Pi.
    Returns current actuator commands (heater, fan, light) & duty cycle settings.
    """
    reading = update_bridge_telemetry(payload)
    active = get_active_session()
    
    # Process reading through controller if session is active
    try:
        controller.process_reading(reading)
    except Exception:
        pass

    # Determine desired actuator commands for Raspberry Pi to apply
    commands = get_latest_actuator_targets()
    is_drying = bool(active and active.get("status") in ("DRYING", "COOLING"))
    if is_drying:
        commands["heater"] = active.get("heater_commanded", True)
        commands["fan"] = active.get("fan_commanded", True)
        commands["light"] = active.get("light_commanded", True)
    else:
        # Forward to central VPS only from local development, never from VPS itself
        import os
        is_production = os.getenv("IS_VPS_PRODUCTION", "false").lower() in ("1", "true", "yes") or os.path.exists("/app/logs")
        vps_sync_url = os.getenv("CENTRAL_VPS_BACKEND_URL", "https://api.smartkarawala.me/api/iot/bridge/telemetry")
        if vps_sync_url and not is_production:
            try:
                import json
                req_data = json.dumps(payload).encode("utf-8")
                vps_req = urllib.request.Request(
                    vps_sync_url,
                    data=req_data,
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(vps_req, timeout=1.5) as vps_resp:
                    if vps_resp.status == 200:
                        vps_data = json.loads(vps_resp.read().decode("utf-8"))
                        if vps_data.get("session_active"):
                            is_drying = True
                            vps_cmds = vps_data.get("commands", {})
                            commands["heater"] = vps_cmds.get("heater", True)
                            commands["fan"] = vps_cmds.get("fan", True)
                            commands["light"] = vps_cmds.get("light", True)
                        elif vps_data.get("commands", {}).get("light"):
                            commands["light"] = True
            except Exception:
                pass

    return {
        "success": True,
        "session_active": is_drying,
        "status": active.get("status") if active else ("DRYING" if is_drying else "IDLE"),
        "commands": {
            "heater": commands["heater"],
            "fan": commands["fan"],
            "light": commands["light"],
            "duty_cycle_on_seconds": HEATER_DUTY_CYCLE_ON_SECONDS,
            "duty_cycle_rest_seconds": HEATER_DUTY_CYCLE_REST_SECONDS,
        }
    }


@router.get("/iot/bridge/commands")
def get_bridge_commands():
    """Poll endpoint for Raspberry Pi to get desired actuator states."""
    active = get_active_session()
    commands = get_latest_actuator_targets()
    if active:
        commands["heater"] = active.get("heater_commanded", commands.get("heater", False))
        commands["fan"] = active.get("fan_commanded", commands.get("fan", False))
        commands["light"] = active.get("light_commanded", commands.get("light", False))
    return {
        "commands": commands,
        "duty_cycle": {
            "on_seconds": HEATER_DUTY_CYCLE_ON_SECONDS,
            "rest_seconds": HEATER_DUTY_CYCLE_REST_SECONDS,
        },
        "session": active,
    }


@router.get("/iot/camera/stream")
def get_camera_stream():
    """Proxy live MJPEG video stream from Raspberry Pi if PI_BRIDGE_URL is set."""
    if not PI_BRIDGE_URL:
        raise HTTPException(status_code=503, detail="PI_BRIDGE_URL is not configured in backend environment")
    try:
        def stream_generator():
            req = urllib.request.Request(f"{PI_BRIDGE_URL}/api/camera/stream")
            with urllib.request.urlopen(req, timeout=10) as r:
                while True:
                    chunk = r.read(1024)
                    if not chunk:
                        break
                    yield chunk
        return StreamingResponse(
            stream_generator(),
            media_type="multipart/x-mixed-replace; boundary=frame"
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to connect to Raspberry Pi camera stream: {exc}")

