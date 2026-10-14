from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, Optional
from pydantic import (
    AfterValidator, AliasChoices, BaseModel, ConfigDict, Field, StringConstraints,
    field_validator, model_validator,
)

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
# Phase G (piece 5) — the method a trader EXPLICITLY picked for a trade, and
# which stop it was judged on. NOT the same axis as TpMethod above: TpMethod is
# method -> ALERT ROW and is post-trade (the EditDrawer writes it); PickedMethod
# is the pre-trade human decision, and it SEEDS TpMethod at creation via
# services.picked_method.seed_tp_from_pick. Also not RrModel, which is the
# pricer. Three similar-sounding names, three different axes.
PickedMethod = Literal['arithmetic', 'monte_carlo', 'ladder', 'barrier_race']
PickedStopBasis = Literal['stock', 'premium']


def _aware_iso_timestamp(value: str) -> str:
    """P6 (G1-9): `pickedAt` must be a timezone-aware ISO 8601 timestamp.

    The only producer is the frontend's `new Date().toISOString()`
    (`2026-09-30T12:00:00.000Z`), which Python 3.11's fromisoformat reads as
    UTC. Stored AS SENT -- validated, not normalised -- so the column and every
    reader are unchanged. Naive is refused because the field exists to age a
    pick, and a naive timestamp cannot be compared against a clock."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError('pickedAt must be an ISO 8601 timestamp') from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('pickedAt must carry a timezone (e.g. a trailing Z)')
    return value


# Shared by PortfolioPositionCreate.pickedAt and ArmRequest.picked_at, and it
# has to be: a fired auto-trade books through PortfolioPositionCreate AFTER its
# broker order is placed, so a constraint only the create schema carried would
# turn a bad arm into an order with no tracked position. Refusing it at ARM is
# the point.
PickedAt = Annotated[str, StringConstraints(max_length=64), AfterValidator(_aware_iso_timestamp)]

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
    # Which quantity `iv_rank` holds, exactly as on IvRankDetail below. The
    # STOCK score's volatility rule carries the same figure the CONTRACT rule
    # does, and only the contract half was converted in the first pass -- so
    # scoreDetailText printed "IV Rank 45" for a 45% ABSOLUTE IV on every
    # default-path scan, which is the literal defect statement of
    # PHASE-A-NULL-IVRANK-2026-09-06. stock_scorer._rule_vol has emitted the
    # basis in its detail dict since that change; this is the field that lets
    # it reach the wire instead of being dropped by _safe(VolDetail, ...).
    iv_basis: Literal["rank", "absolute", "none"] = "absolute"
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
    # Which quantity `iv_rank` holds: "rank" (an IV rank from IBKR or
    # tastytrade), "absolute" (implied volatility 0-100), or "none". Lets the
    # UI label the figure honestly rather than printing an absolute IV under
    # the words "IV rank" (PHASE-A-NULL-IVRANK-2026-09-06).
    iv_basis: Literal["rank", "absolute", "none"] = "absolute"
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


class BlockerComparison(BaseModel):
    model_config = ConfigDict(populate_by_name=True, allow_inf_nan=False)
    code: str
    label: str
    metric: str
    observed: float | int | str | None = None
    threshold: float | int | str
    operator: str


class ComponentExplanation(BaseModel):
    model_config = ConfigDict(populate_by_name=True, allow_inf_nan=False)
    name: str
    wire_name: str
    raw_score: int
    weight: float
    contribution: float
    lost_points: float
    observed: float | int | None = None
    observed_unit: str = ""
    basis: Literal["rank", "absolute", "none"] | None = None
    preferred_min: float | int | None = None
    preferred_max: float | int | None = None
    flags: list[str] = Field(default_factory=list)
    volume: int | None = None
    open_interest: int | None = None
    preferred_volume_min: int | None = None
    preferred_oi_min: int | None = None


class ContractExplanation(BaseModel):
    model_config = ConfigDict(populate_by_name=True, allow_inf_nan=False)
    version: int = 1
    contract_id: str
    evaluated_at: str
    outcome: Literal["blocked", "aggregate"]
    score: int
    status: Status
    unrounded_score: float | None = None
    rounded_score: int | None = None
    pass_threshold: float
    caution_threshold: float
    weights: dict[str, float]
    components: dict[str, ComponentExplanation]
    largest_losses: list[ComponentExplanation]
    blockers: list[BlockerComparison]
    reject_reasons: list[str] = Field(default_factory=list)
    soft_flags: list[str] = Field(default_factory=list)
    soft_fail_count: int
    max_soft_fail_count: int
    hard_bounds: dict[str, float] = Field(default_factory=dict)
    raw_inputs: dict[str, float | None] = Field(default_factory=dict)


class StockComponentEvidence(BaseModel):
    name: str
    wire_name: str
    raw_score: int
    status: Status
    measured: bool
    weight: float
    contribution: float
    detail: dict
    config: dict


class StockCapEvidence(BaseModel):
    name: str
    status: Status
    before: Status
    after: Status
    detail: dict
    config: dict


class StockExplanation(BaseModel):
    """Read-only scan-time evidence; absent on legacy cards, never backfilled."""
    version: Literal[1] = 1
    symbol: str
    direction: Direction
    horizon: Horizon
    scoring_mode: Literal["stock", "options"]
    iv_basis: str
    evaluated_at: str
    score: int
    status: Status
    raw_status: Status
    unrounded_score: float
    rounding: Literal["python_round_ties_to_even"]
    pass_threshold: float
    caution_threshold: float
    weights: dict[str, float]
    components: dict[str, StockComponentEvidence]
    caps: list[StockCapEvidence]
    gate_config: dict[str, dict | None]


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
    # TWO DIFFERENT QUANTITIES, either of which may be absent
    # (PHASE-A-NULL-IVRANK-2026-09-06):
    #   ivRank -- an IV RANK, where today's IV sits in this name's own
    #             52-week range. Only IBKR and tastytrade supply one, so it is
    #             None on most chains.
    #   iv     -- ABSOLUTE implied volatility, 0-100, for THIS strike.
    # Until 2026-09-06 the absolute figure was written into `ivRank`, so the UI
    # printed a 45% IV as "IV rank 45". Consumers must prefer the rank, fall
    # back to `iv`, and LABEL WHICH ONE they are showing.
    # ROUND 6 finding 8. The per-component breakdown for THIS contract. The
    # scorer already produces it (ContractScoreCard.breakdown) and /api/contracts
    # discarded it, so a user who picked a contract in Step 6 got the new
    # contract's composite score over the AUTO-PICKED one's five component
    # scores and detail lines -- including a quantitative "IV 62% - pref <=55%"
    # for a different strike. Returned so the override can carry it across.
    breakdown: Optional[ContractScoreBreakdown] = None
    ivRank: Optional[int] = None
    iv: Optional[float] = None
    ivPercentile: Optional[int] = None
    spread: float
    volume: int
    score: int
    contractConfidence: Status
    explanation: Optional[ContractExplanation] = None
    # NO-LIVE-QUOTE (plan 3c): /api/contracts grades in label mode, so a row
    # whose quote is not live comes back capped at CAUTION with these set from
    # the score card. quoteState: 'one_sided' | 'session_closed' | 'stale';
    # None on a live row.
    noLiveQuote: bool = False
    quoteState: Optional[str] = None


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
    avg_regime_duration: float       # 1 / (1 − p_stay), transition strides
    duration_stride_bars: Optional[int] = None
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
    # PREMIUM_STOP only -- the premium-stop fraction this alert actually fired
    # at (ALERT-THRESHOLD-STAMP-2026-09-05). `referenceValue` already carries
    # the threshold PRICE; this is the percentage beside it, and it is the
    # RESOLVED per-position value, never the global. Matches the frontend
    # engine's `ToastItem.premiumStopPct` and the `thresholdPct` this generator
    # already writes to the event log, so a row cannot mean one thing depending
    # on which engine produced it.
    #
    # None on every other alert type, and on any PREMIUM_STOP predating this
    # field -- the Alerts page falls back to resolving it live for those.
    premiumStopPct: Optional[float] = None
    # PREMIUM_STOP only -- the side rule it fired under: 'short-stock' (fires
    # on a RISE), 'long-stock' or 'option' (STOP-SEMANTICS-2026-10-02). Also
    # selects the notifier's dedup key, so a short's rise-side fire never
    # inherits dedup state written under the old fall-side rule.
    stopSide: Optional[str] = None


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
    # See OptionContract above — a percentile when one exists, else None, with
    # the absolute level in `iv` (PHASE-A-NULL-IVRANK-2026-09-06).
    ivRank: Optional[int] = None
    iv: Optional[float] = None
    ivPercentile: Optional[int] = None
    dte: int


class TradeEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    limit: float
    maxFill: float
    orderType: OrderType


class FinalStopOut(BaseModel):
    """Provenance for the stock stop the scan already resolved (piece 3).

    `TradeExit.invalidation` carries the NUMBER; this block says where it came
    from, so the "Bottom (final stop)" row can render before the user has
    pressed Compute Arithmetic Plan. Every field mirrors the corresponding one
    on `ExitPlanStopOut`, which the endpoint version of this row already reads.

    NOT PRESENT here, and deliberately: `contractPrice`, `rrModel` and
    `structuralConfidence`. The first two need a contract repriced AT the stop,
    which is a per-contract question the scan's auto-pick does not settle (a
    Step 6 override replaces the contract without moving this stop); the
    contract-priced sub-cells and the risk-derived size render "—" until an
    Arithmetic Plan is computed. `structuralConfidence` is omitted because
    nothing on the card reads it outside the endpoint's own block.
    """
    model_config = ConfigDict(populate_by_name=True)
    price: float
    source: Literal["final_stop", "flat_fallback"]
    # 'final_stop' rows carry compute_final_stop's own source; 'flat_fallback'
    # rows carry None, because no structural/ATR comparison was ever made.
    stopSource: Optional[Literal["structural", "atr_widened"]] = None
    structuralSource: Optional[Literal["order_block", "swing_low", "swing_high"]] = None
    # The raw structural candidate, whether or not it decided `price`.
    structuralPrice: Optional[float] = None
    # The ATR floor, whether or not it decided `price`. None on flat_fallback.
    atrFloorPrice: Optional[float] = None
    # |structuralPrice - atrFloorPrice|; None when there was no structural
    # candidate at all, or on the flat_fallback path.
    distanceDollar: Optional[float] = None
    # ATR(14) the floor was built on. 0.0 on the flat_fallback path — which is
    # exactly why that path exists.
    atr: float = 0.0
    # ISO-8601 UTC. Server-set, unlike ExitPlan.computedAt (client-set on
    # receipt), because this one rides on a scan result that IS persisted and
    # replayed: a restored card must be able to say how old its stop is.
    computedAt: str


class FinalStopIn(FinalStopOut):
    """Request-only FinalStopOut (NUMERIC-API-INPUTS T2): the block a card
    round-trips into POST /contracts/recompute-plan, where a non-finite
    number is a 422. FinalStopOut itself stays unguarded: exit_plan.py builds
    it and every response returns it. A FinalStopIn echoed into a
    FinalStopOut-typed response field serialises with the parent's fields."""
    model_config = ConfigDict(populate_by_name=True, allow_inf_nan=False)


class TradeExit(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    # PIECE 3: the resolved stock stop — the wider of the structural level and
    # a 2xATR floor — not a flat percentage move. See `finalStop` below for
    # which branch produced it.
    invalidation: float
    premiumStop: float
    timeStopDays: int
    target: float                    # KEEP — first target stock price (backward compat)
    targets: list[TargetLevel] = []  # NEW — 3 graduated target levels
    # ABSENT means "this card predates piece 3" — a scan session persisted
    # before it shipped, replayed through /scan/last-run. It must never render
    # as a computed stop; the card reads "not computed — re-run the scan".
    stockStopLoss: float | None = None
    stockStopLossAt: float | None = None
    rrRiskBasis: Literal["premium_stop", "stock_stop", "full_premium"] | None = None
    targetSource: Literal["structural_snap", "arithmetic", "flat_fallback", "capped"] | None = None
    finalStop: Optional[FinalStopOut] = None


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
    # See OptionContract above (PHASE-A-NULL-IVRANK-2026-09-06).
    ivRank:             Optional[int] = None
    iv:                 Optional[float] = None
    score:              int
    contractConfidence: Status
    contractBreakdown:  ContractScoreBreakdown
    contractExplanation: Optional[ContractExplanation] = None
    rrRatio:            float
    rrModel:            RrModel
    reason:             str
    spreadType:         Optional[Literal["single", "bear_put", "bear_call"]] = None
    legs:               Optional[list[OptionLeg]] = None
    netDebitCredit:     Optional[float] = None
    maxProfit:          Optional[float] = None
    maxLoss:            Optional[float] = None
    breakeven:          Optional[float] = None


class RegimeGateSnapshot(BaseModel):
    """The two headwind thresholds a scan RESOLVED (YAML overlaid by Step 3).

    Only the two per-run thresholds, deliberately: `enabled` and
    `require_stable_for_reject` are config, not per-scan parameters, and are
    not overridable by any caller (see services/regime_gate.py).

    A None value means the resolved block itself carried no such key, which
    the fire path reads exactly as the scan did -- from scoring_rules.yaml.
    """
    headwindCautionPct: Optional[float] = None
    headwindRejectPct:  Optional[float] = None


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
    stockExplanation: Optional[StockExplanation] = None
    contract: str
    contractScore: int
    contractConfidence: Status
    contractBreakdown: ContractScoreBreakdown
    contractExplanation: Optional[ContractExplanation] = None
    contractDetails: Optional[ContractDetails] = None
    entry: TradeEntry
    exit: TradeExit
    nextEventDays: Optional[int] = None
    nextEventLabel: Optional[str] = None
    rrRatio: float
    rrModel: RrModel
    finalStatus: Status
    unvalidatedReason: Optional[str] = None
    # Fix #3: earnings inside the reject window -> finalStatus REJECT and no send.
    earningsVeto: bool = False
    # Unknown earnings (none on file, or only a past date). D4 amended
    # 2026-10-03: on a single stock (isEtf False) finalStatus is capped at
    # CAUTION; an ETF is unaffected. The cap is display/ranking only -- the
    # auto-trader never reads this card; its OWN fire-time lookup is what
    # refuses (auto_trader._apply_event_veto; audit round 1, F7).
    earningsUnknown: bool = False
    # Membership in the curated ETF set (app/data/etfs.py). False for any
    # symbol not in it -- the safe direction (treated as a stock).
    isEtf: bool = False
    # Days to EARNINGS alone (nextEventDays is the nearer of earnings/dividend).
    earningsDays: Optional[int] = None
    # NO-LIVE-QUOTE (plan 3c): carries a Step 6 pick's flag onto the card. A
    # scan card is built only from contracts that were live WHEN THE SCAN RAN
    # (reject mode), so the scan always leaves this False -- which is never
    # proof that the quote is live now (the result is persisted).
    noLiveQuote: bool = False
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

    # ── The stop-vs-premium gate, priced at SCAN time (Phase B3) ─────────────
    # docs/superpowers/plans/2026-09-02-gate-basis-spec.md §2.3. TWO fields,
    # not five, and this is load-bearing rather than terse: `WatchlistRow`
    # carries no contract data at all, so shipping strike/dte/premium/iv/delta
    # down to let the ranking table price the gate itself would be the
    # rejected "Black-Scholes in TypeScript" decision arriving by the back
    # door. The badge renders a verdict the backend already reached.
    #
    # They describe the AUTO-PICKED contract, which a Step 6 override can
    # later replace -- the ranking table must say so, because after such an
    # override the row's badge and the card's badge legitimately describe two
    # different contracts.
    #
    # None means NOT COMPUTED and must never render as a PASS: no structural
    # or ATR stop could be formed (a flat or too-short candle feed), the IV
    # would not invert out of the mid, the contract expires inside a day, or
    # the row was restored from a scan session written before this shipped.
    stopCostPct:    Optional[float] = None
    stopCostStatus: Optional[Literal["PASS", "CAUTION"]] = None

    # ── The regime-gate rule THIS card's scan ran under ─────────────────────
    # Decision AUTOTRADE-ARMED-TRADE-JUDGED-BY-ITS-SCANS-RULE-2026-09-21: an
    # armed trade is judged by the rule its own scan resolved, not by whatever
    # Step 3 says at the moment Arm is pressed. The arm payload reads its
    # thresholds from HERE, so they travel with the card -- through a reload
    # (scanStore persists the result), a Step-3 edit or reset (which never
    # touches a card), and a restart that changes scoring_rules.yaml (the
    # numbers are the RESOLVED ones, YAML already overlaid).
    #
    # None means the card was produced before this field existed (an older
    # persisted or DB-restored scan); the Arm button refuses such a card rather
    # than guess which rule its scan used.
    regimeGate: Optional[RegimeGateSnapshot] = None


# ── Scan ─────────────────────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    # NUMERIC-API-INPUTS T2: every float is finite or a 422 -- also when a
    # stored schedule entry is re-validated (the scheduler records a failed
    # run; GET /api/scan-schedule skips the entry with a warning).
    model_config = ConfigDict(allow_inf_nan=False)

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
    # Per-scan regime-gate overrides — the Step-3 "Headwind caution %" /
    # "Headwind reject %" controls. Same names, same type, same None-means-YAML
    # semantics as StockScanRequest's pair (schemas/stock_scan.py:60-61).
    #
    # ADDED 2026-09-19 as the OPTIONS half of a control that was only ever wired
    # to the STOCK scan. Step 3 is shared by both modes and shows these two in
    # every mode, so setting "Headwind reject %" and running an OPTIONS scan
    # changed nothing at all. That matters now rather than merely being untidy:
    # the auto-trader snapshots these onto the armed trade and applies them at
    # fire (AUTOTRADE-GATE-INPUTS-FRESH-PER-SYMBOL-2026-09-19), and the only
    # producer of an armed trade is the OPTIONS trade card. Without this the
    # snapshot would carry a threshold the scan behind the card never used --
    # re-creating the scan-versus-fire disagreement in the other direction.
    #
    # DEFAULTS ARE THE YAML VALUES (-15 / -40, executionParamDefaults.ts:37), so
    # an untouched Step-3 panel leaves this scan's behaviour BYTE-IDENTICAL. It
    # bites only when the trader deliberately moves the control, which is what
    # the control is for.
    regime_headwind_caution_pct: Optional[float] = None
    regime_headwind_reject_pct:  Optional[float] = None
    # Bearish spread construction params (used by Pass 2 for bearish candidates)
    spread_width:        float = 5.0
    short_leg_delta:     float = 0.30
    iv_rank_threshold:   float = 50.0   # applies when an IV RANK is in hand
    # Applies when only an ABSOLUTE IV is in hand, which is most chains. It is a
    # separate knob because 50% IV and the 50th percentile are different claims.
    # UNMEASURED, like the percentile seeds and Q7.
    #
    # None means ABSENT FROM THE REQUEST, not 50: a body built before
    # PHASE-A-SPREAD-BASIS-2026-09-06 carries only `iv_rank_threshold`, and those
    # bodies are still out there -- schedule entries persist a fully resolved
    # request server-side (schemas/scan_schedule.py) and are only rewritten when
    # the profile behind them is re-saved. Defaulting such a body to 50 would
    # discard the user's own setting and, on a Tradier-only chain, flip
    # choose_primary from bear_put (debit, long premium) to bear_call (credit,
    # short premium, assignment exposure) -- round 1's finding (d) surviving in
    # the one path that never re-resolves. `_seed_iv_abs_threshold` below applies
    # exactly the rule settingsStore's v23->v24 migration applies client-side.
    iv_abs_threshold:    Optional[float] = None
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

    @model_validator(mode="after")
    def _seed_pre_split_iv_knobs(self) -> "ScanRequest":
        """A pre-split request means its single knob for the chains it actually saw.

        Before PHASE-A-SPREAD-BASIS/NULL-IVRANK-2026-09-06 one threshold was
        applied to whichever figure was in hand, and on most chains that figure
        is the ABSOLUTE one -- so a body naming only the rank knob was, in
        practice, setting the absolute cut-off. Seeding preserves that intent;
        falling back to the class default silently overrules a user who moved it.

        `iv_abs_threshold` doubles as the PRE-SPLIT MARKER for this body. Every
        current client sends it (the frontend type makes it required), so its
        absence means the body was built before the split -- which matters
        because the second knob cannot be tested for absence on its own:
        `overrides` is a SPARSE dict, so a current client that edited only the
        Step-3 "IV rank pass max" row legitimately sends `iv_rank_pass_max` with
        no `iv_abs_pass_max`, and seeding that would apply a ceiling the user
        never asked for. Gating on the marker keeps the seeding to bodies that
        genuinely predate the split.

        Why it is needed at all: a schedule entry persists a fully resolved
        request server-side (schemas/scan_schedule.py) and rewrites it only when
        the profile behind it is re-saved, so pre-split bodies keep running
        unattended. `stock_scorer._rule_vol` reads `iv_abs_pass_max` whenever the
        basis is not 'rank', and the two keys deliberately do not leak across
        bases -- so a stored `iv_rank_pass_max` is simply inert on most chains.
        """
        if self.iv_abs_threshold is not None:
            return self  # a current client; nothing to seed

        self.iv_abs_threshold = self.iv_rank_threshold

        ov = self.overrides
        if isinstance(ov, dict):
            rank_max = ov.get("iv_rank_pass_max")
            if isinstance(rank_max, (int, float)) and not isinstance(rank_max, bool):
                if ov.get("iv_abs_pass_max") is None:
                    self.overrides = {**ov, "iv_abs_pass_max": rank_max}
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
    # The residual: anything in `rejected` that matched none of the buckets
    # above. Mostly per-symbol EXCEPTIONS, which routers/scan.py records as
    # `reason=str(result)` -- frequently the empty string for httpx/asyncio
    # errors, so it matches no predicate and would otherwise vanish. Without
    # this bucket the funnel silently loses every symbol on a PARTIAL/FAILED
    # run, which is the same class of hole `failed_direction` was added to
    # close. Mirrors StockPipeline.other_rejected.
    #
    # Optional for the same reason as the two below, and it must be: defaulting
    # it to 0 would let a legacy blob claim it saw zero exceptions, which is
    # precisely the fabricated reading that default is rejected for there.
    other_rejected:    Optional[int] = None
    # None means ABSENT, not zero. A PERSISTED v2 blob predates these fields;
    # its `candidates` was snapshotted BEFORE the direction-conviction filter
    # and the shortlist cap ran, so it can over-report. Defaulting to 0 would
    # let such a blob positively assert "nothing was gated" -- fabricating a
    # reading rather than admitting the count is unaccounted for. The frontend
    # omits the stage entirely when the value is None.
    #
    # Deliberately NOT a SCAN_RESULT_SCHEMA_VERSION bump, though `candidates`
    # does change meaning. The two bumps above were safety-critical: a stored
    # price or stop silently denominated in something other than its name, with
    # the basis unrecoverable. These are display counters for the Step-3 funnel
    # -- nothing sizes, prices or gates a trade off them -- so the cost of a
    # bump (the guard refuses EVERY stored v2 result, discarding real scan
    # history) buys nothing a stale funnel count does not already cost. The
    # None-vs-0 distinction is what keeps that cheaper choice honest.
    failed_direction:  Optional[int] = None  # removed by the direction-conviction gate
    failed_shortlist:  Optional[int] = None  # trimmed by the shortlist cap (see original_count)
    # The direction gate's "no data" removals (trend UNMEASURED), counted apart
    # from failed_direction (a measured trend below the floor), as
    # StockPipeline does. Removed right after the pre-screen, before the chain
    # fetch -- so the funnel places this stage there, not beside
    # failed_direction. None = a result stored before the field existed, whose
    # failed_direction still includes these.
    failed_direction_unmeasured: Optional[int] = None
    # The direction-conviction floor THIS scan applied; None = exempt horizon
    # (or a result stored before the field existed).
    direction_min_trend: Optional[float] = None
    candidates:        int   # made it through everything, after every filter


class EventWindow(BaseModel):
    """The earnings/dividend proximity window the scan's event rule applied
    (scoring_rules.yaml horizon default, replaced by any request override)."""
    reject_days:  int
    caution_days: int
    # Separate earnings gate; absent on results saved before hold-aware vetoes.
    veto_days: Optional[int] = None


class DteWindow(BaseModel):
    """The contract expiry window actually enforced for a scan."""
    min_dte:    int
    max_dte:    int
    multiplier: float


# Bumped when a change makes a PERSISTED ScanResult unreadable by the current
# code -- i.e. when a stored blob's fields no longer mean what they say.
#
#   1  post-PHASE-A-NULL-IVRANK-2026-09-06. Before it, `ivRank` held raw
#      implied volatility under a percentile's name.
#   2  post-PIECE-3-2026-09-09. Before it, `exit.invalidation` held a flat
#      percentage move off the stock price under the resolved structural+2xATR
#      stop's name -- and `exit.finalStop`, the block that would say which,
#      did not exist. A v1 blob is therefore indistinguishable from a piece-3
#      scan whose bar feed was too thin to resolve a stop, so the basis is not
#      recoverable and the blob is refused rather than relabelled.
#   3  options R/R on the full-premium basis (Phase C T9, TRADING-REVIEW-
#      PHASE-C-RR). Before it, `rrRatio` / `targets[].rrContribution` divided
#      reward by the premium stop (premium x 0.60) or the captured stock-stop
#      loss, and the field names did not change -- so a v2 ratio overstates
#      reward per unit of real risk by at least 1/0.6 under the new reading.
#      Refused, and the frontend's scanStore v18 branch discards its own copy.
#
# EVERY CONSUMER COMPARES, none tests `is None`. A stored result is trustworthy
# only when its version is at least this one: `(blob.schema_version or 0) <
# SCAN_RESULT_SCHEMA_VERSION` refuses it. Testing for None was what let piece 3
# ship a v1 blob straight through three endpoints -- the guard only knew about
# the ONE bump that existed when it was written, so the next one was silently
# exempt. Written as a comparison, the next bump is honoured everywhere for
# free.
SCAN_RESULT_SCHEMA_VERSION = 3


class ScanRequestContext(BaseModel):
    """The ScanRequest fields echoed on its ScanResult (see request_context)."""
    universe:       list[str]
    direction:      Direction
    horizon:        Horizon
    horizon_preset: Optional[str] = None
    hold_min_days:  Optional[int] = None
    hold_max_days:  Optional[int] = None


class ScanResult(BaseModel):
    report_run_id: Optional[str] = None
    report_generation: Optional[int] = None
    report_persistence: Optional[Literal["saved", "unavailable"]] = None
    scan_id: str
    timestamp: str
    # Absent means PRE-SPLIT. A scan result is persisted to `scan_sessions`
    # (routers/scan.py restore_from_db) and re-served by /scan/last and
    # /api/tradecards, and one written before the split holds raw implied
    # volatility x100 under `ivRank` -- the name of a percentile. Nothing on the
    # record says which quantity it is, exactly as for the localStorage blobs
    # round 1 addressed, and the basis is no more recoverable here. The frontend
    # migration DROPS such a figure rather than relabelling it; the server does
    # the same by refusing to restore the blob at all, because it is stale market
    # data from before an upgrade and re-scanning costs nothing.
    schema_version: Optional[int] = None
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
    # Absent on results persisted before 2026-09-29; the UI then falls back to
    # the horizon's YAML window.
    event_window: Optional[EventWindow] = None
    # The contract-rule overrides this scan graded contracts with
    # (contract_validator.effective_contract_overrides of the request's
    # overrides, BEFORE the hold-days DTE widening, which /api/contracts
    # re-derives from the same hold days). Step 6 sends it back to
    # /api/contracts so its table grades with the trade cards' rules, not
    # contract_rules.yaml's. {} = the scan overrode nothing. None = absent:
    # a result from before 2026-09-29, or the recording failed.
    contract_rules: Optional[dict[str, float]] = None
    # The Reward/Risk overrides (rr_* keys) this scan priced its plans with,
    # exactly as config_loader.effective_rr_overrides validated them. Step 7's
    # recompute-plan sends these back rather than live scanOverrides, which can
    # be edited after the scan (STEP3-PARAM-REACH). {} = the scan overrode
    # none. None = absent: a result from before 2026-10-02, or recording failed.
    rr_overrides: Optional[dict[str, float]] = None
    # The request fields this result was produced from, so a result restored
    # from /api/scan/last into an empty browser (no persisted ScanContext) can
    # rebuild the direction and hold days Steps 5-7 read, instead of falling
    # back to Bullish / Swing (STEP3-PARAM-REACH). None = a result from before
    # 2026-10-02.
    request_context: Optional[ScanRequestContext] = None
    # NO-LIVE-QUOTE (plan 3f): how many rejected names were rejected only
    # because none of their contracts had a live quote (reason exactly
    # "contracts rejected: no_live_quote(N)"). The scheduled-scan notice reads
    # this rather than parsing reasons. 0 on results persisted before it.
    noLiveQuoteNames: int = 0


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

    # ── Options mode only; the three below are one block ──────────────────
    # `scan_id` names the ScanResult that GET /api/scan/last returns at the
    # same instant. It is here so a reader fetching both endpoints can tell
    # whether the request fields above and the thresholds below describe the
    # result it holds, or a scan that landed between the two calls — the two
    # globals are snapshotted together under the router's state lock, so a
    # matching scan_id is a real guarantee, not a hope. None in stock mode
    # (which pairs no result) and whenever there is no last result, including
    # after restore_from_db refuses a pre-split blob but keeps its request.
    scan_id: Optional[str] = None
    # The two IV cut-offs the last manual scan ran with, taken from the
    # persisted ScanRequest AFTER its `_seed_pre_split_iv_knobs` validator, so
    # a pre-split body reports the value that was actually applied rather than
    # the class default. `iv_abs_threshold` is choose_primary's credit/debit
    # line — the seeded number with real money behind it — and
    # scripts/iv_basis_analysis.py records it against every sampled row so
    # section 4 measures the line in force instead of assuming 50.
    # None means UNKNOWN (no last request, or stock mode), never 50.
    iv_abs_threshold: Optional[float] = None
    iv_rank_threshold: Optional[float] = None


# ── Portfolio persistence ─────────────────────────────────────────────────────

class PortfolioPositionCreate(BaseModel):
    # allow_inf_nan=False (NUMERIC-API-INPUTS T2): every float is persisted, so
    # each is finite or a 422. Also reached by auto_trade_booking._build_body,
    # whose existing except refuses the booking instead of writing the value.
    model_config = ConfigDict(populate_by_name=True, allow_inf_nan=False)

    recId: str = Field(alias="rec_id")
    symbol: str
    contract: str       # SYMBOL|STRIKE|EXPIRY|C/P
    direction: Direction
    # gt=0: a non-positive entry price is not a price, and it is the DENOMINATOR
    # the router divides premiumStopDollar by to derive the per-position stop.
    # Accepting 0 meant that derivation was skipped and the user's typed dollar
    # stop dropped on the floor, while every other unusable-input path on this
    # endpoint reports itself.
    #
    # allow_inf_nan=False (P6, G1-6): `gt=0` alone ACCEPTS Infinity (inf > 0),
    # and the row was committed before the response failed to encode it -- a
    # stored inf behind a 500. JSON.stringify cannot emit Infinity, so only a
    # direct API call reaches this.
    entryPrice: float = Field(alias="entry_price", gt=0, allow_inf_nan=False)
    # ge=1, matching the PATCH path (routers/portfolio.py rejects qty < 1): a
    # zero or negative quantity is not a position, and without the floor POST
    # saved one that every P&L and exposure sum then multiplied by. Request
    # schema only -- PortfolioPositionSchema stays unbounded so a pre-existing
    # bad row still lists.
    qty: int = Field(default=1, ge=1)
    entryDate: str = Field(alias="entry_date")
    stop: Optional[float] = None
    structuralStop: Optional[float] = Field(alias="structural_stop", default=None)
    exitPlan: Optional[dict] = Field(alias="exit_plan", default=None)
    targets: list[dict] = []
    dteTotal: Optional[int] = Field(alias="dte_total", default=None)
    portfolioValue: float = Field(alias="portfolio_value", default=100000.0, description="Deprecated compatibility field; server account value is authoritative")
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
    # Round 9 -- does `stop` carry a level the USER TYPED, as an absolute price
    # against today's quote, rather than a plan-derived level?
    #
    # The router re-anchors `stop` by (live_price - scanStockPrice) so a plan
    # computed at scan time still sits the same distance from the underlying
    # when it is finally saved. That is right for a level the PLAN derived --
    # and wrong for one the user typed, for exactly the reason stated above for
    # premiumStopDollar: the client's number is anchored to a price the router
    # then replaces. Since this branch made the card's Invalidation an editable
    # absolute price (and round 8 bounded it against the LIVE quote), a typed
    # $180 on a stock that was scanned at $145 and now trades at $200 was being
    # stored as $235 -- above spot, so alert_generator's bullish
    # `price <= pos.stop` raises a Critical STOP_REACHED on the first scan.
    #
    # True = store `stop` as sent. None/False keeps the re-anchor, so every
    # existing client is unaffected. Only `stop` is exempted: structuralStop and
    # targets remain plan-derived and still move with the underlying.
    stopIsUserSet: Optional[bool] = Field(alias="stop_is_user_set", default=None)
    # Phase G (piece 5) — the trader's explicit method pick, carried through AT
    # CREATION for the same reason premiumStopPct is (see above): a trade sent
    # from the card must not have to be re-picked in the drawer afterwards.
    #
    # All five are Optional and default to None, and NULL IS A REAL STATE, not a
    # missing value: it means "opened before G, or opened by a path with no
    # human in it". The after-scan auto-executor (S5) is deliberately exempt
    # from G's send gate and sends exactly this shape — see the spec's §7.3 and
    # PHASE-G-S5-EXEMPT-2026-09-14. The portfolio renders it as "—", never as
    # 'ladder'.
    pickedMethod: Optional[PickedMethod] = Field(alias="picked_method", default=None)
    # THE UNITS ARE IN THE NAMES ON PURPOSE. Only the STOCK price may ever seed
    # resolved_tp_price, which alert_generator.py:181 compares against the stock
    # quote. A premium in that column makes `price >= 6.24` true on the first
    # tick and fires TP_HIT instantly on every bullish option position. An
    # un-suffixed `picked_row_price` cannot be checked by reading it.
    #
    # gt=0 on both for the reason entryPrice carries it and the reason
    # alertEngine.ts:164-169 re-checks `> 0` at the far end: a `?? 0` fallback
    # upstream can land a zero here, and zero is never a price. allow_inf_nan=False
    # for entryPrice's reason: an inf here seeds resolved_tp_price=inf, and
    # TP_HIT never fires again.
    pickedRowStockPrice: Optional[float] = Field(alias="picked_row_stock_price", default=None, gt=0, allow_inf_nan=False)
    pickedRowOptionPrice: Optional[float] = Field(alias="picked_row_option_price", default=None, gt=0, allow_inf_nan=False)
    pickedStopBasis: Optional[PickedStopBasis] = Field(alias="picked_stop_basis", default=None)
    pickedAt: Optional[PickedAt] = Field(alias="picked_at", default=None)
    # STOCKS-HORIZON-T1 H6 -- the scan's hold in calendar days, sent by the
    # stock sends. None (options, older clients) = no hold, no time stop.
    holdMaxDays: Optional[int] = Field(alias="hold_max_days", default=None, ge=0)
    # Audit round 1, F1 -- the order this save is about to place, so the D5
    # premium cap is judged at the price the order can FILL at
    # (`portfolio_risk.premium_cap_basis`): max(mid, limit) for LMT, the ask
    # (mid + half the live spread) for MKT. Create-only transport, never
    # stored. Both None means no order follows the save (a tracked basket row,
    # an older client): the cap is judged at the mid, as before. The stored
    # entry price is unaffected either way.
    orderType: Optional[Literal["LMT", "MKT"]] = Field(alias="order_type", default=None)
    orderLimitPrice: Optional[float] = Field(alias="order_limit_price", default=None, gt=0, allow_inf_nan=False)

    def __init__(self, **data):
        # Support both camelCase and snake_case field names
        mapped = {}
        aliases = {
            "order_type": "orderType",
            "order_limit_price": "orderLimitPrice",
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
            "stop_is_user_set": "stopIsUserSet",
            # Phase G. These five are REDUNDANT and are kept only for symmetry
            # with the eleven above; do not read them as load-bearing. An
            # earlier comment here claimed omitting one would silently drop the
            # pick -- that is FALSE and was corrected by the step 1 audit.
            # `model_config` sets `populate_by_name` (:856) and every field
            # carries `Field(alias=...)`, so pydantic accepts BOTH conventions
            # on its own; FastAPI validates via `model_validate`, which bypasses
            # this `__init__` entirely. Verified by construction, both ways.
            "picked_method": "pickedMethod",
            "picked_row_stock_price": "pickedRowStockPrice",
            "picked_row_option_price": "pickedRowOptionPrice",
            "picked_stop_basis": "pickedStopBasis",
            "picked_at": "pickedAt",
            "hold_max_days": "holdMaxDays",
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

    `portfolioValue` is retained for wire compatibility and ignored. Quantity
    increases re-run the exposure gate against server account configuration;
    decreases and edits without a quantity increase bypass that gate.

    `exitPlan`, `maxLossOverride`, `activeTpMethod`, `resolvedTpPrice`/
    `resolvedTpUpdatedAt`, and `alertOverrides` are Phase 0 scaffolding for
    the exit-plan pipeline (docs/superpowers/plans/2026-08-26-exit-plan-pipeline.md)
    — no endpoint computes these yet, but the PATCH plumbing to persist
    whatever a later feature computes already exists. Like `structuralStop`,
    `exitPlan`/`maxLossOverride`/`alertOverrides` follow the exclude_unset
    pattern so `{"exitPlan": null}` can still explicitly clear a previously
    computed value."""
    # allow_inf_nan=False (NUMERIC-API-INPUTS T2): persisted; finite or a 422.
    model_config = ConfigDict(populate_by_name=True, allow_inf_nan=False)

    stop: Optional[float] = None
    structuralStop: Optional[float] = Field(alias="structural_stop", default=None)
    targets: Optional[list[dict]] = None
    qty: Optional[int] = None
    portfolioValue: Optional[float] = Field(alias="portfolio_value", default=None)
    exitPlan: Optional[dict] = Field(alias="exit_plan", default=None)
    maxLossOverride: Optional[dict] = Field(alias="max_loss_override", default=None)
    activeTpMethod: Optional[TpMethod] = Field(alias="active_tp_method", default=None)
    resolvedTpPrice: Optional[float] = Field(alias="resolved_tp_price", default=None, allow_inf_nan=False)
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
    # True when GET /portfolio got no quote for this position (NO-LIVE-QUOTE
    # NLQ-1 round-1 F2). currentPrice / pnlDollar / pnlPct then hold their 0.0
    # defaults, which are NOT a price: the table renders "—" instead.
    quoteUnavailable: bool = False
    dteRemaining: int = 0
    delta: Optional[float] = None
    theta: Optional[float] = None
    # An IV RANK, or None when no rank source answered. Before
    # 2026-09-06 this field carried the ABSOLUTE IV instead, so the portfolio
    # table printed an absolute level under "IV RANK"; the absolute figure now
    # rides in `iv` and the two are labelled apart
    # (PHASE-A-NULL-IVRANK-2026-09-06).
    ivRank: Optional[int] = None
    iv: Optional[float] = None
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
    # Phase G — the trader's explicit pick, as recorded. These stay NULL when
    # absent; unlike activeTpMethod below they are NOT coerced to a default,
    # because "nobody picked" is the thing they exist to be able to say.
    pickedMethod: Optional[PickedMethod] = None
    pickedRowStockPrice: Optional[float] = None
    pickedRowOptionPrice: Optional[float] = None
    pickedStopBasis: Optional[PickedStopBasis] = None
    pickedAt: Optional[str] = None
    # STOCKS-HORIZON-T1 H6 -- None = no hold (never a stock time stop).
    holdMaxDays: Optional[int] = None

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
            # NO `or` COERCION HERE, unlike activeTpMethod two lines up. A NULL
            # pick must survive the round trip as NULL so the portfolio can
            # render "—"; defaulting it to 'ladder' would invent a decision.
            pickedMethod=obj.picked_method,
            pickedRowStockPrice=obj.picked_row_stock_price,
            pickedRowOptionPrice=obj.picked_row_option_price,
            pickedStopBasis=obj.picked_stop_basis,
            pickedAt=obj.picked_at,
            holdMaxDays=getattr(obj, "hold_max_days", None),
        )


class ClosePositionRequest(BaseModel):
    """Body for POST /api/portfolio/{rec_id}/close."""
    # allow_inf_nan=False (NUMERIC-API-INPUTS T2): exitPrice is persisted.
    model_config = ConfigDict(populate_by_name=True, allow_inf_nan=False)
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
