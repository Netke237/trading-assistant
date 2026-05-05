from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ContinuousScanConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    enabled: bool = False
    cadence_minutes: int = Field(default=60, ge=5, le=1440)


class ContinuousScanStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    running: bool
    last_run_at: str | None = None
    next_run_at: str | None = None
    cadence_minutes: int


class ScanDelta(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    symbol: str
    rank_delta: int
    score_delta: int


class ScanHistoryEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    scan_id: str
    timestamp: str
    candidate_count: int
    rejected_count: int
    state: str
