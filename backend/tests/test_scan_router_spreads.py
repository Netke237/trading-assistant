"""Tests for bearish spread attachment in POST /api/scan (F4).

Verifies that:
- A bearish candidate has spreadType in ("bear_put", "bear_call")
- The legs field has exactly 2 entries
- The non-primary spread appears in alternatives with spreadType populated
- Bullish candidates are unaffected (no spreadType)
- Spread filter: if credit < min_credit, spread is rejected
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from app.scoring.contract_validator import ContractScoreCard, ContractScoreBreakdown
from app.scoring.stock_scorer import StockScoreCard
from app.scoring.entry_quality import EntryAssessment
from app.scoring.reward_risk import RrResult


# ── Fixtures ──────────────────────────────────────────────────────────────────

_MOCK_CANDLES = [
    {
        "time": f"2026-0{i // 10 + 1}-{i % 28 + 1:02d}",
        "open": 184.0,
        "high": 190.0,
        "low": 182.0,
        "close": 187.0,
        "volume": 1_000_000,
    }
    for i in range(30)
]

# Single put contract for the primary chain fetch (Pass 2 bearish)
_MOCK_PUT_CHAIN = [
    {
        "strike": 185, "expiry": "2026-07-18", "price": 3.00, "spread": 0.20,
        "bid": 2.90, "ask": 3.10,
        "delta": -0.45, "theta": -0.05, "ivRank": 60, "dte": 30,
        "right": "P", "volume": 400,
    },
    {
        "strike": 180, "expiry": "2026-07-18", "price": 1.50, "spread": 0.20,
        "bid": 1.40, "ask": 1.60,
        "delta": -0.30, "theta": -0.04, "ivRank": 60, "dte": 30,
        "right": "P", "volume": 300,
    },
]

# Single call contract for the alt chain fetch
_MOCK_CALL_CHAIN = [
    {
        "strike": 190, "expiry": "2026-07-18", "price": 2.50, "spread": 0.20,
        "bid": 2.40, "ask": 2.60,
        "delta": 0.30, "theta": -0.05, "ivRank": 60, "dte": 30,
        "right": "C", "volume": 500,
    },
    {
        "strike": 195, "expiry": "2026-07-18", "price": 1.00, "spread": 0.20,
        "bid": 0.90, "ask": 1.10,
        "delta": 0.20, "theta": -0.03, "ivRank": 60, "dte": 30,
        "right": "C", "volume": 200,
    },
]

# The primary option chain result returned by the first chain fetch (Pass 2 direction chain)
_MOCK_CHAIN_P = [
    {
        "strike": 185, "expiry": "2026-07-18", "price": 3.00, "spread": 0.20,
        "bid": 2.90, "ask": 3.10,
        "delta": -0.45, "theta": -0.05, "ivRank": 30, "dte": 30,
        "right": "P", "volume": 400,
    }
]


def _make_pass_card(symbol: str, direction: str = "Bearish") -> StockScoreCard:
    return StockScoreCard(
        symbol=symbol,
        direction=direction,
        horizon="Swing",
        score=75,
        status="PASS",
        rules=[],
    )


def _make_contract_score() -> ContractScoreCard:
    return ContractScoreCard(
        contract_id="AAPL|185|2026-07-18|P",
        symbol="AAPL",
        strike=185.0,
        expiry="2026-07-18",
        is_call=False,
        score=70,
        status="PASS",
        breakdown=ContractScoreBreakdown(60, 60, 60, 60, 60, 60),
    )


def _make_entry() -> EntryAssessment:
    return EntryAssessment(
        limit_price=3.00, max_fill=3.05, order_type="Limit", quality_status="PASS",
    )


def _make_rr() -> RrResult:
    return RrResult(rr_ratio=2.0, model_used="Delta approximation", estimated_exit_premium=5.0)


def _make_plan(entry_result: EntryAssessment, rr_result: RrResult):
    """Fake TradePlan mirroring what build_trade_plan would return — the primary
    card's entry/exit/RR/targets now come from that shared helper."""
    from app.scoring.trade_plan import TradePlan
    return TradePlan(
        entry=entry_result,
        invalidation_price=180.0,
        premium_stop=1.8,
        time_stop_days=12,
        target_price=170.0,
        targets=[],
        rr_ratio=rr_result.rr_ratio,
        rr_model=rr_result.model_used,
        target_price_raw=170.0,
        invalidation_price_raw=180.0,
    )


# ── Helper: run _process_symbol with spread mocks ────────────────────────────

async def _run_bearish_process(
    *,
    iv_rank_threshold: float = 50.0,
    put_chain: list = None,
    call_chain: list = None,
    primary_chain: list = None,
    min_credit: float = 0.50,
    max_debit_pct: float = 40.0,
    spread_width: float = 5.0,
    short_leg_delta: float = 0.30,
):
    """Drive _process_symbol for a single bearish AAPL symbol."""
    from app.routers.scan import _process_symbol

    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    _put_chain = put_chain if put_chain is not None else _MOCK_PUT_CHAIN
    _call_chain = call_chain if call_chain is not None else _MOCK_CALL_CHAIN
    _primary = primary_chain if primary_chain is not None else _MOCK_CHAIN_P

    pass_card = _make_pass_card("AAPL")
    contract_score = _make_contract_score()
    entry_result = _make_entry()
    rr_result = _make_rr()

    # fetch_option_chain_async is called 3 times:
    # 1st: Pass 2 primary direction chain (P for bearish)
    # 2nd+3rd: spread attachment parallel fetch (P + C)
    chain_side_effects = [_primary, _put_chain, _call_chain]
    mock_chain = AsyncMock(side_effect=chain_side_effects)

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple Inc.")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", mock_chain),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=_make_plan(entry_result, rr_result)),
        patch("app.routers.scan.estimate_rr", return_value=rr_result),
        patch("app.routers.scan.log_event"),
    ):
        result = await _process_symbol(
            "AAPL", "Bearish", "Swing", mock_client, sem, "test-scan-id",
            iv_rank_threshold=iv_rank_threshold,
            min_credit=min_credit,
            max_debit_pct=max_debit_pct,
            spread_width=spread_width,
            short_leg_delta=short_leg_delta,
        )
    return result


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bearish_candidate_has_spread_type():
    """Bearish candidate must have spreadType in (bear_put, bear_call)."""
    result = await _run_bearish_process()
    assert hasattr(result, "spreadType"), "No spreadType attribute on result"
    assert result.spreadType in ("bear_put", "bear_call"), (
        f"Unexpected spreadType: {result.spreadType!r}"
    )


@pytest.mark.asyncio
async def test_bearish_candidate_has_two_legs():
    """Bearish candidate's legs field must have exactly 2 entries."""
    result = await _run_bearish_process()
    assert result.legs is not None, "legs is None"
    assert len(result.legs) == 2, f"Expected 2 legs, got {len(result.legs)}"


@pytest.mark.asyncio
async def test_bearish_candidate_alt_spread_in_alternatives():
    """The non-primary spread must appear in alternatives with spreadType populated."""
    result = await _run_bearish_process()
    spread_alts = [
        a for a in result.alternatives
        if getattr(a, "spreadType", None) in ("bear_put", "bear_call")
    ]
    assert len(spread_alts) >= 1, (
        f"Expected at least 1 alternative with spreadType, got {result.alternatives}"
    )
    alt = spread_alts[0]
    assert alt.spreadType != result.spreadType, (
        "Alternative spread type must differ from primary"
    )
    assert alt.legs is not None and len(alt.legs) == 2, (
        f"Alternative must have 2 legs, got {alt.legs}"
    )


@pytest.mark.asyncio
async def test_bearish_low_iv_rank_uses_bear_put():
    """When iv_rank < threshold, primary should be bear_put."""
    # iv_rank comes from the primary chain (ivRank=30), threshold=50 → bear_put
    result = await _run_bearish_process(iv_rank_threshold=50.0)
    assert result.spreadType == "bear_put", (
        f"Expected bear_put for low IV rank, got {result.spreadType!r}"
    )


@pytest.mark.asyncio
async def test_bearish_high_iv_rank_uses_bear_call():
    """When iv_rank >= threshold, primary should be bear_call."""
    # Override primary chain to have high ivRank
    high_iv_primary = [
        {
            "strike": 185, "expiry": "2026-07-18", "price": 3.00, "spread": 0.20,
            "bid": 2.90, "ask": 3.10,
            "delta": -0.45, "theta": -0.05, "ivRank": 75, "dte": 30,
            "right": "P", "volume": 400,
        }
    ]
    result = await _run_bearish_process(iv_rank_threshold=50.0, primary_chain=high_iv_primary)
    assert result.spreadType == "bear_call", (
        f"Expected bear_call for high IV rank, got {result.spreadType!r}"
    )


@pytest.mark.asyncio
async def test_bullish_candidate_has_no_spread():
    """Bullish candidates must NOT have spread fields populated."""
    from app.routers.scan import _process_symbol

    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    _MOCK_CHAIN_C = [
        {
            "strike": 190, "expiry": "2026-07-18", "price": 2.50, "spread": 0.20,
            "bid": 2.40, "ask": 2.60,
            "delta": 0.45, "theta": -0.05, "ivRank": 55, "dte": 30,
            "right": "C", "volume": 500,
        }
    ]

    pass_card = _make_pass_card("AAPL", direction="Bullish")
    bull_contract_score = ContractScoreCard(
        contract_id="AAPL|190|2026-07-18|C",
        symbol="AAPL",
        strike=190.0,
        expiry="2026-07-18",
        is_call=True,
        score=70,
        status="PASS",
        breakdown=ContractScoreBreakdown(60, 60, 60, 60, 60, 60),
    )
    entry_result = _make_entry()
    rr_result = _make_rr()

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple Inc.")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=_MOCK_CHAIN_C)),
        patch("app.routers.scan.validate_contract", return_value=bull_contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=_make_plan(entry_result, rr_result)),
        patch("app.routers.scan.estimate_rr", return_value=rr_result),
        patch("app.routers.scan.log_event"),
    ):
        result = await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
        )

    assert result.spreadType is None, (
        f"Bullish candidate should not have spreadType, got {result.spreadType!r}"
    )
    assert result.legs is None, (
        f"Bullish candidate should not have legs, got {result.legs}"
    )


@pytest.mark.asyncio
async def test_spread_filter_credit_too_low_no_primary_bear_call():
    """If bear_call credit < min_credit, primary spread should be None (graceful skip)."""
    # High IV rank → bear_call primary; min_credit very high so it gets rejected
    high_iv_primary = [
        {
            "strike": 185, "expiry": "2026-07-18", "price": 0.10, "spread": 0.05,
            "bid": 0.08, "ask": 0.12,
            "delta": -0.45, "theta": -0.05, "ivRank": 75, "dte": 30,
            "right": "P", "volume": 400,
        }
    ]
    # Call chain with very tight bid/ask so credit is tiny
    tiny_call_chain = [
        {
            "strike": 190, "expiry": "2026-07-18", "price": 0.10, "spread": 0.05,
            "bid": 0.08, "ask": 0.12,
            "delta": 0.30, "theta": -0.02, "ivRank": 75, "dte": 30,
            "right": "C", "volume": 200,
        },
        {
            "strike": 195, "expiry": "2026-07-18", "price": 0.05, "spread": 0.03,
            "bid": 0.04, "ask": 0.06,
            "delta": 0.15, "theta": -0.01, "ivRank": 75, "dte": 30,
            "right": "C", "volume": 100,
        },
    ]
    result = await _run_bearish_process(
        iv_rank_threshold=50.0,
        primary_chain=high_iv_primary,
        call_chain=tiny_call_chain,
        put_chain=_MOCK_PUT_CHAIN,
        min_credit=10.0,   # deliberately impossibly high
    )
    # Primary spread should be rejected by filter → spreadType is None
    assert result.spreadType is None, (
        f"Expected None spreadType when credit filter fails, got {result.spreadType!r}"
    )


@pytest.mark.asyncio
async def test_scan_request_accepts_spread_params():
    """ScanRequest must accept the five new spread params without validation error."""
    from app.schemas import ScanRequest
    req = ScanRequest(
        universe=["AAPL"],
        direction="Bearish",
        horizon="Swing",
        spread_width=10.0,
        short_leg_delta=0.25,
        iv_rank_threshold=60.0,
        min_credit=1.00,
        max_debit_pct=35.0,
    )
    assert req.spread_width == 10.0
    assert req.short_leg_delta == 0.25
    assert req.iv_rank_threshold == 60.0
    assert req.min_credit == 1.00
    assert req.max_debit_pct == 35.0


@pytest.mark.asyncio
async def test_scan_request_spread_params_default():
    """ScanRequest spread params have sensible defaults."""
    from app.schemas import ScanRequest
    req = ScanRequest(universe=[], direction="Bullish", horizon="Swing")
    assert req.spread_width == 5.0
    assert req.short_leg_delta == 0.30
    assert req.iv_rank_threshold == 50.0
    assert req.min_credit == 0.50
    assert req.max_debit_pct == 40.0
