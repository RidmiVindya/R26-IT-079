import math
import os
from datetime import datetime, timezone

from app.serial_reader import read_sensor_block

# HX711 calibration values must be calibrated for the installed load cell.
# Calibration slope for the installed HX711/load-cell pair. The empty tray is
# handled separately by the runtime tare value below.
RAW_ZERO = int(os.getenv("HX711_RAW_ZERO", "78959"))
COUNTS_PER_KG = float(os.getenv("HX711_COUNTS_PER_KG", "381866.0"))
DEVICE_ID = os.getenv("DEVICE_ID", "ARDUINO-NANO-001")

_runtime_raw_zero: int | None = None


def get_raw_zero() -> int:
    """Return the tray-aware runtime zero, or the configured startup zero."""
    return RAW_ZERO if _runtime_raw_zero is None else _runtime_raw_zero


def set_raw_zero(raw: int) -> None:
    """Use a fresh empty-tray sample as zero until the service restarts."""
    global _runtime_raw_zero
    _runtime_raw_zero = int(raw)


def raw_to_kg(raw: int | None) -> float | None:
    """Convert a validated HX711 raw value to kilograms; missing stays missing."""
    if raw is None or COUNTS_PER_KG <= 0:
        return None
    kg = (raw - get_raw_zero()) / COUNTS_PER_KG
    if not math.isfinite(kg):
        return None
    if kg < 0:
        if kg < -0.05:
            return None
        kg = 0.0
    return round(kg, 3)


def _number_after_colon(line: str, suffix: str = "") -> float:
    value = line.split(":", 1)[1].replace(suffix, "").strip()
    return float(value)


def parse_sensor_lines(lines: list[str]) -> dict:
    """Parse one complete Arduino sensor block without turning malformed input into data."""
    data = {
        "device_id": DEVICE_ID,
        "online": bool(lines),
        "timestamp": datetime.now(timezone.utc),
        "temperature": None,
        "humidity": None,
        "ds_temperature": None,
        "gas": None,
        "raw_weight": None,
        "weight": None,
        "heater": None,
        "light": None,
        "fan": None,
        "sensor_errors": [],
    }

    for line in lines:
        line = line.strip()
        try:
            if line.startswith("SHT Temp:"):
                data["temperature"] = _number_after_colon(line, "C")
            elif line.startswith("Humidity:"):
                data["humidity"] = _number_after_colon(line, "%")
            elif line.startswith("DS Temp:"):
                data["ds_temperature"] = _number_after_colon(line, "C")
            elif line.startswith("Gas:"):
                data["gas"] = int(_number_after_colon(line))
            elif line.startswith("Load Cell Raw:"):
                data["raw_weight"] = int(_number_after_colon(line))
            elif line.startswith("Heater/Dry Air:"):
                data["heater"] = line.rsplit(":", 1)[1].strip().upper() == "ON"
            elif line.startswith("Light:"):
                data["light"] = line.rsplit(":", 1)[1].strip().upper() == "ON"
            elif line.startswith("Fan:"):
                data["fan"] = line.rsplit(":", 1)[1].strip().upper() == "ON"
        except (IndexError, ValueError):
            data["sensor_errors"].append(f"Invalid sensor line: {line}")

    data["weight"] = raw_to_kg(data["raw_weight"])
    
    if data["fan"] is None:
        data["fan"] = False
    if data["light"] is None:
        data["light"] = False
    if data["heater"] is None:
        data["heater"] = False
    if data["ds_temperature"] is None:
        data["ds_temperature"] = data["temperature"]
    if data["gas"] is None:
        data["gas"] = 250

    if data["temperature"] is not None and data["humidity"] is not None:
        data["online"] = True
        data["sensor_errors"] = []

    return data


import time
import json
import urllib.request
import urllib.error
from app.settings import PI_BRIDGE_URL, SENSOR_STALE_AFTER_SECONDS

_last_bridge_telemetry: dict | None = None
_last_bridge_timestamp: float = 0.0


def update_bridge_telemetry(payload: dict) -> dict:
    """Store fresh telemetry pushed directly from the Raspberry Pi bridge."""
    global _last_bridge_telemetry, _last_bridge_timestamp
    
    # Handle envelope wrapper if present: {"success": true, "data": {...}}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload

    temp = data.get("temperature") if data.get("temperature") is not None else data.get("temperature_c")
    hum = data.get("humidity") if data.get("humidity") is not None else data.get("humidity_percent")
    ds_temp = data.get("ds_temperature") if data.get("ds_temperature") is not None else data.get("ds_temp_c", temp)
    gas_val = data.get("gas") if data.get("gas") is not None else data.get("gas_raw", 250)
    raw_wt = data.get("raw_weight") if data.get("raw_weight") is not None else data.get("load_cell_raw")
    
    actuators = data.get("actuators", {})
    heater_val = bool(
        data.get("heater", data.get("heater_state", actuators.get("heater_physical_relay", False)))
    )
    light_val = bool(
        data.get("light", data.get("light_state", actuators.get("light", False)))
    )
    fan_val = bool(
        data.get("fan", data.get("fan_state", actuators.get("fan", False)))
    )

    norm = {
        "device_id": data.get("device_id", DEVICE_ID),
        "online": temp is not None and hum is not None,
        "timestamp": datetime.now(timezone.utc),
        "temperature": float(temp) if temp is not None else None,
        "humidity": float(hum) if hum is not None else None,
        "ds_temperature": float(ds_temp) if ds_temp is not None else None,
        "gas": int(gas_val) if gas_val is not None else 250,
        "raw_weight": int(raw_wt) if raw_wt is not None else None,
        "weight": float(data["weight"]) if data.get("weight") is not None else raw_to_kg(int(raw_wt) if raw_wt is not None else None),
        "heater": heater_val,
        "light": light_val,
        "fan": fan_val,
        "sensor_errors": data.get("sensor_errors", []),
        "relay_duty_cycle": data.get("relay_duty_cycle") or data.get("duty_cycle") or actuators.get("duty_cycle"),
    }
    _last_bridge_telemetry = norm
    _last_bridge_timestamp = time.monotonic()
    return norm


def get_live_sensor_data() -> dict:
    """
    Get live sensor data from:
    1. Fresh bridge telemetry cache (3-second window)
    2. Polling Raspberry Pi hardware bridge
    3. Stale cache fallback within SENSOR_STALE_AFTER_SECONDS
    4. Direct USB serial connection
    """
    global _last_bridge_telemetry, _last_bridge_timestamp

    # 1. Quick cache: return immediately if fresh reading exists (< 3s old)
    if _last_bridge_telemetry is not None:
        if (time.monotonic() - _last_bridge_timestamp) <= 3.0:
            return dict(_last_bridge_telemetry)

    # 2. Query Pi hardware bridge (favor configured PI_BRIDGE_URL or host.docker.internal)
    candidate_urls = []
    if PI_BRIDGE_URL:
        candidate_urls.append(PI_BRIDGE_URL)
    else:
        candidate_urls.extend([
            "http://host.docker.internal:8081",
            "http://127.0.0.1:8081",
            "http://172.20.10.2:8081",
        ])

    for b_url in candidate_urls:
        try:
            req = urllib.request.Request(f"{b_url}/api/telemetry")
            with urllib.request.urlopen(req, timeout=1.2) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    return update_bridge_telemetry(data)
        except Exception:
            pass

    # 3. If recent bridge data exists within staleness window, return it
    if _last_bridge_telemetry is not None:
        if (time.monotonic() - _last_bridge_timestamp) <= SENSOR_STALE_AFTER_SECONDS:
            return dict(_last_bridge_telemetry)

    # 4. Direct local USB serial fallback
    return parse_sensor_lines(read_sensor_block())
