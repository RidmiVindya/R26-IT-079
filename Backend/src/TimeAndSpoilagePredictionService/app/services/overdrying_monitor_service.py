"""Detect over-drying / burn risk during an active drying run.

Where this sits
---------------
The spoilage model answers "is this batch going bad?" - a moisture/bacteria
question, driven by high humidity, high gas, and stalled weight loss over
long elapsed times. It has no concept of the opposite failure: fish that is
already dry and still being heated.

That gap is what this module fills. It is a separate risk axis, deliberately
not folded into `spoilage_risk`: conflating "spoiling from damp" with
"burning from heat" into one Low/Medium/High would hide which failure is
actually happening, and the two call for opposite corrective actions.

What it reads
-------------
Everything comes from Milan's GET /api/iot/live, which returns the live
sensor reading *and* the oven's current session (target temperature,
completion weight, whether the heater is commanded on). Nothing here
requires any change to his service.

What it decides
---------------
Two independent signals, either of which raises the risk:

  1. Past completion weight while still heating. The oven should hand off to
     COOLING the moment the batch reaches its target dryness, so this should
     not persist. It catches the case where that hand-off did not happen -
     a stuck relay, a control-loop race, or a completion weight that is
     wrong because the tare was bad.

  2. Chamber temperature sustained well above the operator's own target -
     an independent sign that heat control is not behaving as commanded.

MQ-136 gas is *not* a trigger. It is an H2S/spoilage indicator, not a smoke
or burn sensor; using it to prove burning would be reading the wrong signal.
It is attached to the result as corroborating context only, when it happens
to be elevated at the same time.

Both signals require the condition to hold for OVERDRY_LINGER_SECONDS rather
than firing on a single reading, so one noisy sample cannot raise an alert or
(via the caller) stop a batch.

This module only *detects*. Stopping the oven is the caller's decision - see
app/services/oven_control_client.py and the drying integration routes.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

OverDryingRisk = Literal["Low", "Medium", "High"]

OVERDRY_LINGER_SECONDS = float(os.getenv("OVERDRY_LINGER_SECONDS", "60"))
OVERHEAT_MARGIN_C = float(os.getenv("OVERHEAT_MARGIN_C", "10"))
# Gas level that counts as "also elevated" when annotating a risk. Matches the
# Low/Medium boundary in classify_smell_level so the two agree on what
# "elevated" means.
GAS_ELEVATED_VALUE = float(os.getenv("GAS_ELEVATED_VALUE", "300"))

# batch_id -> when each condition first became true. Cleared when it stops
# being true, or when the batch ends.
_past_completion_since: dict[str, datetime] = {}
_overheat_since: dict[str, datetime] = {}


def clear_state(batch_id: str) -> None:
    """Forget any in-progress timers for a batch (call when a run ends)."""
    _past_completion_since.pop(batch_id, None)
    _overheat_since.pop(batch_id, None)


def _elapsed_since(store: dict[str, datetime], batch_id: str, now: datetime) -> float:
    """Seconds the condition has held, starting the clock on first sight."""
    since = store.setdefault(batch_id, now)
    return (now - since).total_seconds()


def evaluate(batch_id: str, sensor: dict[str, Any]) -> dict[str, Any]:
    """Assess over-drying risk from one live reading.

    `sensor` is Milan's /api/iot/live payload, including its nested "session".

    Returns a dict with:
        risk            - "Low" | "Medium" | "High"
        reasons         - list of human-readable strings (empty when Low)
        should_stop     - True when the oven ought to be stopped now
        stop_reason     - machine-readable reason, or None
        details         - the numbers the decision was made from
    """
    session = sensor.get("session") or {}
    now = datetime.now(timezone.utc)

    reasons: list[str] = []
    should_stop = False
    stop_reason: str | None = None
    # "Medium" marks a condition that is real but has not yet lasted long
    # enough to act on - the early warning the operator sees before a stop.
    risk: OverDryingRisk = "Low"

    # Only a genuinely drying batch can be over-dried.
    if session.get("status") != "DRYING":
        clear_state(batch_id)
        return {
            "risk": "Low",
            "reasons": [],
            "should_stop": False,
            "stop_reason": None,
            "details": {},
        }

    weight = sensor.get("weight")
    gas = sensor.get("gas")
    temperature = sensor.get("temperature")
    completion_weight = session.get("completion_weight_kg")
    target_temperature = session.get("target_temperature_c")
    heater_on = bool(session.get("heater_commanded"))

    gas_note = (
        f" Gas is also elevated ({gas})."
        if isinstance(gas, (int, float)) and gas > GAS_ELEVATED_VALUE
        else ""
    )

    # --- Signal 1: dry already, but still heating --------------------------
    past_completion = (
        isinstance(weight, (int, float))
        and isinstance(completion_weight, (int, float))
        and weight <= completion_weight
        and heater_on
    )
    if past_completion:
        held_for = _elapsed_since(_past_completion_since, batch_id, now)
        if held_for >= OVERDRY_LINGER_SECONDS:
            risk = "High"
            should_stop = True
            stop_reason = "overdrying_risk_auto_stop"
            reasons.append(
                f"Batch reached its dry target ({completion_weight} kg) but the "
                f"heater has stayed on for {held_for:.0f}s.{gas_note}"
            )
        else:
            risk = "Medium"
            reasons.append(
                f"Batch has reached its dry target ({completion_weight} kg) and "
                f"the heater is still on ({held_for:.0f}s so far)."
            )
    else:
        _past_completion_since.pop(batch_id, None)

    # --- Signal 2: running hotter than asked, for a sustained period -------
    overheating = (
        isinstance(temperature, (int, float))
        and isinstance(target_temperature, (int, float))
        and temperature >= target_temperature + OVERHEAT_MARGIN_C
    )
    if overheating:
        held_for = _elapsed_since(_overheat_since, batch_id, now)
        if held_for >= OVERDRY_LINGER_SECONDS:
            risk = "High"
            should_stop = True
            # Signal 1 is the more specific diagnosis, so it keeps the reason
            # when both fire together.
            stop_reason = stop_reason or "overheating_risk_auto_stop"
            reasons.append(
                f"Chamber has held {temperature}C - at least {OVERHEAT_MARGIN_C}C "
                f"above the {target_temperature}C target - for {held_for:.0f}s."
                f"{gas_note}"
            )
        else:
            if risk == "Low":
                risk = "Medium"
            reasons.append(
                f"Chamber is at {temperature}C, above the {target_temperature}C "
                f"target ({held_for:.0f}s so far)."
            )
    else:
        _overheat_since.pop(batch_id, None)

    return {
        "risk": risk,
        "reasons": reasons,
        "should_stop": should_stop,
        "stop_reason": stop_reason,
        "details": {
            "current_weight_kg": weight,
            "completion_weight_kg": completion_weight,
            "heater_commanded": heater_on,
            "temperature_c": temperature,
            "target_temperature_c": target_temperature,
            "gas": gas,
        },
    }
