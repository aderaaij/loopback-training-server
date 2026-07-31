from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class SleepStagesSchema(BaseModel):
    awake: float | None = None
    rem: float | None = None
    core: float | None = None
    deep: float | None = None


class HealthMetricsCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    date: date
    sleep_duration: float | None = Field(default=None, alias="sleepDuration")
    sleep_stages: SleepStagesSchema | None = Field(default=None, alias="sleepStages")
    resting_heart_rate: float | None = Field(default=None, alias="restingHeartRate")
    hrv_sdnn: float | None = Field(default=None, alias="hrvSdnn")
    weight: float | None = None
    vo2_max: float | None = Field(default=None, alias="vo2Max")
    steps: int | None = None
    active_energy_burned: float | None = Field(default=None, alias="activeEnergyBurned")
    basal_energy_burned: float | None = Field(default=None, alias="basalEnergyBurned")
    body_fat_percentage: float | None = Field(default=None, alias="bodyFatPercentage")
    lean_body_mass: float | None = Field(default=None, alias="leanBodyMass")
    respiratory_rate: float | None = Field(default=None, alias="respiratoryRate")
    spo2: float | None = None


class HealthMetricsBulkCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    metrics: list[HealthMetricsCreate]


class HealthMetricsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    sleep_duration: float | None
    sleep_stages: dict | None
    resting_heart_rate: float | None
    hrv_sdnn: float | None
    weight: float | None
    vo2_max: float | None
    steps: int | None
    active_energy_burned: float | None
    basal_energy_burned: float | None
    body_fat_percentage: float | None
    lean_body_mass: float | None
    respiratory_rate: float | None
    spo2: float | None
    created_at: datetime
    updated_at: datetime


class HealthMetricsBulkResponse(BaseModel):
    upserted: int
