from datetime import datetime, timezone
from app.database import db

alert_collection = db["drying_alert_logs"]


def check_alerts(data: dict):
    alerts = []

    temperature = data.get("temperature")
    humidity = data.get("humidity")
    gas = data.get("gas")

    if humidity is not None and humidity > 70:
        alerts.append({
            "type": "HIGH_HUMIDITY",
            "message": "Humidity is above safe drying level",
            "value": humidity,
            "priority": "HIGH"
        })

    if temperature is not None and temperature > 50:
        alerts.append({
            "type": "HIGH_TEMPERATURE",
            "message": "Temperature is above safe drying level",
            "value": temperature,
            "priority": "HIGH"
        })

    if gas is not None and gas > 300:
        alerts.append({
            "type": "GAS_WARNING",
            "message": "Gas level is above normal range",
            "value": gas,
            "priority": "MEDIUM"
        })

    return alerts


def save_alerts(alerts: list):
    saved_ids = []

    for alert in alerts:
        alert_to_save = {
            **alert,
            "device_id": "ARDUINO-NANO-001",
            "batch_id": "BATCH-TEST-001",
            "status": "ACTIVE",
            "timestamp": datetime.now(timezone.utc)
        }

        result = alert_collection.insert_one(alert_to_save)
        saved_ids.append(str(result.inserted_id))

    return saved_ids