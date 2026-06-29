"""Pydantic schemas for composite Markov + confirmation trigger definitions."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class MarkovTriggerDef(BaseModel):
    """Primary trigger: Markov/HMM regime change with confidence thresholds."""
    model: Literal["OMM", "HMM_intraday", "HMM_daily", "any"] = "OMM"
    to_state: str | None = None          # e.g. 'Bull', 'Bear', 'Choppy', 'Trending', 'Mean-reverting'
    conviction_min: int = Field(50, ge=0, le=100)   # OMM conviction_pct threshold
    p_transition_min: float = Field(0.3, ge=0.0, le=1.0)   # HMM transition probability
    p_stay_min: float = Field(0.5, ge=0.0, le=1.0)          # HMM staying-in-state probability


class ConfirmationSignalDef(BaseModel):
    """One confirmation condition in an N-of-M set."""
    type: Literal["structure", "momentum"]
    signal_kind: str   # structure: FVG/BOS/CHoCH/OrderBlock/RSIDivergence/MACDDivergence/Fibonacci/Confluence
                       # momentum: volume_spike/rsi_cross/macd_cross
    direction: str | None = None      # 'Bullish', 'Bearish', or None (any direction)
    min_confidence: int = Field(60, ge=0, le=100)


class CompositeTriggerDef(BaseModel):
    """Full composite trigger: one primary Markov gate + N-of-M confirmations."""
    primary: MarkovTriggerDef
    confirmations: list[ConfirmationSignalDef] = Field(default_factory=list)
    min_confirmations: int = Field(1, ge=0)   # N: how many confirmations must fire (0 = primary alone)
    horizon: Literal["intraday", "swing", "position"] = "swing"
