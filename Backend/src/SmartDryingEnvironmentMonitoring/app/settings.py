import os


def _float_setting(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _int_setting(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


# These are operational defaults, not fish-specific drying recommendations.
TEMPERATURE_TOLERANCE_C = _float_setting("TEMPERATURE_TOLERANCE_C", 2.0)
HUMIDITY_TOLERANCE_PERCENT = _float_setting("HUMIDITY_TOLERANCE_PERCENT", 3.0)
# A MANUAL run still protects the product/equipment by removing heat at the
# operator-selected temperature target. Set to 0 for an exact target cutoff.
MANUAL_HEATER_CUTOFF_MARGIN_C = _float_setting("MANUAL_HEATER_CUTOFF_MARGIN_C", 0.0)
SENSOR_READ_TIMEOUT_SECONDS = _float_setting("SENSOR_READ_TIMEOUT_SECONDS", 3.0)
SENSOR_SAVE_INTERVAL_SECONDS = _int_setting("SENSOR_SAVE_INTERVAL_SECONDS", 10)
SENSOR_STALE_AFTER_SECONDS = _int_setting("SENSOR_STALE_AFTER_SECONDS", 30)
