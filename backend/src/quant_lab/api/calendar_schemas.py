from __future__ import annotations

from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field


class CalendarCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    market: str = Field(min_length=1, max_length=32)
    exchange: str = Field(min_length=1, max_length=32)
    timezone: str = Field(min_length=1, max_length=64)
    source_type: str = "LOCAL_CSV"
    source_name: str = Field(min_length=1, max_length=255)


class CalendarResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    calendar_id: str
    name: str
    market: str
    exchange: str
    timezone: str
    source_type: str
    source_name: str
    created_at: datetime


class CalendarVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    trading_calendar_version_id: str
    calendar_id: str
    version: int
    status: str
    source_sha256: str
    schema_version: str
    session_count: int
    first_session_date: date | None
    last_session_date: date | None
    fingerprint: str
    created_at: datetime
    published_at: datetime | None


class CalendarSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    trading_calendar_session_id: str
    calendar_version_id: str
    session_date: date
    is_open: bool
    open_time: time | None
    close_time: time | None
    timezone: str
    session_type: str


class CalendarListResponse(BaseModel):
    items: tuple[CalendarResponse, ...]


class CalendarVersionListResponse(BaseModel):
    items: tuple[CalendarVersionResponse, ...]


class CalendarSessionListResponse(BaseModel):
    items: tuple[CalendarSessionResponse, ...]
