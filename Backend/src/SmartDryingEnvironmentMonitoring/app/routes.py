from fastapi import APIRouter
from app.sensor_parser import get_live_sensor_data
from app.models import CommandRequest
from app.device_controller import control_device
from app.database import save_sensor_log
from app.alert_service import check_alerts, save_alerts
router = APIRouter()


@router.get("/iot/live")
def get_live_data():
    return get_live_sensor_data()


@router.post("/iot/command")
def send_iot_command(data: CommandRequest):
    return control_device(data.command)


@router.post("/iot/save-reading")
def save_live_sensor_reading():
    data = get_live_sensor_data()
    inserted_id = save_sensor_log(data)

    return {
        "success": True,
        "message": "Sensor reading saved successfully",
        "inserted_id": inserted_id,
        "data": data
    }
    
@router.get("/iot/alerts/check")
def check_current_alerts():
    data = get_live_sensor_data()
    alerts = check_alerts(data)
    saved_ids = save_alerts(alerts)

    return {
        "sensor_data": data,
        "alert_count": len(alerts),
        "alerts": alerts,
        "saved_alert_ids": saved_ids
    }