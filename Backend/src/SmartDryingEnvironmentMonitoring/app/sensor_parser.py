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
        # HX711 electrical noise on an empty/resting scale jitters a few
        # hundred counts around the true zero. A small negative delta is
        # still "empty", not an invalid reading; only reject a delta too
        # large to be noise.
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
    
    # Normalize payload into standard reading structure
    norm = {
        "device_id": payload.get("device_id", DEVICE_ID),
        "online": True,
        "timestamp": datetime.now(timezone.utc),
        "temperature": float(payload["temperature"]) if payload.get("temperature") is not None else None,
        "humidity": float(payload["humidity"]) if payload.get("humidity") is not None else None,
        "ds_temperature": float(payload.get("ds_temperature", payload.get("temperature", 30.0))),
        "gas": int(payload.get("gas", 250)),
        "raw_weight": payload.get("raw_weight"),
        "weight": payload.get("weight") if payload.get("weight") is not None else raw_to_kg(payload.get("raw_weight")),
        "heater": bool(payload.get("heater", payload.get("actuators", {}).get("heater_physical_relay", False))),
        "light": bool(payload.get("light", payload.get("actuators", {}).get("light", False))),
        "fan": bool(payload.get("fan", payload.get("actuators", {}).get("fan", False))),
        "sensor_errors": payload.get("sensor_errors", []),
        "relay_duty_cycle": payload.get("relay_duty_cycle") or payload.get("actuators", {}).get("duty_cycle"),
    }
    _last_bridge_telemetry = norm
    _last_bridge_timestamp = time.monotonic()
    return norm


def get_live_sensor_data() -> dict:
    """
    Get live sensor data from:
    1. Fresh pushed Raspberry Pi bridge data (within staleness window)
    2. Polling Raspberry Pi bridge if PI_BRIDGE_URL is set
    3. Direct USB serial connection (fallback)
    """
    global _last_bridge_telemetry, _last_bridge_timestamp

    # 1. Use fresh pushed telemetry from Pi if available
    if _last_bridge_telemetry is not None:
        if (time.monotonic() - _last_bridge_timestamp) <= SENSOR_STALE_AFTER_SECONDS:
            return dict(_last_bridge_telemetry)

    # 2. If PI_BRIDGE_URL is configured, query the Pi HTTP endpoint directly
    if PI_BRIDGE_URL:
        try:
            req = urllib.request.Request(f"{PI_BRIDGE_URL}/api/telemetry")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    return update_bridge_telemetry(data)
        except Exception:
            pass

    # 3. Direct local USB serial fallback
    return parse_sensor_lines(read_sensor_block())


