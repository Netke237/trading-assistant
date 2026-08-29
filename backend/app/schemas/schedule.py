from __future__ import annotations
from pydantic import BaseModel, Field, model_validator


class ScheduleConfig(BaseModel):
    enabled_options:    bool      = False
    enabled_stocks:     bool      = False
    cadence_minutes:    int       = Field(60, ge=5, le=1440)
    days_of_week:       list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])  # 0=Mon…6=Sun
    window_start_hour:  int       = Field(9,  ge=0, le=23)
    window_end_hour:    int       = Field(17, ge=1, le=24)
    timezone_name:      str       = "Europe/Berlin"

    @model_validator(mode='after')
    def check_window_order(self) -> 'ScheduleConfig':
        if self.window_start_hour >= self.window_end_hour:
            raise ValueError(
                f"window_start_hour ({self.window_start_hour}) must be less than "
                f"window_end_hour ({self.window_end_hour})"
            )
        return self
