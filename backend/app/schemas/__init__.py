from __future__ import annotations
from enum import Enum
from typing import Literal, Optional
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.scan import (
    ContinuousScanConfig,
    ContinuousScanStatus,
    ScanDelta,
    ScanHistoryEntry,
)

# ── Shared literals ──────────────────────────────────────────────────────────

Status = Literal['PASS', 'CAUTION', 'REJECT', 'PENDING', 'NO_DATA']
Direction = Literal['Bullish', 'Bearish']
Horizon = Literal['Intraday', 'Swing', 'Position']
ScanState = Literal['IDLE', 'SCANNING', 'COMPLETED', 'FAILED', 'PARTIAL', 'CANCELLED']
AlertKind = Literal['Info', 'Action', 'Critical']
OrderType = Literal['Limit', 'Market', 'Stop']
OptionRight = Literal['C', 'P']
TrendDir = Literal['up', 'flat', 'down']
RrModel = Literal['Heston repriced', 'BS repriced (IV-derived)', 'Delta approximation']
# Active take-profit method driving a position's TP_HIT alert — see
# docs/superpowers/plans/2026-08-26-exit-plan-pipeline.md, Feature D.
TpMethod = Literal['ladder', 'monte_carlo', 'exit_plan_2r', 'exit_plan_3r']

# ── Sentiment / regime ──────────────────────────────────────────────────────

class SentimentData(BaseModel):
    """Per-symbol per-scan conviction payload from Markov regime signal."""
    model_config = ConfigDict(populate_by_name=True)
    horizon: str
    timeframe: str
    state: str
    p_stay: float
    stability: str
    regime_age_days: int
    avg_regime_duration: float
    conviction_pct: int
    conviction_label: str
    interpretation: str
    hmm_state: Optional[str] = None
    alignment: Literal['Aligned', 'Diverging', 'Unavailable'] = 'Unavailable'
    insufficient_data: bool = False


# ── Fundamentals ─────────────────────────────────────────────────────────────

class FundamentalsOut(BaseModel):
    score: int
    quality_label: str
    risk_label: str
    growth_score: int
    quality_score: int
    risk_score: int
    safety_flags: list[str] = Field(default_factory=list)
    detail: dict = Field(default_factory=dict)


# ── Score breakdowns ─────────────────────────────────────────────────────────

class TriggerDetail(BaseModel):
    candle:         str
    macd_pass:      bool
    rsi_pass:       bool
    stoch_pass:     bool
    momentum_count: int
    volume_bonus:   bool

class PullbackDetail(BaseModel):
    retracement_pct: float | None = None
    reason:          str
    fvg_hit:         bool = False
    fvg_gap:         list[float] | None = None

class TrendDetail(BaseModel):
    method:    str
    adx_val:   float | None = None
    price_pts: int   | None = None
    slope_pts: int   | None = None
    stock_roc: float | None = None
    bench_roc: float | None = None

class EventDetail(BaseModel):
    event:         str
    days_to_event: int | None = None

class VolDetail(BaseModel):
    iv_rank: float | None = None
    reason:  str   | None = None


class DteDetail(BaseModel):
    dte: int
    preferred_min: int
    preferred_max: int


class DeltaDetail(BaseModel):
    delta: float
    preferred_min: float
    preferred_max: float


class IvRankDetail(BaseModel):
    iv_rank: float | None = None
    preferred_max: float


class LiquidityDetail(BaseModel):
    volume: int
    open_interest: int
    preferred_volume_min: int
    preferred_oi_min: int


class SpreadDetail(BaseModel):
    spread_pct: float
    preferred_max_pct: float


class ScoreBreakdown(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    trend: int
    pullback: int
    trigger: int
    event: int
    volatility: int
    # Optional rich detail — populated from RuleResult.detail
    trendDetail:    TrendDetail    | None = None
    pullbackDetail: PullbackDetail | None = None
    triggerDetail:  TriggerDetail  | None = None
    eventDetail:    EventDetail    | None = None
    volDetail:      VolDetail      | None = None
    sentiment:      Optional[SentimentData] = None


class ContractScoreBreakdown(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    dteFit: int
    delta: int
    ivAttractiveness: int
    liquidity: int
    spread: int
    dteDetail: DteDetail | None = None
    deltaDetail: DeltaDetail | None = None
    ivDetail: IvRankDetail | None = None
    liquidityDetail: LiquidityDetail | None = None
    spreadDetail: SpreadDetail | None = None


# ── Watchlist ────────────────────────────────────────────────────────────────

class WatchlistRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    symbol: str
    company: str
    price: float
    direction: Direction
    horizon: Horizon
    score: int
    rankDelta: int
    scoreDelta: Optional[int] = None
    status: Status
    breakdown: ScoreBreakdown
    nextEventDays: Optional[int] = None
    nextEventLabel: Optional[str] = None


# ── Contracts ────────────────────────────────────────────────────────────────

class OptionContract(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    symbol: str
    strike: int
    expiry: str
    right: OptionRight
    dte: int
    dteTotal: int
    price: float
    delta: float
    theta: float
    ivRank: int
    ivPercentile: int
    spread: float
    volume: int
    score: int
    contractConfidence: Status


# ── Candles ──────────────────────────────────────────────────────────────────

class Candle(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: int


# ── Regime ───────────────────────────────────────────────────────────────────

class RegimeMetric(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    label: str
    value: str
    status: Status
    trend: Optional[TrendDir] = None


class OmmData(BaseModel):
    """Observable Markov Model output for Position / Swing horizons."""
    model_config = ConfigDict(populate_by_name=True)
    state: Literal['Bull', 'Bear', 'Choppy']
    p_stay: float                    # P(current state persists next bar)
    stability: Literal['Stable', 'Fragile']
    regime_age_days: int             # consecutive bars in current state
    avg_regime_duration: float       # 1 / (1 − p_stay), in days
    transition_row: list[float]      # [P(Bull), P(Bear), P(Choppy)] for current state
    state_order: list[str]           # ['Bull', 'Bear', 'Choppy'] — index key
    conviction_pct: Optional[int] = None
    conviction_label: Optional[str] = None


class IntraHmmTransition(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    to: str
    prob: float


class IntraHmmData(BaseModel):
    """Gaussian HMM output for Intraday horizon (15-min bars)."""
    model_config = ConfigDict(populate_by_name=True)
    state: Literal['Trending', 'Choppy', 'Mean-reverting']
    p_stay: float
    p_transition: list[IntraHmmTransition]   # non-trivial transitions (prob > 0.05)


IntradayHmmStatus = Literal['ok', 'insufficient_data', 'unavailable']


class MarketRegime(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    overall: Status
    headline: str
    metrics: list[RegimeMetric]
    omm: Optional[OmmData] = None                  # Position / Swing — None if insufficient data
    intraday_hmm: Optional[IntraHmmData] = None    # Intraday HMM — None if hmmlearn unavailable
    intraday_hmm_status: IntradayHmmStatus = 'unavailable'  # ok / insufficient_data / unavailable
    intraday_omm: Optional[OmmData] = None         # Intraday OMM fallback when HMM unavailable
    vix_pct_30d: Optional[float] = None            # VIX percentile vs last 30 trading days
    vix_pct_252d: Optional[float] = None           # VIX percentile vs last 252 trading days
    conviction_pct: Optional[int] = None
    conviction_label: Optional[str] = None
    hmm_state: Optional[str] = None
    alignment: Optional[Literal['Aligned', 'Diverging', 'Unavailable']] = None
    regime_direction: Optional[Literal['BULL', 'BEAR', 'MIXED']] = None


# ── Sectors ──────────────────────────────────────────────────────────────────

class SectorTile(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    key: str
    name: str
    changePct: float
    status: Status
    symbolCount: int = 0


class IndexChangeTile(BaseModel):
    """Daily changePct/status for an index ETF (SPY, QQQ). No symbolCount."""
    key: str
    name: str
    changePct: float
    status: Status


# ── Portfolio ────────────────────────────────────────────────────────────────

class PortfolioPosition(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    symbol: str
    contract: str
    direction: Direction
    entryDate: str
    expiry: str
    dteRemaining: int
    dteTotal: int
    entryPrice: float
    currentPrice: float
    pnlDollar: float
    pnlPct: float
    stop: float
    target: float
    status: Status
    ivRank: Optional[int] = None
    delta: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    contracts: Optional[int] = None
    source: Optional[Literal['broker', 'manual']] = None
    orderedAt: Optional[str] = None
    # NOTE: no premium_stop_pct here, deliberately. This model is the MOCK
    # FIXTURE shape (app/fixtures/portfolio.py is its only referent) -- it is
    # not a request or response model on any route. Piece 4's field lives on
    # PortfolioPositionCreate / Update / Schema below, which are the live ones.


# ── Alerts ───────────────────────────────────────────────────────────────────

class AlertItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    kind: AlertKind
    symbol: str
    reason: str
    timestamp: str
    recId: str = ""
    alertType: str = "SCAN_COMPLETE"
    price: Optional[float] = None
    referenceValue: Optional[float] = None
    direction: Optional[str] = None
    contract: Optional[str] = None


# ── Events ───────────────────────────────────────────────────────────────────

class UpcomingEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    date: str
    symbol: str
    label: str
    status: Status


# ── News ─────────────────────────────────────────────────────────────────────

class NewsItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id:        str
    symbol:    str
    headline:  str
    source:    str
    timestamp: str
    sentiment: Literal['bull', 'bear', 'neutral'] = 'neutral'


# ── Pricing method enum ──────────────────────────────────────────────────────

class PricingMethod(str, Enum):
    HESTON = "Heston repriced"
    BS_REPRICED = "BS repriced (IV-derived)"
    DELTA_APPROX = "Delta approximation"
    UNAVAILABLE = "Unavailable"


# ── Target levels ─────────────────────────────────────────────────────────────

class TargetLevel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    # AliasChoices lets Pydantic accept both the new camelCase keys (current API)
    # and the old snake_case keys still present in existing DB scan-session JSON.
    targetPrice: float = Field(
        validation_alias=AliasChoices('targetPrice', 'target_price'),
    )
    stockPrice: float = Field(
        validation_alias=AliasChoices('stockPrice', 'stock_price', 'targetPrice', 'target_price'),
    )
    estimatedOptionPrice: float = Field(
        validation_alias=AliasChoices('estimatedOptionPrice', 'estimated_option_price'),
    )
    pricingMethod: PricingMethod = Field(
        validation_alias=AliasChoices('pricingMethod', 'pricing_method'),
    )
    rrContribution: float = Field(
        validation_alias=AliasChoices('rrContribution', 'rr_contribution'),
    )

    @field_validator('pricingMethod', mode='before')
    @classmethod
    def normalize_legacy_pricing_method(cls, value: object) -> object:
        """Accept codes from old persisted scan sessions and emit the current enum.

        'delta-approx' predates the Heston/BS/delta-approx 3-way split — old
        sessions never distinguished a true BS reprice from the crude
        flat-delta fallback, both stored under this one code and always
        displayed as "BS repriced (IV-derived)". Map it to BS_REPRICED, not
        the now-distinct DELTA_APPROX, to preserve that historical display
        rather than silently reclassifying old data."""
        return {
            'heston': PricingMethod.HESTON,
            'delta-approx': PricingMethod.BS_REPRICED,
            'manual': PricingMethod.UNAVAILABLE,
        }.get(value, value) if isinstance(value, str) else value


# ── Trade cards ──────────────────────────────────────────────────────────────

class ContractDetails(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    strike: int
    expiry: str
    right: OptionRight
    mid: float
    delta: float
    theta: float
    ivRank: int
    ivPercentile: Optional[int] = None
    dte: int


class TradeEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    limit: float
    maxFill: float
    orderType: OrderType


class TradeExit(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    invalidation: float
    premiumStop: float
    timeStopDays: int
    target: float                    # KEEP — first target stock price (backward compat)
    targets: list[TargetLevel] = []  # NEW — 3 graduated target levels


class OptionLeg(BaseModel):
    right:  Literal["C", "P"]
    strike: float
    expiry: str
    action: Literal["BUY", "SELL"]
    qty:    int
    bid:    float
    ask:    float


class AlternativeContract(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    symbol:             str
    strike:             int
    expiry:             str
    right:              OptionRight
    dte:                int
    mid:                float
    delta:              float
    theta:              float
    ivRank:             int
    score:              int
    contractConfidence: Status
    contractBreakdown:  ContractScoreBreakdown
    rrRatio:            float
    rrModel:            RrModel
    reason:             str
    spreadType:         Optional[Literal["single", "bear_put", "bear_call"]] = None
    legs:               Optional[list[OptionLeg]] = None
    netDebitCredit:     Optional[float] = None
    maxProfit:          Optional[float] = None
    maxLoss:            Optional[float] = None
    breakeven:          Optional[float] = None


class TradeCardData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    symbol: str
    company: str
    price: float
    direction: Direction
    status: Status
    stockScore: int
    stockConfidence: Status
    stockBreakdown: ScoreBreakdown
    contract: str
    contractScore: int
    contractConfidence: Status
    contractBreakdown: ContractScoreBreakdown
    contractDetails: Optional[ContractDetails] = None
    entry: TradeEntry
    exit: TradeExit
    nextEventDays: Optional[int] = None
    nextEventLabel: Optional[str] = None
    rrRatio: float
    rrModel: RrModel
    finalStatus: Status
    alternatives:      list[AlternativeContract] = []
    alternativesCount: int = 0
    confidence:        Optional[int] = None
    confidenceText:    Optional[str] = None
    sentiment:         Optional[SentimentData] = None
    fundamentals:      Optional[FundamentalsOut] = None
    spreadType:        Optional[Literal["single", "bear_put", "bear_call"]] = None
    legs:              Optional[list[OptionLeg]] = None
    netDebitCredit:    Optional[float] = None
    maxProfit:         Optional[float] = None
    maxLoss:           Optional[float] = None
    breakeven:         Optional[float] = None


# ── Scan ─────────────────────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    universe:    list[str]
    direction:   Direction
    horizon:     Horizon
    overrides:   dict = {}
    # Price / cap filters from Step 1 universe page
    min_price:   Optional[float] = None
    max_price:   Optional[float] = None
    min_cap_usd: Optional[float] = None
    max_cap_usd: Optional[float] = None
    # Holding horizon (calendar days). The backend derives the contract DTE window
    # from these: dte = hold * dte_holding_multiplier. When absent, contract_rules.yaml
    # hard_reject.min_dte/max_dte apply as a fallback.
    hold_min_days: Optional[int] = None
    hold_max_days: Optional[int] = None
    # The HOLDING preset key the trader picked ("Intraday" ... "Annual",
    # "Custom"). Deliberately NOT `horizon` above: that one is the collapsed
    # scoring horizon and is Literal-restricted to three values, so it cannot
    # carry Quarterly/SemiAnnual/Annual/Custom at all. The repricing table in
    # risk_rules.yaml is keyed on this one — the /first-passage endpoint takes
    # the same key under the same name, and the two must match or the Monte
    # Carlo card and the Fixed % Ladder reprice at different horizons.
    # Untyped (plain str) on purpose: an unknown value resolves to Swing rather
    # than 422-ing a whole scan over a display detail.
    horizon_preset: Optional[str] = None
    # Per-scan confidence-gate overrides (snake_case, matching this model's style)
    confidence_caution_below: Optional[int] = None
    confidence_reject_below:  Optional[int] = None
    # Per-scan ATR win/loss barrier override (asymmetric — must be provided
    # together; a lone target or stop is ignored, see routers/scan.py). When
    # both are None, the per-horizon config in scoring_rules.yaml applies.
    confidence_atr_mult_target: Optional[float] = None
    confidence_atr_mult_stop:   Optional[float] = None
    # Per-scan fundamentals-gate overrides
    fundamentals_enabled:        Optional[bool]  = None
    fundamentals_caution_below:  Optional[float] = None
    fundamentals_reject_below:   Optional[float] = None
    fundamentals_de_reject:      Optional[float] = None
    # Per-scan bearish-fundamentals overrides (Step-3 "Fundamentals Bearish"
    # sliders, BEARISH SCANS ONLY) — health score too high to short safely.
    # Mirrors StockScanRequest's fields of the same name (schemas/stock_scan.py).
    fundamentals_caution_above: Optional[float] = None
    fundamentals_reject_above:  Optional[float] = None
    # Bearish spread construction params (used by Pass 2 for bearish candidates)
    spread_width:        float = 5.0
    short_leg_delta:     float = 0.30
    iv_rank_threshold:   float = 50.0
    min_credit:          float = 0.50
    max_debit_pct:       float = 40.0

    @model_validator(mode="after")
    def _validate_hold_days(self) -> "ScanRequest":
        if self.hold_min_days is not None and self.hold_max_days is not None:
            if self.hold_min_days < 0 or self.hold_max_days < 0:
                raise ValueError("hold_min_days and hold_max_days must be non-negative")
            if self.hold_max_days < self.hold_min_days:
                raise ValueError("hold_max_days must be >= hold_min_days")
        return self


class RejectedCandidate(BaseModel):
    symbol: str
    reason: str
    breakdown: dict[str, int] | None = None


class OptionsPipeline(BaseModel):
    scanned:           int   # total symbols attempted
    failed_data:       int   # "no market data" + price/cap filters
    failed_pre_screen: int   # Pass 1 score gate (reason starts with "Pre-screen:")
    no_chain:          int   # "no option chain"
    failed_score:      int   # Pass 2 score gate (reason starts with "Score gate:")
    failed_contracts:  int   # "all contracts rejected"
    candidates:        int   # made it through everything


class DteWindow(BaseModel):
    """The contract expiry window actually enforced for a scan."""
    min_dte:    int
    max_dte:    int
    multiplier: float


class ScanResult(BaseModel):
    scan_id: str
    timestamp: str
    candidates: list[TradeCardData]
    rejected: list[RejectedCandidate]
    state: ScanState = 'COMPLETED'
    previous_run_id: Optional[str] = None
    deltas: list[ScanDelta] = []
    shortlist_truncated: bool = False
    original_count: int = 0
    pipeline: Optional[OptionsPipeline] = None
    direction_banner: Optional[str] = None
    dte_window: Optional[DteWindow] = None


class ScanSessionStatus(BaseModel):
    """Last-run status for a scan session (options or stock mode).

    `status` means different things per mode. For options mode, "running"/
    "stopped" only reflect whether the continuous scan scheduler is toggled
    on/off — a plain one-off scan never transitions through "running", it
    goes straight to "complete". For stock mode, "running" reflects that a
    specific scan request is actively executing right now, and there is no
    "stopped" state (no continuous-scan equivalent exists for stock mode).
    Consumers must not treat the two endpoints' status values as
    interchangeable.
    """
    status: str                     # "idle" | "running" | "complete" | "stopped"
    updated_at: Optional[str] = None
    universe: Optional[list[str]] = None
    direction: Optional[str] = None
    horizon: Optional[str] = None
    strategy: Optional[str] = None  # stock-mode only


# ── Portfolio persistence ─────────────────────────────────────────────────────

class PortfolioPositionCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    recId: str = Field(alias="rec_id")
    symbol: str
    contract: str       # SYMBOL|STRIKE|EXPIRY|C/P
    direction: Direction
    # gt=0: a non-positive entry price is not a price, and it is the DENOMINATOR
    # the router divides premiumStopDollar by to derive the per-position stop.
    # Accepting 0 meant that derivation was skipped and the user's typed dollar
    # stop dropped on the floor, while every other unusable-input path on this
    # endpoint reports itself.
    entryPrice: float = Field(alias="entry_price", gt=0)
    qty: int = Field(default=1)
    entryDate: str = Field(alias="entry_date")
    stop: Optional[float] = None
    structuralStop: Optional[float] = Field(alias="structural_stop", default=None)
    exitPlan: Optional[dict] = Field(alias="exit_plan", default=None)
    targets: list[dict] = []
    dteTotal: Optional[int] = Field(alias="dte_total", default=None)
    portfolioValue: float = Field(alias="portfolio_value", default=50000.0)
    scanStockPrice: Optional[float] = Field(alias="scan_stock_price", default=None)
    tradeCardSnapshot: Optional[dict] = Field(alias="trade_card_snapshot", default=None)
    # Feature 5 (TradeCard Exit-Plan Restructure) — pre-trade max-loss override
    # set on the Arithmetic Profit Target card, carried through at creation
    # time. Mirrors PortfolioPositionUpdate.maxLossOverride, which already
    # supports this field for the post-trade (PATCH) path.
    maxLossOverride: Optional[dict] = Field(alias="max_loss_override", default=None)
    # Piece 4 — per-position premium stop, chosen on the trade card and carried
    # through AT CREATION. Deliberately not update-only: activeTpMethod /
    # resolvedTpPrice live on PortfolioPositionUpdate alone, and repeating that
    # here would mean a trade sent from the card silently falls back to the
    # global on its very first alert. None = inherit the global.
    premiumStopPct: Optional[float] = Field(alias="premium_stop_pct", default=None, gt=0, lt=1)
    # Piece 4 — the DOLLAR premium stop as typed on the trade card. Preferred
    # over premiumStopPct on this path, and the reason it exists: the router
    # REPLACES entry_price with the live quote when there is one, so a fraction
    # derived client-side against the card's mid would be re-anchored to a
    # different price and silently change the dollar stop the user chose. The
    # fraction is therefore derived server-side, against the entry_price that
    # is actually persisted. Bounded only as positive here; the ratio it
    # produces is validated against (0, 1) at the point of derivation, because
    # whether a given dollar amount is a valid stop depends on that entry.
    premiumStopDollar: Optional[float] = Field(alias="premium_stop_dollar", default=None, gt=0)

    def __init__(self, **data):
        # Support both camelCase and snake_case field names
        mapped = {}
        aliases = {
            "rec_id": "recId",
            "entry_price": "entryPrice",
            "entry_date": "entryDate",
            "structural_stop": "structuralStop",
            "exit_plan": "exitPlan",
            "dte_total": "dteTotal",
            "portfolio_value": "portfolioValue",
            "scan_stock_price": "scanStockPrice",
            "trade_card_snapshot": "tradeCardSnapshot",
            "max_loss_override": "maxLossOverride",
            "premium_stop_pct": "premiumStopPct",
            "premium_stop_dollar": "premiumStopDollar",
        }
        for k, v in data.items():
            mapped[aliases.get(k, k)] = v
        super().__init__(**mapped)


class PortfolioPositionUpdate(BaseModel):
    """Partial update for a persisted position — only the fields the drawer
    exposes as editable. A field omitted from the request body is left alone;
    the router distinguishes "omitted" from "explicitly null" via
    `model_dump(exclude_unset=True)`, since `{"structuralStop": null}` must
    still be able to clear a previously-set structural stop.

    `qty` IS `Optional[int]` here too (so `{"qty": null}` still validates and
    is tracked in `model_fields_set`, rather than pydantic rejecting it before
    the router ever sees it) — but unlike `stop`/`structuralStop`, there is no
    meaningful "clear the quantity" operation, so the router does NOT treat a
    present-but-null `qty` as a no-op the way it does for those fields. It
    explicitly checks `qty is None or qty < 1` and returns a clean 422 for
    either case — that guard is load-bearing, not redundant, precisely
    because this field's type alone doesn't rule out `None` reaching it.
    `exclude_unset=True` still means an omitted `qty` key never touches this
    field at all.

    `portfolioValue` is only required by the router when `qty` is being
    increased (it re-runs the exposure gate in that case, same as
    `POST /api/portfolio`); a `qty` decrease or an edit that never sends `qty`
    doesn't need it.

    `exitPlan`, `maxLossOverride`, `activeTpMethod`, `resolvedTpPrice`/
    `resolvedTpUpdatedAt`, and `alertOverrides` are Phase 0 scaffolding for
    the exit-plan pipeline (docs/superpowers/plans/2026-08-26-exit-plan-pipeline.md)
    — no endpoint computes these yet, but the PATCH plumbing to persist
    whatever a later feature computes already exists. Like `structuralStop`,
    `exitPlan`/`maxLossOverride`/`alertOverrides` follow the exclude_unset
    pattern so `{"exitPlan": null}` can still explicitly clear a previously
    computed value."""
    model_config = ConfigDict(populate_by_name=True)

    stop: Optional[float] = None
    structuralStop: Optional[float] = Field(alias="structural_stop", default=None)
    targets: Optional[list[dict]] = None
    qty: Optional[int] = None
    portfolioValue: Optional[float] = Field(alias="portfolio_value", default=None)
    exitPlan: Optional[dict] = Field(alias="exit_plan", default=None)
    maxLossOverride: Optional[dict] = Field(alias="max_loss_override", default=None)
    activeTpMethod: Optional[TpMethod] = Field(alias="active_tp_method", default=None)
    resolvedTpPrice: Optional[float] = Field(alias="resolved_tp_price", default=None)
    resolvedTpUpdatedAt: Optional[str] = Field(alias="resolved_tp_updated_at", default=None)
    alertOverrides: Optional[dict] = Field(alias="alert_overrides", default=None)
    # Piece 4 — editable post-entry from the Portfolio drawer. Follows the same
    # exclude_unset pattern as stop/structuralStop: an omitted key leaves the
    # value alone, while an explicit null CLEARS the override and returns the
    # position to inheriting the global.
    premiumStopPct: Optional[float] = Field(alias="premium_stop_pct", default=None, gt=0, lt=1)


class PortfolioPositionSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    id: str
    recId: str
    symbol: str
    contract: str
    direction: Direction
    entryPrice: float
    qty: int
    # Set only on the POST /api/portfolio response, when the risk check
    # auto-reduced the requested qty to fit exposure limits — `qty` above
    # already reflects the adjusted value; this tells the caller it differs
    # from what was requested, rather than silently applying a different size.
    adjustedQty: Optional[int] = None
    entryDate: str
    stop: Optional[float] = None
    structuralStop: Optional[float] = None
    targets: list[dict] = []
    dteTotal: Optional[int] = None
    createdAt: str
    # Live fields — populated by GET /portfolio via Tradier option quote
    currentPrice: float = 0.0
    currentStockPrice: Optional[float] = None   # live underlying price (options only; equals currentPrice for stock legs)
    pnlDollar: float = 0.0
    pnlPct: float = 0.0
    dteRemaining: int = 0
    delta: Optional[float] = None
    theta: Optional[float] = None
    ivRank: Optional[int] = None
    # Exit-plan pipeline (docs/superpowers/plans/2026-08-26-exit-plan-pipeline.md)
    # — Phase 0 scaffolding, populated by later phases.
    exitPlan: Optional[dict] = None
    maxLossOverride: Optional[dict] = None
    activeTpMethod: TpMethod = 'ladder'
    resolvedTpPrice: Optional[float] = None
    resolvedTpUpdatedAt: Optional[str] = None
    alertOverrides: dict = {}
    # Piece 4 — None means this position inherits the global premium stop. The
    # frontend renders that difference ("60% (global)" vs "45%"), so it must
    # survive the round trip rather than being resolved server-side.
    premiumStopPct: Optional[float] = None

    @classmethod
    def from_orm_model(cls, obj) -> "PortfolioPositionSchema":
        return cls(
            id=str(obj.id),
            recId=obj.rec_id,
            symbol=obj.symbol,
            contract=obj.contract,
            direction=obj.direction,
            entryPrice=obj.entry_price,
            qty=obj.qty,
            entryDate=obj.entry_date,
            stop=obj.stop,
            structuralStop=obj.structural_stop,
            targets=obj.targets or [],
            dteTotal=obj.dte_total,
            createdAt=obj.created_at.isoformat() if obj.created_at else "",
            exitPlan=obj.exit_plan,
            maxLossOverride=obj.max_loss_override,
            activeTpMethod=obj.active_tp_method or 'ladder',
            resolvedTpPrice=obj.resolved_tp_price,
            resolvedTpUpdatedAt=obj.resolved_tp_updated_at.isoformat() if obj.resolved_tp_updated_at else None,
            alertOverrides=obj.alert_overrides or {},
            premiumStopPct=obj.premium_stop_pct,
        )


class ClosePositionRequest(BaseModel):
    """Body for POST /api/portfolio/{rec_id}/close."""
    model_config = ConfigDict(populate_by_name=True)
    qtyToClose: Optional[int] = None        # None -> close the whole position
    exitPrice: Optional[float] = None       # None -> server fetches the live quote
    exitDate: Optional[str] = None          # None -> today (YYYY-MM-DD)
    # Reserved for the future broker feature (see router stub) — inactive for now.
    sendToBroker: bool = False


class ClosedPositionSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)
    id: str
    recId: str
    symbol: str
    contract: str
    direction: Direction
    entryPrice: float
    entryDate: Optional[str] = None
    exitPrice: float
    exitDate: str
    qtyClosed: int
    realizedPnlDollar: float
    realizedPnlPct: float
    closedAt: str

    @classmethod
    def from_orm_model(cls, obj) -> "ClosedPositionSchema":
        return cls(
            id=str(obj.id),
            recId=obj.rec_id,
            symbol=obj.symbol,
            contract=obj.contract,
            direction=obj.direction,
            entryPrice=obj.entry_price,
            entryDate=obj.entry_date,
            exitPrice=obj.exit_price,
            exitDate=obj.exit_date,
            qtyClosed=obj.qty_closed,
            realizedPnlDollar=obj.realized_pnl_dollar,
            realizedPnlPct=obj.realized_pnl_pct,
            closedAt=obj.closed_at.isoformat() if obj.closed_at else "",
        )


class PerformancePoint(BaseModel):
    date: str
    value: float


class PerformanceResponse(BaseModel):
    realizedToday: float = 0.0
    realizedWeek: float = 0.0
    realizedMonth: float = 0.0
    realizedYear: float = 0.0
    realizedCurve: list[PerformancePoint] = []   # cumulative realized profit line
    equityCurve: list[PerformancePoint] = []      # total account value line (from snapshots)
    openPnlCurve: list[PerformancePoint] = []     # unrealized P&L of open positions (from snapshots)
