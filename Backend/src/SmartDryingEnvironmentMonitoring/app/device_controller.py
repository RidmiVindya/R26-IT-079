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