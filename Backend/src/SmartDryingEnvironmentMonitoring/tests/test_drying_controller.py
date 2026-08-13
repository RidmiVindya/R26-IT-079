from datetime import datetime, timedelta, timezone

import app.drying_controller as drying
from app.drying_controller import ConflictError, DryingController
from app.models import ControlMode, ControlProfileRequest
from app.sensor_parser import parse_sensor_lines


class FakeStore:
    def __init__(self):
        self.sessions = {}
        self.events = []
        self.readings = []

    def create(self, session):
        self.sessions[session["batch_id"]] = dict(session)
        return dict(session)

    def get(self, batch_id):
        session = self.sessions.get(batch_id)
        return dict(session) if session else None

    def active(self):
        for session in self.sessions.values():
            if session["status"] in {"READY", "DRYING", "COOLING"}:
                return dict(session)
        return None

    def update(self, batch_id, **changes):
        self.sessions[batch_id].update(changes)
        self.sessions[batch_id]["updated_at"] = datetime.now(timezone.utc)
        return dict(self.sessions[batch_id])


def install_fake_dependencies(monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(drying, "create_session", store.create)
    monkeypatch.setattr(drying, "get_session", store.get)
    monkeypatch.setattr(drying, "get_active_session", store.active)
    monkeypatch.setattr(drying, "update_session", store.update)
    monkeypatch.setattr(drying, "save_event", lambda batch_id, event_type, payload=None: store.events.append((batch_id, event_type, payload)))
    monkeypatch.setattr(drying, "save_sensor_log", lambda reading: store.readings.append(dict(reading)))
    monkeypatch.setattr(drying, "set_actuator_states", lambda **_: {"success": True, "results": []})
    monkeypatch.setattr(drying, "control_device", lambda _: {"success": True})
    return store


def reading(weight=9.0, temperature=45.0, humidity=55.0):
    return {
        "online": True,
        "sensor_errors": [],
        "timestamp": datetime.now(timezone.utc),
        "weight": weight,
        "temperature": temperature,
        "humidity": humidity,
        "device_id": "test-device",
    }


def test_auto_control_and_weight_completion_are_one_time(monkeypatch):
    store = install_fake_dependencies(monkeypatch)
    controller = DryingController()
    controller.create_profile(ControlProfileRequest(
        batch_id="BATCH-1",
        target_temperature_c=50,
        target_humidity_percent=40,
        cooling_duration_seconds=60,
    ))

    started = controller.start("BATCH-1", ControlMode.AUTO, reading())
    assert started.initial_weight_kg == 9.0
    assert started.completion_weight_kg == 3.0
    assert started.status.value == "DRYING"
    assert started.heater_commanded is True
    assert started.fan_commanded is True

    # A duplicate start does not reset the captured initial weight.
    duplicate = controller.start("BATCH-1", ControlMode.AUTO, reading(weight=8.0))
    assert duplicate.initial_weight_kg == 9.0

    controller.process_reading(reading(weight=3.0, temperature=49.0, humidity=40.0))
    session = store.get("BATCH-1")
    assert session["status"] == "COOLING"
    assert session["completion_event_emitted"] is True
    assert len([event for event in store.events if event[1] == "WEIGHT_COMPLETION_REACHED"]) == 1

    controller.process_reading(reading(weight=2.9, temperature=49.0, humidity=40.0))
    assert len([event for event in store.events if event[1] == "WEIGHT_COMPLETION_REACHED"]) == 1


def test_manual_targets_control_heater_and_exhaust_fan_while_light_is_manual(monkeypatch):
    store = install_fake_dependencies(monkeypatch)
    controller = DryingController()
    controller.create_profile(ControlProfileRequest(
        batch_id="BATCH-MANUAL",
        target_temperature_c=40,
        target_humidity_percent=12,
        source="operator_override",
    ))

    started = controller.start("BATCH-MANUAL", ControlMode.MANUAL, reading(temperature=39.0, humidity=55.0))
    assert started.heater_commanded is True
    assert started.fan_commanded is True

    updated = controller.manual_actuators(
        "BATCH-MANUAL",
        heater=None,
        fan=None,
        light=True,
    )

    assert updated.heater_commanded is True
    assert updated.fan_commanded is True
    assert updated.light_commanded is True

    controller.process_reading(reading(temperature=40.0, humidity=12.0))
    updated = store.get("BATCH-MANUAL")
    assert updated["heater_commanded"] is False
    assert updated["fan_commanded"] is False

    stopped = controller.stop("BATCH-MANUAL")
    assert stopped.light_commanded is False
    assert stopped.stop_reason == "operator_stop"


def test_manual_duration_stops_relays_and_auto_requires_duration_and_weight(monkeypatch):
    store = install_fake_dependencies(monkeypatch)
    controller = DryingController()
    controller.create_profile(ControlProfileRequest(
        batch_id="BATCH-MANUAL-TIME",
        target_temperature_c=40,
        target_humidity_percent=12,
        predicted_duration_minutes=1,
        source="operator_override",
    ))
    controller.start("BATCH-MANUAL-TIME", ControlMode.MANUAL, reading(temperature=39.0))
    store.update("BATCH-MANUAL-TIME", duration_ends_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    controller.process_reading(reading(temperature=39.0))
    manual_session = store.get("BATCH-MANUAL-TIME")
    assert manual_session["status"] == "STOPPED"
    assert manual_session["stop_reason"] == "duration_target_reached"

    controller.create_profile(ControlProfileRequest(
        batch_id="BATCH-AUTO-TIME",
        target_temperature_c=50,
        target_humidity_percent=40,
        predicted_duration_minutes=60,
    ))
    controller.start("BATCH-AUTO-TIME", ControlMode.AUTO, reading())
    controller.process_reading(reading(weight=3.0))
    assert store.get("BATCH-AUTO-TIME")["status"] == "DRYING"

    store.update("BATCH-AUTO-TIME", duration_ends_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    controller.process_reading(reading(weight=3.0))
    assert store.get("BATCH-AUTO-TIME")["status"] == "COOLING"


def test_manual_heater_turns_off_at_temperature_target(monkeypatch):
    store = install_fake_dependencies(monkeypatch)
    controller = DryingController()
    controller.create_profile(ControlProfileRequest(
        batch_id="BATCH-MANUAL-TEMP",
        target_temperature_c=40,
        target_humidity_percent=12,
        source="operator_override",
    ))
    started = controller.start("BATCH-MANUAL-TEMP", ControlMode.MANUAL, reading(temperature=39.0))
    assert started.heater_commanded is True

    controller.process_reading(reading(temperature=41.2))
    session = store.get("BATCH-MANUAL-TEMP")
    assert session["status"] == "DRYING"
    assert session["heater_commanded"] is False

    try:
        controller.manual_actuators("BATCH-MANUAL-TEMP", heater=True, fan=None, light=None)
    except ConflictError:
        pass
    else:
        raise AssertionError("Heater must be controlled by the MANUAL target conditions")


def test_parser_preserves_missing_weight_and_marks_bad_humidity():
    parsed = parse_sensor_lines(["SENSOR DATA", "SHT Temp: 29.8 C", "Humidity: 130 %", "-----------------------"])
    assert parsed["weight"] is None
    assert parsed["humidity"] is None
    assert parsed["sensor_errors"]
