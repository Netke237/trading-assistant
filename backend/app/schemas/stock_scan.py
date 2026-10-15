from __future__ import annotations

from app.schemas.payload_depth import validate_payload_depth
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.schemas import SentimentData, FundamentalsOut, StockExplanation
from app.services.horizon_profiles import TunedHorizon


Strategy = Literal["pullback_ema", "breakout_base", "ma_crossover", "mean_reversion_rsi", "mean_reversion_bb", "mean_reversion_vwap", "mean_reversion_multi"]


class StockScanRequest(BaseModel):
    category: Literal["stocks", "pullback"] = "stocks"
    # NUMERIC-API-INPUTS T2: every float is finite or a 422. Inherited by
    # StockAnalysisRequest (pydantic merges a parent's config into a subclass).
    model_config = ConfigDict(allow_inf_nan=False)

    universe:    list[str]
    symbols:     Optional[list[str]] = None   # when set, scan only these tickers
    direction:   Literal["Bullish", "Bearish"]
    horizon:     Literal["Intraday", "Swing", "Position"]
    strategy:    Strategy
    # Strategy fields (STOCKS-HORIZON-T1 H4): Optional, default None. An
    # omitted field takes the backend profile for direction x params horizon
    # (strategy_param_store.get_profile); a value is an explicit override.
    # They used to carry non-None defaults, so the YAML `active:` value of any
    # field the request carries never reached a live scan.
    pullback_tolerance_pct:     Optional[float] = Field(None, gt=0, le=1.0)  # 0 < tolerance ≤ 100%
    pullback_ema_period:        Optional[int]   = Field(None, gt=0)           # EMA to pull back to
    pullback_trend_ema:         Optional[int]   = Field(None, gt=0)           # trend-confirmation EMA
    pullback_ma_type:           Optional[Literal["EMA", "SMA"]] = None
    pullback_require_reversal:  bool  = False                        # require green candle on signal bar (UI toggle, not tuned)
    ma_crossover_fast:      Optional[int]   = Field(None, gt=0)           # fast MA period
    ma_crossover_slow:      Optional[int]   = Field(None, gt=0)           # slow MA period
    ma_crossover_lookback:  Optional[int]   = Field(None, gt=0)           # lookback ≥ 1
    breakout_volume_mult:   Optional[float] = Field(None, gt=1.0)         # must exceed 1× (volume expansion)
    rsi_period:             Optional[int]   = Field(None, gt=0)           # RSI look-back period
    rsi_oversold:           Optional[float] = Field(None, gt=0, le=100)   # RSI oversold threshold
    rsi_overbought:         Optional[float] = Field(None, gt=0, le=100)   # RSI overbought threshold (bearish)
    rsi_trend_sma:          Optional[int]   = Field(None, gt=0)           # trend-confirmation SMA
    require_choppy_regime:  Optional[bool]  = None                        # live filter: only fire when OMM state is Choppy
    # Which tuned horizon's parameters this scan reads. None + a hold (and a
    # non-Intraday scoring horizon) -> horizon_profiles.tuned_params_horizon.
    params_horizon: Optional[TunedHorizon] = None
    min_price:   Optional[float] = None
    max_price:   Optional[float] = None
    min_cap_usd: Optional[float] = None
    max_cap_usd: Optional[float] = None
    account_size:       float = Field(50_000.0, gt=0)
    # gt=0: a 0 used to be turned into 1% by `_position_size`'s `or 0.01`.
    # None (with no risk_fixed_usd) still means the 1% default, now sized by
    # the conviction multiplier like any other percentage.
    risk_pct:           Optional[float] = Field(0.01, gt=0, le=1)

    @field_validator("risk_pct", mode="before")
    @classmethod
    def _stored_zero_is_unset(cls, v):
        # Decision P3A-STORED-ZERO-RISK-RUNS-AT-DEFAULT-2026-09-25 (Kenneth):
        # scan schedules saved while "Max loss per trade" was 0% carry
        # risk_pct 0 in scan_schedule.yaml. Before gt=0 they sized at the 1%
        # default; they still do (now conviction-adjusted, like any None) rather
        # than failing every fire and 500-ing the whole schedule list. Manual
        # scans never post 0 -- the frontend stops them with a message.
        if v == 0 and not isinstance(v, bool):
            return None
        return v
    # gt=0 and finite (REGIME-SIZING-AUDIT r2 finding 2). Unbounded, -100 sent
    # 1 share with dollar_risk -100; 0 was falsy in `_position_size` and fell
    # through to the 1% default, sizing UP from a request for $0; nan/inf made
    # int() raise in every symbol, which gather() swallowed into an empty scan.
    # No LIVE caller sends this field (no frontend source, no stored schedule),
    # so refusing at the door breaks no live caller. A request SAVED before the bound
    # (stock_scan's last_request_json) could carry one; restore_stock_from_db
    # drops such a request instead of failing startup (r3 finding 2).
    risk_fixed_usd:     Optional[float] = Field(None, gt=0, allow_inf_nan=False)
    # The hold that produced the scan (STOCKS-HORIZON-P0B B6): the earnings veto
    # window is max(reject_days, hold_max_days). None (an older client, or a
    # schedule saved before the field) uses the scoring horizon's preset hold,
    # `stock_scorer.DEFAULT_HOLD_MAX`.
    hold_max_days:      Optional[int] = Field(None, ge=0, le=3650)
    bt_min_trades:      int   = 5
    bt_min_win_rate:    float = 0.45
    shortlist_max_candidates: int = Field(10, gt=0)
    regime_filter: bool = False
    # Step-3 "Min stock score" (decision Q5). Stocks-mode only. A name whose
    # composite score is below it is dropped as a score-gate failure. None =
    # no extra floor beyond the REJECT status (score < caution threshold 35).
    min_stock_score: Optional[float] = Field(None, ge=0, le=100)
    # Per-scan fundamentals-gate overrides
    fundamentals_enabled:        Optional[bool]  = None
    fundamentals_caution_below:  Optional[float] = None
    fundamentals_reject_below:   Optional[float] = None
    fundamentals_de_reject:      Optional[float] = None
    # Per-scan scorer overrides — keys map directly to stock_scorer.py override handlers.
    # Options contract params and the two IV ceilings (iv_abs_pass_max,
    # iv_rank_pass_max) are excluded (irrelevant in stock mode).
    overrides: dict[str, Any] = Field(default_factory=dict)
    # Confidence gate — caps a stock's verdict when signal backtest win-rate is low.
    # When None, the gate is disabled (backend falls back to scoring_rules.yaml defaults).
    confidence_caution_below: Optional[float] = None  # win-rate < this → cap at CAUTION
    confidence_reject_below:  Optional[float] = None  # win-rate < this → cap at REJECT
    # Per-scan ATR win/loss barrier override (asymmetric — must be provided
    # together; a lone target or stop is ignored, see routers/stock_scan.py).
    # When both are None, the per-horizon config in scoring_rules.yaml applies.
    confidence_atr_mult_target: Optional[float] = None
    confidence_atr_mult_stop:   Optional[float] = None
    # Per-scan regime gate overrides — sector headwind thresholds.
    regime_headwind_caution_pct: Optional[float] = None
    regime_headwind_reject_pct:  Optional[float] = None
    # Per-scan fundamentals bearish overrides — applied only on Bearish scans.
    fundamentals_caution_above:  Optional[float] = None
    fundamentals_reject_above:   Optional[float] = None
    # Mean reversion multi-signal params. Optional (H4): None takes the multi
    # profile. min_confirmations > variants and the intraday variant are
    # refused on the MERGED shape (stock_scan._reject_unsupported_multi_variants),
    # so a request with 2 variants against a profile min_confirmations 3 is a
    # 422, not a silently dead scan.
    mean_reversion_variants: Optional[list[str]] = None
    mean_reversion_min_confirmations: Optional[int] = Field(None, ge=1, le=3)
    vwap_lookback:       Optional[int]   = Field(None, gt=0)
    vwap_deviation_pct:  Optional[float] = Field(None, gt=0)

    _validate_payload_depth = field_validator('overrides', mode="before")(validate_payload_depth)


class StrategySignalOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    strategy:     str
    entry_price:  float
    stop_price:   float
    target_price: float
    #: Full nearest-first exit ladder; targets[0] == target_price. Defaults to []
    #: so a scan result deserialized from an older persisted session still
    #: validates.
    targets:      list[float] = Field(default_factory=list)
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
    # STOCKS-T1-FOLLOWUPS F2: trades the backtest closed on time (held the
    # hold, neither stop nor target), and the hold it ran with. A new result
    # always carries n_time_exits as an int; None = unknown (a row saved
    # before these fields). hold_max_days None with an int count = no hold.
    n_time_exits:     Optional[int] = None
    hold_max_days:    Optional[int] = None


class PositionCardOut(BaseModel):
    backtest_artifact_id: str | None = None
    backtest_artifact_status: Literal["available", "unsupported", "insufficient_history", "invalid_input", "failed", "invalid_evidence", "storage_unavailable", "capture_unavailable", "original_unavailable"] | None = None
    model_config = ConfigDict(populate_by_name=True)
    symbol:       str
    company:      str
    price:        float
    direction:    str
    strategy:     StrategySignalOut
    backtest:     BacktestOut
    stock_score:  int
    stock_status: str
    gate_flags: list["GateFlag"] = Field(default_factory=list)
    shares:       int
    dollar_risk:  float
    dollar_size:  float
    # What `shares` was sized on: "off" (regime_sizing disabled, full risk
    # budget), "measured" (the conviction ramp) or "floor:unmeasured" (the
    # symbol's regime could not be measured, so min_mult). Same vocabulary as
    # the auto-trader's history rows.
    sizing_basis: Optional[str] = None
    confidence:   Optional[int] = None
    confidence_text: Optional[str] = None
    sector_rs_pct: float | None = None   # stock ROC minus SPY ROC; positive = outperforming
    next_event_days: int | None = None    # days to nearest earnings or dividend (>=0)
    next_event_label: str | None = None   # "earnings" | "dividend"
    # Next earnings date in days (None = unknown), and whether it falls inside
    # the scan's veto window (STOCKS-HORIZON-P0B B6).
    earnings_days: Optional[int] = None
    earnings_veto: bool = False
    sentiment: Optional[SentimentData] = None
    fundamentals: Optional[FundamentalsOut] = None
    # Which tuned horizon's parameters the signal used (None = the direction
    # baseline, no params horizon) and whether a tuned profile existed for it
    # (STOCKS-HORIZON-T1 H4). Defaults so a persisted older result validates.
    params_horizon: Optional[str] = None
    params_source: Literal["tuned", "baseline"] = "baseline"
    # STOCK-PRES-P1: the scorer's own evidence for stock_score (weights, factor
    # components, scorer caps), exactly StockScoreCard.explanation. Scorer-time:
    # its `status` is the SCORER's verdict, before the scan's later caps
    # (missing/low confidence, Bearish, earnings veto). The verdict is
    # stock_status. None on results persisted before P1, or if the evidence
    # failed validation (logged; the candidate is kept).
    stock_explanation: Optional[StockExplanation] = None


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
    stock_explanation: Optional[StockExplanation] = None
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
    earnings_days: Optional[int] = None
    earnings_veto: bool = False
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
    # None means ABSENT, not zero -- a result persisted before these existed
    # cannot claim nothing was gated. Same reasoning as OptionsPipeline's.
    failed_direction: Optional[int] = None  # direction-conviction gate
    failed_shortlist: Optional[int] = None  # trimmed by the shortlist cap
    # Direction gate, trend UNMEASURED ("no data", decision
    # P3A-UNMEASURED-TREND-REMOVE-2026-09-25) -- counted apart from
    # failed_direction, which is a measured trend below the floor.
    failed_direction_unmeasured: Optional[int] = None
    # The direction-conviction floor THIS scan applied; None = exempt horizon
    # (or a result persisted before the field existed).
    direction_min_trend: Optional[float] = None
    # Optional for the same reason, and to actually match OptionsPipeline —
    # it was required here while the comment above claimed parity with it.
    other_rejected:  Optional[int] = None   # exceptions / unclassified
    candidates:      int


class StockScanResult(BaseModel):
    report_run_id: Optional[str] = None
    report_generation: Optional[int] = None
    report_persistence: Optional[Literal["saved", "unavailable"]] = None
    scan_id:              str
    timestamp:            str
    candidates:           list[PositionCardOut]
    rejected:             list[dict]
    pipeline:             Optional[StockPipeline] = None
    original_count:       int = 0
    shortlist_truncated:  bool = False
    direction_banner:     Optional[str] = None
    # The earnings veto window this scan applied, max(reject_days, hold);
    # None on a result persisted before it existed.
    veto_days:            Optional[int] = None
