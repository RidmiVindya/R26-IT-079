"""Batch-linked drying state machine and closed-loop actuator controller."""

import math
from datetime import timedelta
from threading import RLock

from app.database import (
    create_session,
    get_active_session,
    get_session,
    save_event,
    save_sensor_log,
    update_session,
    utcnow,
)
from app.device_controller import control_device, set_actuator_states
from app.models import ControlMode, ControlProfileRequest, DryingSession, DryingStatus
from app.settings import (
    HUMIDITY_TOLERANCE_PERCENT,
    MANUAL_HEATER_CUTOFF_MARGIN_C,
    TEMPERATURE_TOLERANCE_C,
)


class ControllerError(Exception):
    pass


class ConflictError(ControllerError):
    pass


class DryingController:
    """One-device controller. The RLock makes completion and actuator decisions atomic in-process."""

    def __init__(self) -> None:
        self._lock = RLock()

    @staticmethod
    def _model(session: dict) -> DryingSession:
        return DryingSession.model_validate(session)

    @staticmethod
    def _valid_weight(value) -> bool:
        return isinstance(value, (float, int)) and math.isfinite(value) and value > 0

    @staticmethod
    def _valid_temperature(value) -> bool:
        return isinstance(value, (float, int)) and math.isfinite(value)

    def create_profile(self, profile: ControlProfileRequest) -> DryingSession:
        with self._lock:
            existing = get_session(profile.batch_id)
            if existing:
                if existing["status"] in {DryingStatus.DRYING.value, DryingStatus.COOLING.value}:
                    raise ConflictError("Cannot replace a control profile while drying is active")
                raise ConflictError("A session already exists for this batch; create a new batch session instead")

            active = get_active_session()
            if active and active["batch_id"] != profile.batch_id:
                raise ConflictError(f"Device already has an active session for batch {active['batch_id']}")

            now = utcnow()
            session = {
                "batch_id": profile.batch_id,
                "mode": ControlMode.AUTO.value,
                "status": DryingStatus.READY.value,
                "target_temperature_c": profile.target_temperature_c,
                "target_humidity_percent": profile.target_humidity_percent,
                "profile_version": profile.profile_version,
                "profile_source": profile.source,
                "predicted_duration_minutes": profile.predicted_duration_minutes,
                "duration_ends_at": None,
                "cooling_duration_seconds": profile.cooling_duration_seconds,
                "initial_weight_kg": None,
                "completion_weight_kg": None,
                "current_weight_kg": None,
                "current_temperature_c": None,
                "started_at": None,
                "cooling_ends_at": None,
                "completed_at": None,
                "stopped_at": None,
                "fault_reason": None,
                "last_sensor_at": None,
                "heater_commanded": False,
                "fan_commanded": False,
                "light_commanded": False,
                "completion_event_emitted": False,
                "created_at": now,
                "updated_at": now,
            }
            create_session(session)
            save_event(profile.batch_id, "CONTROL_PROFILE_RECEIVED", {
                "source": profile.source,
                "profile_version": profile.profile_version,
            })
            return self._model(session)

    def get_session(self, batch_id: str) -> DryingSession:
        session = get_session(batch_id)
        if not session:
            raise ControllerError("Drying session not found")
        return self._model(session)

    def start(self, batch_id: str, mode: ControlMode, reading: dict) -> DryingSession:
        with self._lock:
            session = get_session(batch_id)
            if not session:
                raise ControllerError("Drying session not found")
            if session["status"] == DryingStatus.DRYING.value:
                # Duplicate starts are intentionally idempotent.
                return self._model(session)
            if session["status"] != DryingStatus.READY.value:
                raise ConflictError(f"Cannot start a session in {session['status']} state")
            if not reading.get("online") or reading.get("sensor_errors"):
                raise ControllerError("Cannot start drying without a valid complete sensor reading")
            if not self._valid_weight(reading.get("weight")):
                raise ControllerError("Cannot start drying without a valid positive batch weight")
            if not self._valid_temperature(reading.get("temperature")):
                raise ControllerError("Cannot start drying without a valid chamber temperature")
            if mode == ControlMode.AUTO and not (
                isinstance(reading.get("humidity"), (int, float))
                and math.isfinite(reading["humidity"])
                and 0 <= reading["humidity"] <= 100
            ):
                raise ControllerError("Cannot start AUTO drying without a valid chamber humidity")

            active = get_active_session()
            if active and active["batch_id"] != batch_id:
                raise ConflictError(f"Device already has an active session for batch {active['batch_id']}")

            initial_weight = round(float(reading["weight"]), 3)
            # Always establish a known safe relay state before starting a new batch.
            safe_result = set_actuator_states(heater=False, fan=False, light=False)
            if not safe_result["success"]:
                raise ControllerError("Cannot start drying because the device did not accept safe-state commands")
            started_at = utcnow()
            duration_minutes = session.get("predicted_duration_minutes")
            updates = {
                "mode": mode.value,
                "status": DryingStatus.DRYING.value,
                "initial_weight_kg": initial_weight,
                "completion_weight_kg": round(initial_weight / 3, 3),
                "current_weight_kg": initial_weight,
                "current_temperature_c": float(reading["temperature"]),
                "started_at": started_at,
                "duration_ends_at": (
                    started_at + timedelta(minutes=duration_minutes)
                    if duration_minutes
                    else None
                ),
                "last_sensor_at": reading["timestamp"],
                "fault_reason": None,
                "stopped_at": None,
                "completed_at": None,
                "cooling_ends_at": None,
                "completion_event_emitted": False,
                "heater_commanded": False,
                "fan_commanded": False,
                "light_commanded": False,
            }
            session = update_session(batch_id, **updates)
            save_event(batch_id, "DRYING_STARTED", {
                "mode": mode.value,
                "initial_weight_kg": initial_weight,
                "completion_weight_kg": updates["completion_weight_kg"],
            })

            if mode == ControlMode.AUTO:
                session = self._automatic_control(session, reading)
            return self._model(session)

    def set_mode(self, batch_id: str, mode: ControlMode) -> DryingSession:
        with self._lock:
            session = get_session(batch_id)
            if not session:
                raise ControllerError("Drying session not found")
            if session["status"] != DryingStatus.DRYING.value:
                raise ConflictError("Mode can only be changed while drying is active")
            if session["mode"] == mode.value:
                return self._model(session)
            if mode == ControlMode.MANUAL:
                # Entering manual mode never leaves the heater running implicitly.
                session = self._apply_actuators(session, heater=False, fan=session["fan_commanded"])
            session = update_session(batch_id, mode=mode.value)
            save_event(batch_id, "MODE_CHANGED", {"mode": mode.value})
            return self._model(session)

    def manual_actuators(
        self,
        batch_id: str,
        heater: bool | None,
        fan: bool | None,
        light: bool | None = None,
    ) -> DryingSession:
        with self._lock:
            session = get_session(batch_id)
            if not session:
                raise ControllerError("Drying session not found")
            if session["status"] != DryingStatus.DRYING.value or session["mode"] != ControlMode.MANUAL.value:
                raise ConflictError("Manual actuator control requires an active MANUAL drying session")
            if heater is None and fan is None and light is None:
                raise ControllerError("At least one actuator state is required")
            if heater is True and self._manual_temperature_limit_reached(session):
                raise ConflictError(
                    "Heater is blocked because chamber temperature is at or above the MANUAL target"
                )
            session = self._apply_actuators(session, heater=heater, fan=fan, light=light)
            save_event(batch_id, "MANUAL_ACTUATOR_COMMAND", {
                "heater": heater,
                "fan": fan,
                "light": light,
            })
            return self._model(session)

    def tare(self, batch_id: str | None) -> dict:
        with self._lock:
            active = get_active_session()
            if active and active["status"] in {DryingStatus.DRYING.value, DryingStatus.COOLING.value}:
                raise ConflictError("Tare is blocked while drying or cooling is active")
            result = control_device("tare")
            if not result["success"]:
                raise ControllerError("Tare command could not be sent to the device")
            if batch_id:
                save_event(batch_id, "TARE_REQUESTED")
            return result

    def stop(self, batch_id: str, reason: str = "operator_stop") -> DryingSession:
        with self._lock:
            session = get_session(batch_id)
            if not session:
                raise ControllerError("Drying session not found")
            if session["status"] in {DryingStatus.STOPPED.value, DryingStatus.COMPLETED.value}:
                return self._model(session)
            session = self._apply_actuators(session, heater=False, fan=False, light=False)
            session = update_session(
                batch_id,
                status=DryingStatus.STOPPED.value,
                stopped_at=utcnow(),
                fault_reason=None,
            )
            save_event(batch_id, "DRYING_STOPPED", {"reason": reason})
            return self._model(session)

    def process_reading(self, reading: dict) -> dict:
        """Persist telemetry then progress the active session using the newest valid reading."""
        with self._lock:
            session = get_active_session()
            if session:
                reading = {**reading, "batch_id": session["batch_id"]}
            save_sensor_log(reading)

            if not session:
                return reading
            if session["status"] == DryingStatus.READY.value:
                return reading

            if not reading.get("online") or reading.get("sensor_errors"):
                self._fault(session, "Sensor read is missing or invalid")
                return reading

            session = update_session(
                session["batch_id"],
                current_weight_kg=reading.get("weight"),
                current_temperature_c=reading.get("temperature"),
                last_sensor_at=reading["timestamp"],
            )

            if session["status"] == DryingStatus.COOLING.value:
                self._advance_cooling(session)
                return reading

            if session["status"] != DryingStatus.DRYING.value:
                return reading
            if session["mode"] == ControlMode.MANUAL.value:
                if self._manual_temperature_limit_reached(session):
                    if session["heater_commanded"]:
                        self._apply_actuators(session, heater=False, fan=None)
                        save_event(session["batch_id"], "MANUAL_HEATER_SAFETY_CUTOFF", {
                            "temperature_c": reading["temperature"],
                            "target_temperature_c": session["target_temperature_c"],
                        })
                if self._duration_reached(session):
                    self.stop(session["batch_id"], reason="duration_target_reached")
                return reading
            if not self._valid_temperature(reading.get("temperature")):
                self._fault(session, "Chamber temperature is missing or invalid")
                return reading
            if not self._valid_weight(reading.get("weight")):
                self._fault(session, "Batch weight is missing or invalid")
                return reading
            if float(reading["weight"]) > float(session["initial_weight_kg"]):
                self._fault(session, "Current batch weight exceeds captured initial weight")
                return reading

            if session["mode"] == ControlMode.AUTO.value and not (
                isinstance(reading.get("humidity"), (int, float))
                and math.isfinite(reading["humidity"])
                and 0 <= reading["humidity"] <= 100
            ):
                self._fault(session, "Chamber humidity is missing or invalid in AUTO mode")
                return reading

            if (
                float(reading["weight"]) <= float(session["completion_weight_kg"])
                and (not session.get("predicted_duration_minutes") or self._duration_reached(session))
            ):
                self._begin_completion(session, reading)
                return reading

            if session["mode"] == ControlMode.AUTO.value:
                self._automatic_control(session, reading)
            return reading

    @staticmethod
    def _duration_reached(session: dict) -> bool:
        duration_ends_at = session.get("duration_ends_at")
        return duration_ends_at is not None and utcnow() >= duration_ends_at

    @staticmethod
    def _manual_temperature_limit_reached(session: dict) -> bool:
        temperature = session.get("current_temperature_c")
        if not isinstance(temperature, (int, float)) or not math.isfinite(temperature):
            return False
        return temperature >= session["target_temperature_c"] + MANUAL_HEATER_CUTOFF_MARGIN_C

    def _automatic_control(self, session: dict, reading: dict) -> dict:
        temperature = float(reading["temperature"])
        humidity = reading.get("humidity")
        heater = session["heater_commanded"]
        fan = session["fan_commanded"]

        if temperature < session["target_temperature_c"] - TEMPERATURE_TOLERANCE_C:
            heater = True
        elif temperature >= session["target_temperature_c"] + TEMPERATURE_TOLERANCE_C:
            heater = False

        if isinstance(humidity, (int, float)) and math.isfinite(humidity):
            if humidity > session["target_humidity_percent"]:
                fan = True
            elif humidity <= session["target_humidity_percent"] - HUMIDITY_TOLERANCE_PERCENT:
                fan = False

        return self._apply_actuators(session, heater=heater, fan=fan)

    def _apply_actuators(
        self,
        session: dict,
        heater: bool | None,
        fan: bool | None,
        light: bool | None = None,
    ) -> dict:
        desired_heater = session["heater_commanded"] if heater is None else heater
        desired_fan = session["fan_commanded"] if fan is None else fan
        current_light = session.get("light_commanded", False)
        desired_light = current_light if light is None else light
        change_heater = desired_heater if desired_heater != session["heater_commanded"] else None
        change_fan = desired_fan if desired_fan != session["fan_commanded"] else None
        change_light = desired_light if desired_light != current_light else None
        if change_heater is None and change_fan is None and change_light is None:
            return session

        result = set_actuator_states(heater=change_heater, fan=change_fan, light=change_light)
        if not result["success"]:
            self._fault(session, "Device communication failed while changing actuator state")
            raise ControllerError("Device communication failed; session moved to FAULT")
        session = update_session(
            session["batch_id"],
            heater_commanded=desired_heater,
            fan_commanded=desired_fan,
            light_commanded=desired_light,
        )
        save_event(session["batch_id"], "ACTUATOR_STATE_REQUESTED", {
            "heater": desired_heater,
            "fan": desired_fan,
            "light": desired_light,
            "delivery": "serial_write_only",
        })
        return session

    def _begin_completion(self, session: dict, reading: dict) -> None:
        if session["completion_event_emitted"]:
            return
        # Completion is first persisted as COOLING; subsequent readings finish cooling once due.
        result = set_actuator_states(
            heater=False,
            fan=True if not session["fan_commanded"] else None,
            light=False,
        )
        if not result["success"]:
            self._fault(session, "Could not apply safe completion actuator state")
            return
        now = utcnow()
        cooling_ends_at = now + timedelta(seconds=session["cooling_duration_seconds"])
        update_session(
            session["batch_id"],
            status=DryingStatus.COOLING.value,
            heater_commanded=False,
            fan_commanded=True,
            cooling_ends_at=cooling_ends_at,
            completion_event_emitted=True,
        )
        save_event(session["batch_id"], "WEIGHT_COMPLETION_REACHED", {
            "current_weight_kg": reading["weight"],
            "completion_weight_kg": session["completion_weight_kg"],
            "cooling_ends_at": cooling_ends_at,
        })

    def _advance_cooling(self, session: dict) -> None:
        cooling_ends_at = session.get("cooling_ends_at")
        if cooling_ends_at and utcnow() < cooling_ends_at:
            return
        updated = self._apply_actuators(session, heater=False, fan=False, light=False)
        update_session(
            updated["batch_id"],
            status=DryingStatus.COMPLETED.value,
            completed_at=utcnow(),
            cooling_ends_at=None,
        )
        save_event(updated["batch_id"], "DRYING_COMPLETED")

    def _fault(self, session: dict, reason: str) -> None:
        # Make a best effort to remove heat. A failed serial write is still recorded as a fault.
        set_actuator_states(heater=False, fan=False, light=False)
        update_session(
            session["batch_id"],
            status=DryingStatus.FAULT.value,
            fault_reason=reason,
            heater_commanded=False,
            fan_commanded=False,
            light_commanded=False,
        )
        save_event(session["batch_id"], "DRYING_FAULT", {"reason": reason})

    def shutdown_safely(self) -> None:
        """A service restart never silently resumes a heating session."""
        with self._lock:
            session = get_active_session()
            if not session or session["status"] not in {DryingStatus.DRYING.value, DryingStatus.COOLING.value}:
                return
            self._fault(session, "Monitoring service stopped or restarted; operator must review before restart")

    def recover_after_startup(self) -> None:
        """Do not resume persisted heating after a crash or ungraceful restart."""
        self.shutdown_safely()


controller = DryingController()
