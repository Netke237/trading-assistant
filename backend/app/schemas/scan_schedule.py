"""Part 3 — profile-based scan scheduling.

ScanScheduleEntry deliberately carries no runtime state (no last_run_at/
last_status/last_result) — that lives in ScheduledScanRunModel
(models/scheduled_scan_run.py) instead, keyed by schedule_entry_id. Mixing
frequently-mutated runtime data into this infrequently-written YAML config
record would mean every scan completion — for a loop-pattern entry,
potentially every 5 minutes — triggers a full config rewrite.
"""
from __future__ import annotations

from app.schemas.payload_depth import validate_payload_depth

from typing import Literal, Optional

from pydantic import field_validator, BaseModel, Field, model_validator


class ScanScheduleEntry(BaseModel):
    id: str
    label: str
    mode: Literal['options', 'stocks']
    profile_id: str               # frontend-side SearchProfile.id — display/re-sync matching only
    profile_name: str             # denormalized for display without a round-trip
    profile_synced_at: str        # ISO 8601, set by the frontend on every successful push
    resolved_request: dict        # a full ScanRequest or StockScanRequest body, already resolved client-side
    pattern: Literal['fixed_time', 'loop']
    enabled: bool = True
    days_of_week: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])

    # 'fixed_time' pattern — fires every matching weekday at this clock time (operator timezone)
    fire_time: Optional[str] = None  # "HH:MM"

    # 'loop' pattern — fires repeatedly on this cadence within this window (operator timezone)
    cadence_minutes: Optional[int] = Field(None, ge=5, le=1440)
    window_start_hour: Optional[int] = Field(None, ge=0, le=23)
    window_end_hour: Optional[int] = Field(None, ge=1, le=24)

    @model_validator(mode='after')
    def check_pattern_fields(self) -> 'ScanScheduleEntry':
        if self.pattern == 'fixed_time' and not self.fire_time:
            raise ValueError("fire_time is required for pattern='fixed_time'")
        if self.pattern == 'loop':
            if self.cadence_minutes is None or self.window_start_hour is None or self.window_end_hour is None:
                raise ValueError("cadence_minutes/window_start_hour/window_end_hour required for pattern='loop'")
            if self.window_start_hour >= self.window_end_hour:
                raise ValueError("window_start_hour must be less than window_end_hour")
        return self

    @model_validator(mode='after')
    def check_resolved_request_shape(self) -> 'ScanScheduleEntry':
        # Validate resolved_request actually parses as the right request type
        # for this entry's mode — catches a stale/malformed push at save
        # time, not silently at fire time. Import locally to avoid a
        # schema-module cycle (app.schemas imports a lot at package level).
        from app.schemas import ScanRequest
        from app.schemas.stock_scan import StockScanRequest
        try:
            if self.mode == 'options':
                ScanRequest.model_validate(self.resolved_request)
            else:
                StockScanRequest.model_validate(self.resolved_request)
        except Exception as exc:
            raise ValueError(f"resolved_request does not match a valid request for mode={self.mode}: {exc}")
        return self

    _validate_payload_depth = field_validator('resolved_request', mode="before")(validate_payload_depth)


class ScanScheduleEntryCreate(BaseModel):
    """POST body — same shape as ScanScheduleEntry minus the server-generated id."""
    label: str
    mode: Literal['options', 'stocks']
    profile_id: str
    profile_name: str
    profile_synced_at: str
    resolved_request: dict
    pattern: Literal['fixed_time', 'loop']
    enabled: bool = True
    days_of_week: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    fire_time: Optional[str] = None
    cadence_minutes: Optional[int] = Field(None, ge=5, le=1440)
    window_start_hour: Optional[int] = Field(None, ge=0, le=23)
    window_end_hour: Optional[int] = Field(None, ge=1, le=24)

    _validate_payload_depth = field_validator('resolved_request', mode="before")(validate_payload_depth)


class ScheduledScanRunOut(BaseModel):
    id: str
    schedule_entry_id: str
    mode: Literal['options', 'stocks']
    fired_at: str
    status: Literal['success', 'error']
    error: Optional[str] = None
    result_json: Optional[str] = None
