"""Test AlternativeContract attachment to TradeCardData in scan results."""

from contextlib import ExitStack
from unittest.mock import patch, AsyncMock

_MOCK_CANDLES = [
    {"time": f"2026-0{i//10+1}-{i%28+1:02d}", "open": 184.0, "high": 190.0,
     "low": 182.0, "close": 187.0, "volume": 1_000_000}
    for i in range(30)
]

def _expiry(days_from_today: int) -> str:
    from datetime import date, timedelta
    return (date.today() + timedelta(days=days_from_today)).isoformat()


# open_interest and a RELATIVE expiry, so every contract clears
# contract_rules.yaml's hard rejects whenever this runs (a hardcoded 2026-06-20
# expiry had gone stale -- one of the reasons this module iterated nothing).
_MOCK_MULTI_CHAIN = [
    {
        "strike": 185, "expiry": _expiry(41), "price": 4.50, "spread": 0.15,
        "delta": 0.55, "theta": -0.06, "ivRank": 50, "dte": 41,
        "right": "C", "volume": 800, "open_interest": 2000,
    },
    {
        "strike": 190, "expiry": _expiry(41), "price": 2.50, "spread": 0.20,
        "delta": 0.45, "theta": -0.05, "ivRank": 55, "dte": 41,
        "right": "C", "volume": 500, "open_interest": 2000,
    },
    {
        "strike": 195, "expiry": _expiry(41), "price": 1.00, "spread": 0.10,
        "delta": 0.30, "theta": -0.03, "ivRank": 60, "dte": 41,
        "right": "C", "volume": 300, "open_interest": 2000,
    },
]


def _passing_card(direction: str):
    """P6 (B3). The flat _MOCK_CANDLES feed scores ~32 and is REJECTed at the
    stock score gate, so every candidate loop below used to iterate an EMPTY
    list and the module passed while checking nothing. `min_stock_score` does
    not help -- the gate is on the card's STATUS. This module tests
    alternatives, not stock scoring, so the card is fixed to PASS (the pattern
    test_scan_endpoint.py's _force_passing_stock_score uses), with a MEASURED
    trend rule so the options direction gate keeps it (P3c item 2)."""
    from app.scoring.stock_scorer import StockScoreCard, RuleResult
    return StockScoreCard(symbol="AAPL", direction=direction, horizon="Swing", score=80,
                          status="PASS", rules=[RuleResult("trend", "PASS", 80, {})])


def _enter_scan_patches(*, price=185.0, candles=_MOCK_CANDLES, chain=_MOCK_MULTI_CHAIN,
                        company="Test Company", fund=None, direction="Bullish"):
    stack = ExitStack()
    stack.enter_context(patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=price)))
    stack.enter_context(patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=candles)))
    stack.enter_context(patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=chain)))
    stack.enter_context(patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value=company)))
    stack.enter_context(patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=fund)))
    stack.enter_context(patch("app.routers.scan.score_stock", return_value=_passing_card(direction)))
    # The DB-backed pre-fetch would otherwise serve real ingested bars/quotes for
    # AAPL and bypass the mocks above (test_scan_endpoint.py's _no_db_leak).
    stack.enter_context(patch("app.routers.scan.fetch_quotes", return_value={}))
    stack.enter_context(patch("app.services.historical_store.get_bars", AsyncMock(return_value=[])))
    return stack


def _candidates(data: dict) -> list[dict]:
    """The candidate list, asserted NON-EMPTY: a loop over nothing proves nothing."""
    assert data["candidates"], f"scan produced no candidates: {data.get('rejected')}"
    return data["candidates"]


def test_scan_produces_alternatives_with_multi_contract_chain(client):
    with _enter_scan_patches():
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {},
        })
    assert r.status_code == 200
    data = r.json()

    for c in _candidates(data):
        assert "alternatives" in c
        assert "alternativesCount" in c
        assert c["alternativesCount"] >= 1, (
            f"Expected at least 1 alternative for {c['symbol']}, got {c['alternativesCount']}"
        )
        assert c["alternativesCount"] == len(c["alternatives"]), (
            f"alternativesCount {c['alternativesCount']} != len(alternatives) {len(c['alternatives'])}"
        )

        for alt in c["alternatives"]:
            assert alt["score"] < c["contractScore"], (
                f"Alternative score {alt['score']} should be < primary {c['contractScore']}"
            )
            for field in ("symbol", "strike", "expiry", "right", "dte", "mid", "delta",
                          "theta", "ivRank", "score", "contractConfidence",
                          "contractBreakdown", "rrRatio", "rrModel", "reason"):
                assert field in alt, f"AlternativeContract missing field '{field}'"


def test_scan_single_contract_produces_no_alternatives(client):
    _MOCK_SINGLE = [
        {
            "strike": 190, "expiry": _expiry(41), "price": 2.50, "spread": 0.20,
            "delta": 0.45, "theta": -0.05, "ivRank": 55, "dte": 41,
            "right": "C", "volume": 500, "open_interest": 2000,
        }
    ]
    with _enter_scan_patches(chain=_MOCK_SINGLE):
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {},
        })
    assert r.status_code == 200
    data = r.json()
    for c in _candidates(data):
        assert c["alternativesCount"] == 0
        assert c["alternatives"] == []


def test_scan_bullish_alternatives_have_right_C(client):
    with _enter_scan_patches():
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {},
        })
    assert r.status_code == 200
    data = r.json()
    for c in _candidates(data):
        for alt in c["alternatives"]:
            assert alt["right"] == "C", f"Bullish alternative should have right=C, got {alt['right']}"


def test_scan_bearish_alternatives_have_right_P(client):
    _MOCK_PUT_CHAIN = [
        {
            "strike": 180, "expiry": _expiry(41), "price": 4.50, "spread": 0.15,
            "delta": -0.55, "theta": -0.06, "ivRank": 50, "dte": 41,
            "right": "P", "volume": 800, "open_interest": 2000,
        },
        {
            "strike": 175, "expiry": _expiry(41), "price": 2.50, "spread": 0.20,
            "delta": -0.45, "theta": -0.05, "ivRank": 55, "dte": 41,
            "right": "P", "volume": 500, "open_interest": 2000,
        },
        {
            "strike": 170, "expiry": _expiry(41), "price": 1.00, "spread": 0.10,
            "delta": -0.30, "theta": -0.03, "ivRank": 60, "dte": 41,
            "right": "P", "volume": 300, "open_interest": 2000,
        },
    ]
    with _enter_scan_patches(chain=_MOCK_PUT_CHAIN, direction="Bearish"):
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bearish", "horizon": "Swing", "overrides": {},
        })
    assert r.status_code == 200
    data = r.json()
    for c in _candidates(data):
        for alt in c["alternatives"]:
            assert alt["right"] == "P", f"Bearish alternative should have right=P, got {alt['right']}"


async def _run_alt_scan_with_runner_ups(runner_ups: list[dict]):
    """Shared driver for the missing-field regression tests below. Builds a
    chain (chain[0]=full-data primary, chain[1:]=the caller-supplied
    runner-ups) and calls _process_symbol() directly -- not through
    client.post("/api/scan", ...) -- because the full-endpoint path is
    unreliable for this specific bug: the shared _MOCK_CANDLES fixture in
    this file is flat/degenerate enough that _process_symbol short-circuits
    at the stock-score confidence gate before the option chain is ever
    scored, and _process_symbol's db_bars prefetch path can bypass the
    fetch_candles_async/fetch_price_async mocks entirely for symbols that
    already have rows in the test DB (e.g. AAPL, which has seeded fixture
    data). Patching score_stock, validate_contract, and build_trade_plan to
    fixed, known-good results (the same pattern test_scan_router_spreads.py
    already uses for its bearish-spread tests) sidesteps both problems.
    Every contract gets the SAME ContractScoreCard back from the patched
    validate_contract() below; valid_scores.sort() is a stable sort, so
    equal scores preserve the original chain order -- chain[0] becomes the
    primary, chain[1:] become the runner-ups, deterministically."""
    import asyncio
    from unittest.mock import patch, AsyncMock, MagicMock
    from app.routers.scan import _process_symbol
    from app.scoring.contract_validator import ContractScoreCard, ContractScoreBreakdown
    from app.scoring.stock_scorer import StockScoreCard
    from app.scoring.entry_quality import EntryAssessment
    from app.scoring.trade_plan import TradePlan

    pass_card = StockScoreCard(symbol="AAPL", direction="Bullish", horizon="Swing", score=75, status="PASS", rules=[])
    contract_score = ContractScoreCard(
        contract_id="AAPL|185|2026-09-13|C", symbol="AAPL", strike=185.0, expiry="2026-09-13",
        is_call=True, score=70, status="PASS",
        breakdown=ContractScoreBreakdown(60, 60, 60, 60, 60, 60),
    )
    entry_result = EntryAssessment(limit_price=4.55, max_fill=4.65, order_type="Limit", quality_status="PASS")
    plan = TradePlan(
        entry=entry_result, invalidation_price=175.0, premium_stop=2.7, time_stop_days=12,
        target_price=200.0, targets=[], rr_ratio=2.0, rr_model="Heston repriced",
        target_price_raw=200.0, invalidation_price_raw=175.0,
        # Swing's 7 days on a 45-DTE contract, the horizon build_trade_plan
        # resolves for these inputs. Stated, not defaulted: a TradePlan that
        # cannot say what horizon it priced at is how the ladder and the
        # Monte Carlo card drifted apart in the first place.
        reprice_years=(45 - 7) / 365.0,
    )

    chain = [
        {"strike": 185, "expiry": "2026-09-13", "price": 4.50, "spread": 0.15,
         "delta": 0.55, "theta": -0.06, "ivRank": 40, "dte": 45, "right": "C", "volume": 800},
        *runner_ups,
    ]

    sem = asyncio.Semaphore(10)
    mock_client = MagicMock()

    with (
        patch("app.routers.scan.fetch_candles_async", AsyncMock(return_value=_MOCK_CANDLES)),
        patch("app.routers.scan.fetch_price_async", AsyncMock(return_value=185.0)),
        patch("app.routers.scan.fetch_company_name_async", AsyncMock(return_value="Apple Inc.")),
        patch("app.routers.scan.fetch_fundamentals_calendar", AsyncMock(return_value=None)),
        patch("app.routers.scan.fetch_calendar_dates_async", AsyncMock(return_value=(None, None))),
        patch("app.routers.scan.score_stock", return_value=pass_card),
        patch("app.routers.scan.fetch_option_chain_async", AsyncMock(return_value=chain)),
        patch("app.routers.scan.validate_contract", return_value=contract_score),
        patch("app.routers.scan.build_trade_plan", return_value=plan),
        patch("app.routers.scan.log_event"),
        # Isolate the BS-fallback path (what this bug is about) from Heston,
        # which would otherwise calibrate off chain[0]'s real price and mask
        # the fallback-pricing fabrication these tests target.
        patch("app.routers.scan._HESTON_PRICING_ENABLED", False),
    ):
        return await _process_symbol(
            "AAPL", "Bullish", "Swing", mock_client, sem, "test-scan-id",
        )


async def _run_alt_scan_with_runner_up(runner_up: dict):
    return await _run_alt_scan_with_runner_ups([runner_up])


def test_scan_alternative_with_missing_price_is_excluded():
    """A runner-up whose quote is missing 'price' must be excluded from
    alternatives, not fabricated into one with a fake $0.10 premium fed
    through the real-IV reward/risk pipeline. Regression test for the bug
    where alt_c.get("price", 0.10) silently substituted a fabricated
    premium that estimate_rr() then treated as a genuine market quote."""
    import asyncio
    runner_up = {
        # Missing "price" entirely -- simulates a runner-up quote with no
        # real market data. Must NOT be defaulted to a fabricated premium.
        "strike": 190, "expiry": "2026-09-13",
        "delta": 0.68, "theta": -0.05, "ivRank": 69, "dte": 45, "right": "C", "volume": 500,
    }
    result = asyncio.run(_run_alt_scan_with_runner_up(runner_up))
    assert result.alternativesCount == 0, (
        f"Expected the missing-price runner-up to be excluded, got "
        f"{result.alternativesCount} alternative(s): {result.alternatives}"
    )
    assert result.alternatives == []


def test_scan_alternative_with_missing_strike_is_excluded():
    """A runner-up whose quote is missing 'strike' must be excluded, not
    fabricated with the current stock price silently substituted as its
    strike (alt_c.get("strike", price))."""
    import asyncio
    runner_up = {
        # Missing "strike" entirely.
        "expiry": "2026-09-13", "price": 2.50, "spread": 0.20,
        "delta": 0.45, "theta": -0.05, "ivRank": 55, "dte": 45, "right": "C", "volume": 500,
    }
    result = asyncio.run(_run_alt_scan_with_runner_up(runner_up))
    assert result.alternativesCount == 0, (
        f"Expected the missing-strike runner-up to be excluded, got "
        f"{result.alternativesCount} alternative(s): {result.alternatives}"
    )
    assert result.alternatives == []


def test_scan_alternative_with_missing_dte_is_excluded():
    """A runner-up whose quote is missing 'dte' must be excluded, not
    fabricated with a default 30-day expiry silently substituted
    (alt_c.get("dte", 30))."""
    import asyncio
    runner_up = {
        # Missing "dte" entirely.
        "strike": 190, "expiry": "2026-09-13", "price": 2.50, "spread": 0.20,
        "delta": 0.45, "theta": -0.05, "ivRank": 55, "right": "C", "volume": 500,
    }
    result = asyncio.run(_run_alt_scan_with_runner_up(runner_up))
    assert result.alternativesCount == 0, (
        f"Expected the missing-dte runner-up to be excluded, got "
        f"{result.alternativesCount} alternative(s): {result.alternatives}"
    )
    assert result.alternatives == []


def test_scan_alternative_skip_is_per_item_not_batch_wide():
    """When one runner-up has a complete quote and the other is missing
    'price', only the broken one is skipped -- the valid one still appears.
    Proves the guard is a per-item `continue`, not something that discards
    the whole runner-up batch or otherwise interacts across list entries."""
    import asyncio
    valid_runner_up = {
        "strike": 190, "expiry": "2026-09-13", "price": 2.50, "spread": 0.20,
        "delta": 0.45, "theta": -0.05, "ivRank": 55, "dte": 45, "right": "C", "volume": 500,
    }
    broken_runner_up = {
        # Missing "price" entirely.
        "strike": 195, "expiry": "2026-09-13",
        "delta": 0.30, "theta": -0.03, "ivRank": 60, "dte": 45, "right": "C", "volume": 300,
    }
    result = asyncio.run(_run_alt_scan_with_runner_ups([valid_runner_up, broken_runner_up]))
    assert result.alternativesCount == 1, (
        f"Expected exactly the valid runner-up to survive, got "
        f"{result.alternativesCount} alternative(s): {result.alternatives}"
    )
    assert result.alternatives[0].strike == 190, (
        f"Expected the surviving alternative to be the valid strike=190 "
        f"runner-up, got strike={result.alternatives[0].strike}"
    )
