import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.serial_reader import close_arduino, connect_arduino, is_arduino_connected
from app.background_service import auto_save_sensor_data
from app.drying_controller import controller
from app.routes import router


@asynccontextmanager
async def lifespan(_: FastAPI):
    await asyncio.to_thread(connect_arduino)
    await asyncio.to_thread(controller.recover_after_startup)
    task = asyncio.create_task(auto_save_sensor_data())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await asyncio.to_thread(controller.shutdown_safely)
        await asyncio.to_thread(close_arduino)

app = FastAPI(
    title="Smart Drying Environment Monitoring Service",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.get("/")
def root():
    return {
        "service": "Smart Drying Environment Monitoring Service",
        "status": "running"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy" if is_arduino_connected() else "degraded",
        "serial_connected": is_arduino_connected(),
    }

