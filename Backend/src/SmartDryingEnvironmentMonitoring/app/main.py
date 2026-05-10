from fastapi import FastAPI
from app.serial_reader import connect_arduino, read_sensor_block
from app.background_service import auto_save_sensor_data
from app.routes import router

import asyncio
app = FastAPI(
    title="Smart Drying Environment Monitoring Service",
    version="1.0.0"
)

app.include_router(router, prefix="/api")


@app.on_event("startup")
async def startup_event():
    connect_arduino()

    asyncio.create_task(auto_save_sensor_data())


@app.get("/")
def root():
    return {
        "service": "Smart Drying Environment Monitoring Service",
        "status": "running"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy"
    }


@app.get("/api/iot/raw")
def get_raw_sensor_data():
    block = read_sensor_block()
    return {
        "raw_data": block
    }