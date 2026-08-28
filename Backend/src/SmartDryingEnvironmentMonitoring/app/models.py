from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


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


class ControlMode(str, Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"


class DryingStatus(str, Enum):
    READY = "READY"
    DRYING = "DRYING"
    COOLING = "COOLING"
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"
    FAULT = "FAULT"


class ControlProfileRequest(BaseModel):
    """A batch control profile produced by the parameter/prediction module."""

    batch_id: str = Field(min_length=1, max_length=128)
    target_temperature_c: float = Field(gt=0, le=150)
    target_humidity_percent: float = Field(ge=0, le=100)
    predicted_duration_minutes: int | None = Field(default=None, gt=0, le=14_400)
    profile_version: str = Field(default="unversioned", min_length=1, max_length=128)
    source: Literal["prediction_module", "operator_override"] = "prediction_module"
    cooling_duration_seconds: int = Field(default=300, ge=0, le=3_600)

    @field_validator("batch_id", "profile_version")
    @classmethod
    def normalize_identifiers(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value


class StartDryingRequest(BaseModel):
    mode: ControlMode = ControlMode.AUTO


class SetModeRequest(BaseModel):
    mode: ControlMode


class ManualActuatorRequest(BaseModel):
    heater: bool | None = None
    fan: bool | None = None
    light: bool | None = None

    @field_validator("fan", "heater", "light")
    @classmethod
    def values_are_boolean(cls, value: bool | None) -> bool | None:
        return value


class TareRequest(BaseModel):
    batch_id: str | None = Field(default=None, max_length=128)


class DryingSession(BaseModel):
    batch_id: str
    mode: ControlMode
    status: DryingStatus
    target_temperature_c: float
    target_humidity_percent: float
    profile_version: str
    profile_source: str
    predicted_duration_minutes: int | None = None
    duration_ends_at: datetime | None = None
    cooling_duration_seconds: int = 300
    initial_weight_kg: float | None = None
    completion_weight_kg: float | None = None
    current_weight_kg: float | None = None
    current_temperature_c: float | None = None
    started_at: datetime | None = None
    cooling_ends_at: datetime | None = None
    completed_at: datetime | None = None
    stopped_at: datetime | None = None
    stop_reason: str | None = None
    fault_reason: str | None = None
    last_sensor_at: datetime | None = None
    heater_commanded: bool = False
    fan_commanded: bool = False
    light_commanded: bool = False
    completion_event_emitted: bool = False
    created_at: datetime
    updated_at: datetime
