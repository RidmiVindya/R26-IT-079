import serial
import time
import os
from dotenv import load_dotenv

load_dotenv()

<<<<<<< Updated upstream
SERIAL_PORT = os.getenv("SERIAL_PORT", "COM6")
=======
SERIAL_PORT = os.getenv("SERIAL_PORT", "COM4")
>>>>>>> Stashed changes
BAUD_RATE = int(os.getenv("BAUD_RATE", 9600))

arduino = None


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