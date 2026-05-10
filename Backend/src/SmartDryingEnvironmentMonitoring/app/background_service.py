import asyncio
from datetime import datetime
from app.sensor_parser import get_live_sensor_data
from app.database import sensor_collection


async def auto_save_sensor_data():
    while True:
        try:
            data = get_live_sensor_data()

            if data:
                data["timestamp"] = datetime.utcnow()
                data["device_id"] = "ARDUINO-NANO-001"
                data["batch_id"] = "BATCH-TEST-001"

                result = sensor_collection.insert_one(data)

                print(f"Auto saved: {result.inserted_id}")

        except Exception as e:
            print("Auto save error:", e)

        await asyncio.sleep(10000)