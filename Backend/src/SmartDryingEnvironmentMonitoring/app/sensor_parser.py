from app.serial_reader import read_sensor_block

# ============================
# HX711 Calibration
# ============================

RAW_ZERO = 78959          # Empty tray value
COUNTS_PER_KG = 194650.0  # Change after calibration


def raw_to_kg(raw):
    """
    Convert HX711 raw value to kilograms.
    """

    if raw is None:
        return 0.0

    kg = (raw - RAW_ZERO) / COUNTS_PER_KG

    if kg < 0:
        kg = 0

    return round(kg, 2)


def get_live_sensor_data():

    lines = read_sensor_block()

    data = {
        "temperature": None,
        "humidity": None,
        "ds_temperature": None,
        "gas": None,

        # store both
        "raw_weight": None,
        "weight": 0.0,

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

            raw = int(
                line.split(":")[1].strip()
            )

            data["raw_weight"] = raw
            data["weight"] = raw_to_kg(raw)

        elif "Heater/Dry Air:" in line:
            state = line.split(":")[1].strip()
            data["heater"] = state == "ON"

        elif "Light:" in line:
            state = line.split(":")[1].strip()
            data["light"] = state == "ON"

        elif "Fan:" in line:
            state = line.split(":")[1].strip()
            data["fan"] = state == "ON"

    return 