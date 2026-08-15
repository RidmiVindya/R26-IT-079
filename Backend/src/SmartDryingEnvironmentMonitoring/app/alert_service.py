import os
from datetime import datetime, timedelta, timezone

from app.database import save_alert_records

HIGH_HUMIDITY_ALERT_PERCENT = float(os.getenv("HIGH_HUMIDITY_ALERT_PERCENT", "70"))
HIGH_TEMPERATURE_ALERT_C = float(os.getenv("HIGH_TEMPERATURE_ALERT_C", "50"))
HIGH_GAS_ALERT_VALUE = int(os.getenv("HIGH_GAS_ALERT_VALUE", "300"))
_last_alert_at: dict[tuple[str, str], datetime] = {}
_DEDUPLICATION_WINDOW = timedelta(minutes=5)


def check_alerts(data: dict) -> list[dict]:
    alerts = []
    temperature = data.get("temperature")
    humidity = data.get("humidity")
    gas = data.get("gas")

    if humidity is not None and humidity > HIGH_HUMIDITY_ALERT_PERCENT:
        alerts.append({"type": "HIGH_HUMIDITY", "message": "Humidity is above the configured alert threshold", "value": humidity, "priority": "HIGH"})
    if temperature is not None and temperature > HIGH_TEMPERATURE_ALERT_C:
        alerts.append({"type": "HIGH_TEMPERATURE", "message": "Temperature is above the configured alert threshold", "value": temperature, "priority": "HIGH"})
    if gas is not None and gas > HIGH_GAS_ALERT_VALUE:
        alerts.append({"type": "GAS_WARNING", "message": "Gas level is above the configured alert threshold", "value": gas, "priority": "MEDIUM"})
    return alerts


def save_alerts(alerts: list[dict], device_id: str, batch_id: str | None = None) -> list[str]:
    now = datetime.now(timezone.utc)
    new_alerts = []
    for alert in alerts:
        key = (device_id, alert["type"])
        if now - _last_alert_at.get(key, datetime.min.replace(tzinfo=timezone.utc)) < _DEDUPLICATION_WINDOW:
            continue
        _last_alert_at[key] = now
        new_alerts.append({**alert, "device_id": device_id, "batch_id": batch_id, "status": "ACTIVE"})
    return save_alert_records(new_alerts)
