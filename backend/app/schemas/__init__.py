from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict

# ── Shared literals ──────────────────────────────────────────────────────────

Status = Literal['PASS', 'CAUTION', 'REJECT', 'PENDING', 'NO_DATA']
Direction = Literal['Bullish', 'Bearish']
Horizon = Literal['Swing', 'Position']
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


# ── Events ───────────────────────────────────────────────────────────────────

class UpcomingEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    date: str
    symbol: str
    label: str
    status: Status


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
    target: float


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
    rrRatio: float
    rrModel: RrModel
    finalStatus: Status


# ── Scan ─────────────────────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    universe: list[str]
    direction: Direction
    horizon: Horizon
    overrides: dict = {}


class RejectedCandidate(BaseModel):
    symbol: str
    reason: str


class ScanResult(BaseModel):
    scan_id: str
    timestamp: str
    candidates: list[TradeCardData]
    rejected: list[RejectedCandidate]
