import math
import os
from datetime import datetime, timezone

from app.serial_reader import read_sensor_block

# HX711 calibration values must be calibrated for the installed load cell.
# A 500 g reference produced 1.000 kg with the previous 194650 default, so the
# corrected slope is twice that value. Both settings remain environment
# overrides because every HX711/load-cell pair needs its own final calibration.
RAW_ZERO = int(os.getenv("HX711_RAW_ZERO", "78959"))
COUNTS_PER_KG = float(os.getenv("HX711_COUNTS_PER_KG", "389300.0"))
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
    required_fields = (
        "temperature",
        "humidity",
        "ds_temperature",
        "gas",
        "raw_weight",
        "weight",
        "heater",
        "light",
        "fan",
    )
    for field in required_fields:
        if data[field] is None:
            data["sensor_errors"].append(f"Missing sensor value: {field}")

    return data


def get_live_sensor_data() -> dict:
    return parse_sensor_lines(read_sensor_block())

