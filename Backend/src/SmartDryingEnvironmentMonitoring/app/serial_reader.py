import serial
import time
import os
from dotenv import load_dotenv

load_dotenv()

SERIAL_PORT = os.getenv("SERIAL_PORT", "COM6")
BAUD_RATE = int(os.getenv("BAUD_RATE", 9600))

arduino = None


def connect_arduino():
    global arduino

    try:
        arduino = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        time.sleep(2)
        arduino.reset_input_buffer()
        print(f"Connected to Arduino on {SERIAL_PORT}")

    except Exception as e:
        arduino = None
        print("Arduino connection failed:", e)


def read_serial_line():
    global arduino

    if arduino is None:
        return None

    try:
        line = arduino.readline().decode("utf-8", errors="ignore").strip()
        return line if line else None

    except Exception as e:
        print("Serial read error:", e)
        return None


def read_sensor_block():
    data = []
    started = False

    # Read more lines because Arduino sends startup messages first
    for _ in range(120):
        line = read_serial_line()

        if not line:
            continue

        if "SENSOR DATA" in line:
            started = True
            data = [line]
            continue

        if started:
            data.append(line)

            if "----------------" in line:
                return data

    return data

def send_command(command):
    global arduino

    if arduino is None:
        return False

    try:
        arduino.write(command.encode())
        return True

    except Exception as e:
        print("Command send error:", e)
        return False    