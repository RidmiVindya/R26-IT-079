import json
import urllib.request
import urllib.error
from app.serial_reader import send_command
from app.settings import PI_BRIDGE_URL

_latest_actuator_targets = {
    "heater": False,
    "fan": False,
    "light": False
}


def _http_post_json(url: str, payload: dict, timeout: float = 2.0) -> bool:
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status in (200, 201)
    except Exception as exc:
        print(f"Bridge HTTP POST {url} error: {exc}")
        return False


def get_latest_actuator_targets() -> dict:
    return dict(_latest_actuator_targets)


def control_device(command: str):
    command_map = {
        "heater_on": "1",
        "heater_off": "0",

        "light_on": "l",
        "light_off": "k",

        "fan_on": "f",
        "fan_off": "e",

        "tare": "t"
    }

    if command not in command_map:
        return {
            "success": False,
            "message": "Invalid command"
        }

    # Update commanded targets
    if command == "heater_on":
        _latest_actuator_targets["heater"] = True
    elif command == "heater_off":
        _latest_actuator_targets["heater"] = False
    elif command == "fan_on":
        _latest_actuator_targets["fan"] = True
    elif command == "fan_off":
        _latest_actuator_targets["fan"] = False
    elif command == "light_on":
        _latest_actuator_targets["light"] = True
    elif command == "light_off":
        _latest_actuator_targets["light"] = False

    # Send via Pi Bridge if configured
    if PI_BRIDGE_URL:
        if command == "tare":
            if _http_post_json(f"{PI_BRIDGE_URL}/api/tare", {}):
                return {"success": True, "command": command, "bridge": True}
        else:
            if _http_post_json(f"{PI_BRIDGE_URL}/api/command", {"command": command}):
                return {"success": True, "command": command, "bridge": True}

    # Fallback to direct USB serial
    success = send_command(command_map[command])

    if success:
        return {
            "success": True,
            "command": command
        }

    return {
        "success": False,
        "message": "Arduino communication failed"
    }


def set_actuator_states(
    heater: bool | None = None,
    fan: bool | None = None,
    light: bool | None = None,
) -> dict:
    """Apply only requested states. Arduino firmware acknowledgement is still required."""
    if heater is not None:
        _latest_actuator_targets["heater"] = heater
    if fan is not None:
        _latest_actuator_targets["fan"] = fan
    if light is not None:
        _latest_actuator_targets["light"] = light

    candidate_bridge_urls = [
        u for u in [
            PI_BRIDGE_URL,
            "http://host.docker.internal:8081",
            "http://127.0.0.1:8081",
            "http://172.20.10.2:8081",
        ] if u
    ]
    seen_urls = set()
    unique_bridge_urls = [u for u in candidate_bridge_urls if not (u in seen_urls or seen_urls.add(u))]

    payload = {}
    if heater is not None: payload["heater"] = heater
    if fan is not None: payload["fan"] = fan
    if light is not None: payload["light"] = light

    for b_url in unique_bridge_urls:
        if _http_post_json(f"{b_url}/api/actuators", payload):
            return {"success": True, "bridge": True}


    commands: list[str] = []
    if heater is not None:
        commands.append("heater_on" if heater else "heater_off")
    if fan is not None:
        commands.append("fan_on" if fan else "fan_off")
    if light is not None:
        commands.append("light_on" if light else "light_off")

    results = []
    for command in commands:
        result = control_device(command)
        results.append(result)
        if not result["success"]:
            return {"success": False, "results": results}
    return {"success": True, "results": results}
