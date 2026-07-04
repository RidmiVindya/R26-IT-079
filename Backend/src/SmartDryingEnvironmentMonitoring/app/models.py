from pydantic import BaseModel


class CommandRequest(BaseModel):
    command: str


class SensorData(BaseModel):
    temperature: float | None = None
    humidity: float | None = None
    ds_temperature: float | None = None
    gas: int | None = None

    # HX711
    raw_weight: int | None = None
    weight: float | None = None

    heater: bool = False
    light: bool = False
    fan: bool = False