from __future__ import annotations
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.schemas import SentimentData, FundamentalsOut


Strategy = Literal["pullback_ema", "breakout_base", "ma_crossover", "mean_reversion_rsi", "mean_reversion_bb", "mean_reversion_vwap"]


class StockScanRequest(BaseModel):
    universe:    list[str]
    symbols:     Optional[list[str]] = None   # when set, scan only these tickers
    direction:   Literal["Bullish", "Bearish"]
    horizon:     Literal["Intraday", "Swing", "Position"]
    strategy:    Strategy
    pullback_tolerance_pct:     float = Field(0.08, gt=0, le=1.0)  # 0 < tolerance ≤ 100%
    pullback_ema_period:        int   = Field(50,   gt=0)           # EMA to pull back to
    pullback_trend_ema:         int   = Field(100,  gt=0)           # trend-confirmation EMA
    pullback_ma_type:           Literal["EMA", "SMA"] = "EMA"
    pullback_require_reversal:  bool  = False                        # require green candle on signal bar
    ma_crossover_fast:      int   = Field(20,   gt=0)           # fast MA period
    ma_crossover_slow:      int   = Field(50,   gt=0)           # slow MA period
    ma_crossover_lookback:  int   = Field(10,   gt=0)           # lookback ≥ 1
    breakout_volume_mult:   float = Field(1.5,  gt=1.0)         # must exceed 1× (volume expansion)
    rsi_period:             int   = Field(14,   gt=0)           # RSI look-back period
    rsi_oversold:           float = Field(30.0, gt=0, le=100)   # RSI oversold threshold
    rsi_overbought:         float = Field(70.0, gt=0, le=100)   # RSI overbought threshold (bearish)
    rsi_trend_sma:          int   = Field(200,  gt=0)           # trend-confirmation SMA
    require_choppy_regime:  bool  = False                        # live filter: only fire when OMM state is Choppy
    min_price:   Optional[float] = None
    max_price:   Optional[float] = None
    min_cap_usd: Optional[float] = None
    max_cap_usd: Optional[float] = None
    account_size:       float = 50_000.0
    risk_pct:           Optional[float] = 0.01
    risk_fixed_usd:     Optional[float] = None
    bt_min_trades:      int   = 5
    bt_min_win_rate:    float = 0.45
    shortlist_max_candidates: int = Field(10, gt=0)
    regime_filter: bool = False
    # Per-scan fundamentals-gate overrides
    fundamentals_enabled:        Optional[bool]  = None
    fundamentals_caution_below:  Optional[float] = None
    fundamentals_reject_below:   Optional[float] = None
    fundamentals_de_reject:      Optional[float] = None
    # Per-scan scorer overrides — keys map directly to stock_scorer.py override handlers.
    # Options contract params and iv_rank_pass_max are excluded (irrelevant in stock mode).
    overrides: dict[str, Any] = Field(default_factory=dict)
    # Confidence gate — caps a stock's verdict when signal backtest win-rate is low.
    # When None, the gate is disabled (backend falls back to scoring_rules.yaml defaults).
    confidence_caution_below: Optional[float] = None  # win-rate < this → cap at CAUTION
    confidence_reject_below:  Optional[float] = None  # win-rate < this → cap at REJECT
    confidence_atr_mult:      Optional[float] = None  # ATR multiplier for backtest barriers
    # Per-scan regime gate overrides — sector headwind thresholds.
    regime_headwind_caution_pct: Optional[float] = None
    regime_headwind_reject_pct:  Optional[float] = None
    # Per-scan fundamentals bearish overrides — applied only on Bearish scans.
    fundamentals_caution_above:  Optional[float] = None
    fundamentals_reject_above:   Optional[float] = None


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
    sentiment: Optional[SentimentData] = None
    fundamentals: Optional[FundamentalsOut] = None


class GateFlag(BaseModel):
    gate: str
    status: str                  # 'PASS' | 'CAUTION' | 'REJECT'
    detail: str


class RuleContribution(BaseModel):
    # Mirrors stock_scorer.RuleResult EXACTLY (name/status/score/detail).
    name: str
    status: str                  # 'PASS' | 'CAUTION' | 'REJECT'
    score: int
    detail: dict = Field(default_factory=dict)


class EmaTrendOut(BaseModel):
    state: str                   # 'Above' | 'Below'
    ema: float
    last: float
    status: str                  # 'PASS' | 'CAUTION'


class RegimeHorizonBlock(BaseModel):
    horizon: str                 # 'Intraday' | 'Swing' | 'Position'
    timeframe: str
    state: str
    p_stay: float
    stability: str
    regime_age_days: int
    avg_regime_duration: float
    conviction_pct: int
    conviction_label: str
    hmm_state: Optional[str] = None
    alignment: str = "Unavailable"
    transition_row: list[float] = Field(default_factory=list)
    state_order: list[str] = Field(default_factory=list)
    insufficient_data: bool = False


class SectorTileOut(BaseModel):
    name: str
    etf: Optional[str] = None
    change_pct: Optional[float] = None


class SectorRsOut(BaseModel):
    benchmark: str                          # ETF actually used (sector ETF or SPY fallback)
    d1: Optional[float] = None
    w1: Optional[float] = None
    m1: Optional[float] = None


class MarketBackdropOut(BaseModel):
    overall: str
    direction: Optional[str] = None
    vix: Optional[float] = None


class StockAnalysisRequest(StockScanRequest):
    # Override the four required StockScanRequest fields with defaults so the
    # endpoint is callable from `{symbol}` alone (the frontend always sends the
    # real horizon/direction/strategy; defaults exist for tests + safety).
    model_config = ConfigDict(populate_by_name=True)
    symbol: str
    universe: list[str] = Field(default_factory=list)
    direction: Literal["Bullish", "Bearish"] = "Bullish"
    horizon: Literal["Intraday", "Swing", "Position"] = "Swing"
    strategy: Strategy = "pullback_ema"


class StockAnalysisOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    symbol: str
    company: str
    price: float
    direction: str
    stock_score: int
    stock_status: str
    is_index: bool = False
    # Signal-dependent payloads — None when no strategy setup exists (bypass path)
    strategy: Optional[StrategySignalOut] = None
    backtest: Optional[BacktestOut] = None
    confidence: Optional[int] = None
    confidence_text: Optional[str] = None
    sentiment: Optional[SentimentData] = None
    fundamentals: Optional[FundamentalsOut] = None
    next_event_days: Optional[int] = None
    next_event_label: Optional[str] = None
    # Analysis-specific additions
    rules: list[RuleContribution] = Field(default_factory=list)
    gate_flags: list[GateFlag] = Field(default_factory=list)
    ema_trend: Optional[EmaTrendOut] = None
    iv_rank: Optional[float] = None
    regime_by_horizon: dict[str, RegimeHorizonBlock] = Field(default_factory=dict)
    sector: Optional[SectorTileOut] = None
    sector_rs: Optional[SectorRsOut] = None
    market_backdrop: Optional[MarketBackdropOut] = None


class StockPipeline(BaseModel):
    scanned:         int   # total symbols attempted
    failed_history:  int   # "insufficient history" / "no price data" / "price $..."
    failed_score:    int   # "REJECT score=..."
    failed_signal:   int   # "no {strategy} setup"
    failed_backtest: int   # "backtest gate: ..."
    failed_regime:   int = 0  # filtered out by regime headwind
    other_rejected:  int   # exceptions / unclassified
    candidates:      int


class StockScanResult(BaseModel):
    scan_id:              str
    timestamp:            str
    candidates:           list[PositionCardOut]
    rejected:             list[dict]
    pipeline:             Optional[StockPipeline] = None
    original_count:       int = 0
    shortlist_truncated:  bool = False
    direction_banner:     Optional[str] = None
