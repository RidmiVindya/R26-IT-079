from app.serial_reader import send_command


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
