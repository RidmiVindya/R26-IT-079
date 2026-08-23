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
SENSOR_READ_TIMEOUT_SECONDS = _float_setting("SENSOR_READ_TIMEOUT_SECONDS", 5.0)
# The firmware emits a block roughly every 2s. Reuse the last one for a little
# under that: callers still see fresh data, but concurrent pollers stop each
# starting their own serial read and queueing up behind the port lock.
SENSOR_BLOCK_CACHE_SECONDS = _float_setting("SENSOR_BLOCK_CACHE_SECONDS", 1.5)
# A single dropped serial block is a communication hiccup, not a dead sensor:
# the Arduino free-runs its own loop, so an occasional read lands mid-cycle and
# times out even when the hardware is healthy. Fault only once this many
# consecutive reads have failed, so a transient miss cannot kill a live batch.
# Set to 1 to restore the original fault-on-first-bad-reading behaviour.
SENSOR_FAULT_AFTER_CONSECUTIVE_FAILURES = _int_setting(
    "SENSOR_FAULT_AFTER_CONSECUTIVE_FAILURES", 5
)
# `start` captures the initial weight from a single instantaneous sample, so
# load cell noise can push a later reading slightly above it with nothing
# physically changed. Allow the larger of a flat margin and a share of the
# batch, so the "product added mid-batch" check still catches a real increase.
WEIGHT_INCREASE_TOLERANCE_KG = _float_setting("WEIGHT_INCREASE_TOLERANCE_KG", 0.05)
WEIGHT_INCREASE_TOLERANCE_FRACTION = _float_setting(
    "WEIGHT_INCREASE_TOLERANCE_FRACTION", 0.10
)
SENSOR_SAVE_INTERVAL_SECONDS = _int_setting("SENSOR_SAVE_INTERVAL_SECONDS", 10)
SENSOR_STALE_AFTER_SECONDS = _int_setting("SENSOR_STALE_AFTER_SECONDS", 30)
