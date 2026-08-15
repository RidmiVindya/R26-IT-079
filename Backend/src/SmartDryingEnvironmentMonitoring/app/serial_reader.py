import serial
import time
import os
from dotenv import load_dotenv

load_dotenv()

SERIAL_PORT = os.getenv("SERIAL_PORT", "COM4")
BAUD_RATE = int(os.getenv("BAUD_RATE", 9600))

# Opt-in software simulation for running without physical Arduino hardware.
# When MOCK_SENSORS is unset/false, all real-hardware behaviour below is
# byte-for-byte unchanged.
MOCK_SENSORS = os.getenv("MOCK_SENSORS", "false").strip().lower() in ("1", "true", "yes")

arduino = None

# Slowly-varying counter so mock readings drift a little between calls
# (deterministic — no random, so behaviour is reproducible).
_mock_tick = 0


def _mock_sensor_block():
    """
    Produce one simulated SENSOR DATA block in the exact text format the
    real Arduino emits, so sensor_parser.get_live_sensor_data() parses it
    identically to a real reading.
    """
    global _mock_tick
    _mock_tick += 1

    # Drift values within realistic drying-oven ranges.
    temp = 34.0 + (_mock_tick % 6)          # 34-39 C
    humidity = 55.0 - (_mock_tick % 10)     # 45-55 %
    ds_temp = 33.0 + (_mock_tick % 5)       # 33-37 C
    gas = 250 + (_mock_tick % 300)          # 250-549 (MQ-136 raw)
    # Weight decreases over time as fish dries. HX711 raw is calibrated by
    # raw_to_kg() as (raw - 78959) / 194650, so pick raw values that map to a
    # realistic ~8kg batch slowly losing mass toward ~3kg.
    RAW_ZERO = 78959
    COUNTS_PER_KG = 194650.0
    kg = max(3.0, 8.0 - _mock_tick * 0.05)  # 8.0kg drifting down, floor 3.0kg
    raw_weight = int(RAW_ZERO + kg * COUNTS_PER_KG)

    return [
        "===== SENSOR DATA =====",
        f"SHT Temp: {temp:.1f} C",
        f"Humidity: {humidity:.1f} %",
        f"DS Temp: {ds_temp:.1f} C",
        f"Gas: {gas}",
        f"Load Cell Raw: {raw_weight}",
        "Heater/Dry Air: ON",
        "Light: OFF",
        "Fan: ON",
        "-----------------------",
    ]


def connect_arduino():
    global arduino

    try:
        arduino = serial.Serial(
            port=SERIAL_PORT,
            baudrate=BAUD_RATE,
            timeout=1
        )

        time.sleep(2)
        arduino.reset_input_buffer()

        print(f"Connected to Arduino on {SERIAL_PORT}")

    except Exception as e:
        arduino = None
        print(f"Arduino connection failed: {e}")


def read_serial_line():
    global arduino

    if arduino is None:
        return None

    try:
        line = arduino.readline().decode(
            "utf-8",
            errors="ignore"
        ).strip()

        if line == "":
            return None

        return line

    except Exception as e:
        print("Serial read error:", e)
        return None


def read_sensor_block():
    """
    Reads one complete SENSOR DATA block
    """

    # Simulation mode: return a synthetic block instead of reading the serial
    # port, so the service works without physical hardware. Real-hardware path
    # below is unchanged.
    if MOCK_SENSORS:
        return _mock_sensor_block()

    block = []
    started = False

    while True:

        line = read_serial_line()

        if line is None:
            continue

        # Wait until sensor block starts
        if "SENSOR DATA" in line:
            started = True
            block = [line]
            continue

        if started:

            block.append(line)

            # End of sensor block
            if "-----------------------" in line:
                return block


def send_command(command):
    global arduino

    if arduino is None:
        return False

    try:
        arduino.write(command.encode("utf-8"))
        return True

    except Exception as e:
        print("Command send error:", e)
        return False