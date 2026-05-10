from app.serial_reader import read_sensor_block


def get_live_sensor_data():
    lines = read_sensor_block()

    data = {
        "temperature": None,
        "humidity": None,
        "ds_temperature": None,
        "gas": None,
        "weight": None,
        "heater": False,
        "light": False,
        "fan": False
    }

    for line in lines:

        if "SHT Temp:" in line:
            data["temperature"] = float(
                line.split(":")[1].replace("C", "").strip()
            )

        elif "Humidity:" in line:
            data["humidity"] = float(
                line.split(":")[1].replace("%", "").strip()
            )

        elif "DS Temp:" in line:
            data["ds_temperature"] = float(
                line.split(":")[1].replace("C", "").strip()
            )

        elif "Gas:" in line:
            data["gas"] = int(
                line.split(":")[1].strip()
            )

        elif "Load Cell Raw:" in line:
            data["weight"] = int(
                line.split(":")[1].strip()
            )

        elif "Heater/Dry Air:" in line:
            state = line.split(":")[1].strip()
            data["heater"] = state == "ON"

        elif "Light:" in line:
            state = line.split(":")[1].strip()
            data["light"] = state == "ON"

        elif "Fan:" in line:
            state = line.split(":")[1].strip()
            data["fan"] = state == "ON"

    return data