from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


Strategy = Literal["pullback_ema", "breakout_base", "ma_crossover", "mean_reversion_rsi"]


class StockScanRequest(BaseModel):
    universe:    list[str]
    symbols:     Optional[list[str]] = None   # when set, scan only these tickers
    direction:   Literal["Bullish", "Bearish"]
    horizon:     Literal["Intraday", "Swing", "Position"]
    strategy:    Strategy
    pullback_tolerance_pct: float = Field(0.04, gt=0, le=1.0)  # 0 < tolerance ≤ 100%
    pullback_ema_period:    int   = Field(50,   gt=0)           # EMA to pull back to
    pullback_trend_ema:     int   = Field(100,  gt=0)           # trend-confirmation EMA
    pullback_ma_type:       Literal["EMA", "SMA"] = "EMA"
    ma_crossover_fast:      int   = Field(20,   gt=0)           # fast MA period
    ma_crossover_slow:      int   = Field(50,   gt=0)           # slow MA period
    ma_crossover_lookback:  int   = Field(10,   gt=0)           # lookback ≥ 1
    breakout_volume_mult:   float = Field(1.1,  gt=1.0)         # must exceed 1× (volume expansion)
    rsi_period:             int   = Field(14,   gt=0)           # RSI look-back period
    rsi_oversold:           float = Field(30.0, gt=0, le=100)   # RSI oversold threshold
    rsi_trend_sma:          int   = Field(200,  gt=0)           # trend-confirmation SMA
    min_price:   Optional[float] = None
    max_price:   Optional[float] = None
    min_cap_usd: Optional[float] = None
    max_cap_usd: Optional[float] = None
    account_size:       float = 50_000.0
    risk_pct:           Optional[float] = 0.01
    risk_fixed_usd:     Optional[float] = None
    bt_min_trades:      int   = 10
    bt_min_win_rate:    float = 0.45


class StrategySignalOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    strategy:     str
    entry_price:  float
    stop_price:   float
    target_price: float
    rr_ratio:     float
    atr:          float
    detail:       dict


class BacktestOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    n_trades:         int
    win_rate:         float
    total_return_pct: float
    max_drawdown_pct: float
    expectancy:       float
    sharpe:           float
    confidence:       Optional[int]
    passes_gate:      bool
    summary_text:     str


class PositionCardOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    symbol:       str
    company:      str
    price:        float
    direction:    str
    strategy:     StrategySignalOut
    backtest:     BacktestOut
    stock_score:  int
    stock_status: str
    shares:       int
    dollar_risk:  float
    dollar_size:  float
    confidence:   Optional[int] = None
    confidence_text: Optional[str] = None
    sector_rs_pct: float | None = None   # stock ROC minus SPY ROC; positive = outperforming
    next_event_days: int | None = None    # days to nearest earnings or dividend (>=0)
    next_event_label: str | None = None   # "earnings" | "dividend"


class StockScanResult(BaseModel):
    scan_id:    str
    timestamp:  str
    candidates: list[PositionCardOut]
    rejected:   list[dict]
