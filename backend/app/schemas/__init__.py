from __future__ import annotations
from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

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

class ScoreBreakdown(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    trend: int
    pullback: int
    trigger: int
    event: int
    volatility: int


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


class MarketRegime(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    overall: Status
    headline: str
    metrics: list[RegimeMetric]


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


# ── Pricing method enum ──────────────────────────────────────────────────────

class PricingMethod(str, Enum):
    HESTON = "Heston repriced"
    DELTA_APPROX = "Delta approximation"
    UNAVAILABLE = "Unavailable"


# ── Target levels ─────────────────────────────────────────────────────────────

class TargetLevel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    targetPrice: float           # underlying stock price at this target
    stockPrice: float            # alias of targetPrice (keep for backward compat)
    estimatedOptionPrice: float
    pricingMethod: PricingMethod
    rrContribution: float        # estimated reward at this target / risk


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
    universe: list[str]
    direction: Direction
    horizon: Horizon
    overrides: dict = {}


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
