from __future__ import annotations
from enum import Enum
from typing import Literal, Optional
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

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
RrModel = Literal['Heston repriced', 'Delta approximation']

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


class ContractScoreBreakdown(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    dteFit: int
    delta: int
    ivAttractiveness: int
    liquidity: int
    spread: int


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


# ── Sectors ──────────────────────────────────────────────────────────────────

class SectorTile(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
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


class RejectedCandidate(BaseModel):
    symbol: str
    reason: str
    breakdown: dict[str, int] | None = None


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


# ── Portfolio persistence ─────────────────────────────────────────────────────

class PortfolioPositionCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    recId: str = Field(alias="rec_id", default=None)
    symbol: str
    contract: str       # SYMBOL|STRIKE|EXPIRY|C/P
    direction: str
    entryPrice: float = Field(alias="entry_price", default=None)
    qty: int = Field(default=1)
    entryDate: str = Field(alias="entry_date", default=None)
    stop: Optional[float] = None
    targets: list[dict] = []
    dteTotal: Optional[int] = Field(alias="dte_total", default=None)
    portfolioValue: float = Field(alias="portfolio_value", default=50000.0)

    def __init__(self, **data):
        # Support both camelCase and snake_case field names
        mapped = {}
        aliases = {
            "rec_id": "recId",
            "entry_price": "entryPrice",
            "entry_date": "entryDate",
            "dte_total": "dteTotal",
            "portfolio_value": "portfolioValue",
        }
        for k, v in data.items():
            mapped[aliases.get(k, k)] = v
        super().__init__(**mapped)


class PortfolioPositionSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    id: str
    recId: str
    symbol: str
    contract: str
    direction: str
    entryPrice: float
    qty: int
    entryDate: str
    stop: Optional[float] = None
    targets: list[dict] = []
    dteTotal: Optional[int] = None
    createdAt: str
    # Live fields — populated by GET /portfolio via Tradier option quote
    currentPrice: float = 0.0
    pnlDollar: float = 0.0
    pnlPct: float = 0.0
    dteRemaining: int = 0
    delta: Optional[float] = None
    theta: Optional[float] = None
    ivRank: Optional[int] = None

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
            targets=obj.targets or [],
            dteTotal=obj.dte_total,
            createdAt=obj.created_at.isoformat() if obj.created_at else "",
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
    direction: str
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
