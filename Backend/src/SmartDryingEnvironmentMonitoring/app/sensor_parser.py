import math
import os
from datetime import datetime, timezone

from app.serial_reader import read_sensor_block

# HX711 calibration values must be calibrated for the installed load cell.
RAW_ZERO = int(os.getenv("HX711_RAW_ZERO", "78959"))
COUNTS_PER_KG = float(os.getenv("HX711_COUNTS_PER_KG", "194650.0"))
DEVICE_ID = os.getenv("DEVICE_ID", "ARDUINO-NANO-001")


def raw_to_kg(raw: int | None) -> float | None:
    """Convert a validated HX711 raw value to kilograms; missing stays missing."""
    if raw is None or COUNTS_PER_KG <= 0:
        return None
    kg = (raw - RAW_ZERO) / COUNTS_PER_KG
    if not math.isfinite(kg) or kg < 0:
        return None
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
        try:
            if "SHT Temp:" in line:
                data["temperature"] = _number_after_colon(line, "C")
            elif "Humidity:" in line:
                data["humidity"] = _number_after_colon(line, "%")
            elif "DS Temp:" in line:
                data["ds_temperature"] = _number_after_colon(line, "C")
            elif "Gas:" in line:
                data["gas"] = int(line.split(":", 1)[1].strip())
            elif "Load Cell Raw:" in line:
                raw = int(line.split(":", 1)[1].strip())
                data["raw_weight"] = raw
                data["weight"] = raw_to_kg(raw)
            elif "Heater/Dry Air:" in line:
                data["heater"] = line.split(":", 1)[1].strip().upper() == "ON"
            elif "Light:" in line:
                data["light"] = line.split(":", 1)[1].strip().upper() == "ON"
            elif "Fan:" in line:
                data["fan"] = line.split(":", 1)[1].strip().upper() == "ON"
        except (IndexError, TypeError, ValueError) as exc:
            data["sensor_errors"].append({"line": line, "error": str(exc)})

    if data["temperature"] is not None and not math.isfinite(data["temperature"]):
        data["temperature"] = None
        data["sensor_errors"].append({"field": "temperature", "error": "not finite"})
    if data["humidity"] is not None and not 0 <= data["humidity"] <= 100:
        data["humidity"] = None
        data["sensor_errors"].append({"field": "humidity", "error": "outside 0..100"})
    return data


def get_live_sensor_data() -> dict:
    return parse_sensor_lines(read_sensor_block())
