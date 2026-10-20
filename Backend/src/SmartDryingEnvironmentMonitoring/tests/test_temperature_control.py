"""Hardware-free checks for fixed 60C control and command bypasses."""
import math

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import app.drying_controller as drying
from app.drying_controller import ControllerError, DryingController
from app.models import CommandRequest, ControlMode, ControlProfileRequest
from test_drying_controller import install_fake_dependencies, reading


def profile(target=120):
    return ControlProfileRequest(batch_id="TEMP-TEST", target_temperature_c=target,
                                 target_humidity_percent=40, predicted_duration_minutes=30)


@pytest.mark.parametrize("requested", [20, 40, 60, 100, 120, 150, 200, "120"])
def test_every_valid_recommendation_uses_fixed_60(requested):
    assert profile(requested).target_temperature_c == 60


@pytest.mark.parametrize("requested", [0, -1, math.nan, math.inf, -math.inf, True, None, "bad"])
def test_invalid_temperature_is_not_hidden_by_normalization(requested):
    with pytest.raises(ValidationError):
        profile(requested)


def setup(monkeypatch):
    store = install_fake_dependencies(monkeypatch)
    calls = []
    def actuators(**values):
        calls.append(values)
        return {"success": True}
    monkeypatch.setattr(drying, "set_actuator_states", actuators)
    controller = DryingController()
    controller.create_profile(profile())
    return controller, store, calls


@pytest.mark.parametrize("mode", [ControlMode.AUTO, ControlMode.MANUAL])
def test_thermostat_switches_off_at_60_and_restarts_at_58(monkeypatch, mode):
    controller, store, calls = setup(monkeypatch)
    controller.start("TEMP-TEST", mode, reading(temperature=55))
    assert store.get("TEMP-TEST")["heater_commanded"] is True
    controller.process_reading(reading(temperature=59.9))
    assert store.get("TEMP-TEST")["heater_commanded"] is True
    controller.process_reading(reading(temperature=60))
    assert store.get("TEMP-TEST")["heater_commanded"] is False
    assert store.get("TEMP-TEST")["status"] == "DRYING"
    assert calls[-1]["heater"] is False
    controller.process_reading(reading(temperature=59))
    assert store.get("TEMP-TEST")["heater_commanded"] is False
    controller.process_reading(reading(temperature=58))
    assert store.get("TEMP-TEST")["heater_commanded"] is True
    assert calls[-1]["heater"] is True
    controller.process_reading(reading(temperature=65))
    assert calls[-1]["heater"] is False


@pytest.mark.parametrize("mode", [ControlMode.AUTO, ControlMode.MANUAL])
@pytest.mark.parametrize("temperature", [60, 75])
def test_hot_start_never_briefly_commands_heat(monkeypatch, mode, temperature):
    controller, store, calls = setup(monkeypatch)
    started = controller.start("TEMP-TEST", mode, reading(temperature=temperature))
    assert started.heater_commanded is False
    assert started.target_temperature_c == 60
    assert calls and all(call.get("heater") is not True for call in calls)


@pytest.mark.parametrize("temperature", [None, math.nan, math.inf, False])
def test_unknown_temperature_prevents_start(monkeypatch, temperature):
    controller, store, calls = setup(monkeypatch)
    with pytest.raises(ControllerError):
        controller.start("TEMP-TEST", ControlMode.AUTO, reading(temperature=temperature))
    assert calls[-1]["heater"] is False
    assert not any(call.get("heater") is True for call in calls)


@pytest.mark.parametrize("change", [
    {"temperature": None}, {"temperature": math.nan}, {"online": False},
    {"temperature": 65, "humidity": None, "sensor_errors": ["humidity missing"]},
])
def test_heat_is_removed_before_bad_sensor_paths_return(monkeypatch, change):
    controller, store, calls = setup(monkeypatch)
    controller.start("TEMP-TEST", ControlMode.AUTO, reading(temperature=55))
    data = reading(temperature=55)
    data.update(change)
    controller.process_reading(data)
    assert store.get("TEMP-TEST")["heater_commanded"] is False
    assert calls[-1]["heater"] is False


def test_secondary_probe_can_veto_heating(monkeypatch):
    controller, store, calls = setup(monkeypatch)
    data = {**reading(temperature=45), "ds_temperature": 61}
    controller.start("TEMP-TEST", ControlMode.AUTO, data)
    assert all(call.get("heater") is not True for call in calls)
    assert store.get("TEMP-TEST")["heater_commanded"] is False


def test_old_persisted_target_is_normalized_without_resetting_run(monkeypatch):
    controller, store, calls = setup(monkeypatch)
    store.update("TEMP-TEST", target_temperature_c=150)
    controller.start("TEMP-TEST", ControlMode.AUTO, reading(temperature=55))
    started_at = store.get("TEMP-TEST")["started_at"]
    store.update("TEMP-TEST", target_temperature_c=150)
    controller.process_reading(reading(temperature=60))
    assert store.get("TEMP-TEST")["target_temperature_c"] == 60
    assert store.get("TEMP-TEST")["started_at"] == started_at
    assert calls[-1]["heater"] is False


def test_duplicate_start_obeys_hot_reading(monkeypatch):
    controller, store, calls = setup(monkeypatch)
    controller.start("TEMP-TEST", ControlMode.AUTO, reading(temperature=55))
    started_at = store.get("TEMP-TEST")["started_at"]
    controller.start("TEMP-TEST", ControlMode.AUTO, reading(temperature=62))
    assert store.get("TEMP-TEST")["started_at"] == started_at
    assert calls[-1]["heater"] is False


def test_legacy_heater_on_cannot_bypass_thermostat(monkeypatch):
    import app.routes as routes
    calls = []
    monkeypatch.setattr(routes, "control_device", lambda command: calls.append(command))
    with pytest.raises(HTTPException) as failure:
        routes.legacy_iot_command(CommandRequest(command="heater_on"))
    assert failure.value.status_code == 409
    assert calls == []


def test_legacy_heater_off_remains_available(monkeypatch):
    import app.routes as routes
    calls = []
    monkeypatch.setattr(routes, "control_device", lambda command: calls.append(command))
    routes.legacy_iot_command(CommandRequest(command="heater_off"))
    assert calls == ["heater_off"]


def test_light_command_does_not_reenable_heat(monkeypatch):
    import app.routes as routes
    import app.device_controller as device
    monkeypatch.setattr(routes, "get_active_session", lambda: {"status": "DRYING"})
    monkeypatch.setattr(routes, "control_device", lambda command: {"success": True})
    monkeypatch.setitem(device._latest_actuator_targets, "heater", False)
    routes.legacy_iot_command(CommandRequest(command="light_on"))
    assert device.get_latest_actuator_targets()["heater"] is False
