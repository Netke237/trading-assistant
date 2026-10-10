"""OHLCV retention, separate from audit/trade-rationale history retention."""
from app.services.scheduling_tz import _load_settings

DEFAULT_HISTORY_YEARS = 17


def history_years(settings: dict | None = None) -> int:
    settings = _load_settings() if settings is None else settings
    scheduling = settings.get("scheduling", {}) if isinstance(settings, dict) else {}
    value = scheduling.get("history_years") if isinstance(scheduling, dict) else None
    if type(value) is int and 1 <= value <= 20:
        return value
    return DEFAULT_HISTORY_YEARS


def effective_years(requested: int | None = None) -> int:
    if requested is not None and (type(requested) is not int or not 1 <= requested <= 20):
        raise ValueError("history years must be an integer from 1 to 20")
    return max(requested or 0, history_years())
