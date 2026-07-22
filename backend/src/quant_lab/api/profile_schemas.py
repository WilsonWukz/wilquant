from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProfileCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    market: str = "CN_A_SHARE"
    bar_frequency: str = "DAILY"
    bars_dataset_id: str
    bars_dataset_version_id: str
    calendar_id: str
    calendar_version_id: str


class ProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bars_dataset_id: str
    bars_dataset_version_id: str
    calendar_id: str
    calendar_version_id: str


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    profile_id: str
    name: str
    market: str
    bar_frequency: str
    bars_dataset_id: str
    bars_dataset_version_id: str
    calendar_id: str
    calendar_version_id: str
    status: str
    created_at: datetime
    updated_at: datetime


class ProfileListResponse(BaseModel):
    items: tuple[ProfileResponse, ...]
