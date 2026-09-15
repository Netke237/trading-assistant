"""The options funnel must account for the direction-conviction gate.

Regression for the reported bug: a Bearish/Position scan rendered
"Candidates 5" in the Step-3 pipeline funnel above a Step-4 ranking table with
no rows. `OptionsPipeline` was built straight after scoring, BEFORE the
direction-conviction filter ran, so its `candidates` counted symbols that the
filter then stripped and the UI never received. stock_scan.py had always built
StockPipeline after its own filters; only the options path was wrong.

The invariant these tests pin: pipeline.candidates == len(result.candidates),
and every symbol removed between scoring and the response is accounted for by
exactly one funnel counter.
"""
from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import patch, AsyncMock

import pytest

from app.schemas import (
    TradeCardData, ScoreBreakdown, ContractScoreBreakdown, ContractDetails,
    TradeEntry, TradeExit, RejectedCandidate,
)


def _card(symbol: str, trend: int) -> TradeCardData:
    """A minimal PASS candidate whose only interesting axis is `trend` — the
    single field the direction-conviction gate reads."""
    return TradeCardData(
        symbol=symbol,
        company=symbol,
        price=100.0,
        direction="Bearish",
        status="PASS",
        stockScore=70,
        stockConfidence="PASS",
        stockBreakdown=ScoreBreakdown(
            trend=trend, pullback=50, trigger=50, event=50, volatility=50,
        ),
        contract=f"{symbol}|100|2026-06-20|P",
        contractScore=60,
        contractConfidence="PASS",
        contractBreakdown=ContractScoreBreakdown(
            dteFit=50, delta=50, ivAttractiveness=50, liquidity=50, spread=50,
        ),
        contractDetails=ContractDetails(
            strike=100, expiry="2026-06-20", right="P", mid=1.0, delta=-0.5,
            theta=-0.05, ivRank=50, dte=55,
        ),
        entry=TradeEntry(limit=1.0, maxFill=1.05, orderType="Limit"),
        exit=TradeExit(invalidation=105.0, premiumStop=0.6, timeStopDays=10, target=90.0),
        rrRatio=2.0,
        rrModel="BS repriced (IV-derived)",
        finalStatus="PASS",
    )


def _run(client, outcomes: dict[str, object], *, direction: str, horizon: str,
         overrides: dict | None = None):
    """POST /api/scan with _process_symbol stubbed per symbol.

    `outcomes` maps symbol -> the TradeCardData, RejectedCandidate or Exception
    that _process_symbol should produce for it. Keyed by SYMBOL rather than by
    call order: the production code builds its task list and gathers
    concurrently, so an ordered side_effect would silently mis-assign trend
    values if that construction is ever reordered.

    Network is stubbed out so the suite is hermetic — without this the batch
    quote fetch, the bars read and the fundamentals gather all reach live
    services, which is both slow and non-deterministic.
    """
    symbols = list(outcomes)

    async def _fake_process(symbol, *_a, **_kw):
        outcome = outcomes[symbol]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    with ExitStack() as stack:
        stack.enter_context(patch("app.routers.scan._process_symbol", _fake_process))
        stack.enter_context(patch(
            "app.routers.scan.get_tradier_creds",
            return_value=("tok", "https://example.invalid"),
        ))
        stack.enter_context(patch("app.routers.scan.fetch_quotes", return_value={}))
        stack.enter_context(patch(
            "app.services.historical_store.get_bars", AsyncMock(return_value=[]),
        ))
        stack.enter_context(patch(
            "app.routers.scan.get_fundamentals", AsyncMock(return_value=None),
        ))
        r = client.post("/api/scan", json={
            "universe": symbols, "direction": direction, "horizon": horizon,
            "overrides": overrides or {},
        })
    assert r.status_code == 200, r.text
    return r.json()


def _cards(*specs: tuple[str, int]) -> dict[str, object]:
    return {sym: _card(sym, trend) for sym, trend in specs}


def _accounted(pipeline: dict) -> int:
    """Every bucket the funnel can attribute a symbol to."""
    return (
        pipeline["candidates"]
        + pipeline["failed_data"]
        + pipeline["failed_pre_screen"]
        + pipeline["no_chain"]
        + pipeline["failed_score"]
        + pipeline["failed_contracts"]
        + pipeline["failed_direction"]
        + pipeline["failed_shortlist"]
        + pipeline["other_rejected"]
    )


def test_funnel_candidates_matches_returned_list_when_gate_strips_all(client):
    """Bearish/Position gates out trend > 40. Five candidates all above it must
    leave the funnel reporting 0 — not 5 — and name where they went."""
    body = _run(client, _cards(*((s, 60) for s in ("AAA", "BBB", "CCC", "DDD", "EEE"))),
                direction="Bearish", horizon="Position")

    assert body["candidates"] == []
    pipeline = body["pipeline"]
    assert pipeline["candidates"] == 0, (
        "funnel still reports the pre-filter count — this is the reported bug"
    )
    assert pipeline["failed_direction"] == 5
    assert body["direction_banner"], "an empty table must explain itself"


def test_funnel_candidates_matches_returned_list_on_a_partial_strip(client):
    """The survivors, and only the survivors, are counted as candidates."""
    body = _run(client, _cards(("AAA", 60), ("BBB", 20), ("CCC", 30)),
                direction="Bearish", horizon="Position")

    pipeline = body["pipeline"]
    assert pipeline["candidates"] == len(body["candidates"]) == 2
    assert pipeline["failed_direction"] == 1
    assert {c["symbol"] for c in body["candidates"]} == {"BBB", "CCC"}
    assert not body["direction_banner"], "survivors exist — no all-stripped banner"


def test_funnel_reports_no_direction_failures_when_no_gate_applies(client):
    """Intraday is exempt from the gate, so nothing is attributed to it."""
    body = _run(client, _cards(("AAA", 90), ("BBB", 90)),
                direction="Bearish", horizon="Intraday")

    pipeline = body["pipeline"]
    assert pipeline["failed_direction"] == 0
    assert pipeline["candidates"] == len(body["candidates"]) == 2


def test_shortlist_cap_is_accounted_for_rather_than_silently_trimming(client):
    """The cap trims the returned list, so the funnel must show that too —
    otherwise moving `candidates` past the cap just relocates the same lie."""
    body = _run(client, _cards(("AAA", 10), ("BBB", 10), ("CCC", 10)),
                direction="Bearish", horizon="Position",
                overrides={"shortlist_max_candidates": 2})

    pipeline = body["pipeline"]
    assert pipeline["candidates"] == len(body["candidates"]) == 2
    assert pipeline["failed_shortlist"] == 1
    assert body["original_count"] == 3
    assert body["shortlist_truncated"] is True


def test_a_symbol_that_raises_is_counted_not_dropped(client):
    """Exceptions are recorded as `reason=str(exc)`, which for many httpx and
    asyncio errors is the EMPTY STRING and so matches no reason predicate.
    Without a residual bucket such a symbol leaves the funnel entirely."""
    outcomes: dict[str, object] = _cards(("AAA", 10))
    outcomes["BOOM"] = RuntimeError("")   # empty message, as asyncio errors often are

    body = _run(client, outcomes, direction="Bearish", horizon="Position")

    pipeline = body["pipeline"]
    assert pipeline["other_rejected"] == 1, "the raising symbol vanished from the funnel"
    assert _accounted(pipeline) == pipeline["scanned"] == 2
    assert body["state"] == "PARTIAL", "one raised, one survived"


def test_a_rejection_matching_no_predicate_is_counted_not_dropped(client):
    """The buckets match on reason text. A reason nobody classified must still
    land somewhere rather than silently leaving the funnel short."""
    outcomes: dict[str, object] = _cards(("AAA", 10))
    outcomes["ZZZ"] = RejectedCandidate(symbol="ZZZ", reason="some brand new reason")

    body = _run(client, outcomes, direction="Bearish", horizon="Position")

    pipeline = body["pipeline"]
    assert pipeline["other_rejected"] == 1
    assert _accounted(pipeline) == pipeline["scanned"] == 2


def test_every_scanned_symbol_is_accounted_for_in_the_funnel(client):
    """The full invariant, with every bucket non-trivially exercised at once:
    a direction strip, a shortlist trim, a raising symbol and an unclassified
    rejection — so the assertion cannot pass by everything being zero."""
    outcomes: dict[str, object] = _cards(
        ("AAA", 60),   # stripped by the direction gate
        ("BBB", 10),   # survives
        ("CCC", 10),   # survives, then trimmed by the cap
    )
    outcomes["BOOM"] = RuntimeError("")
    outcomes["ZZZ"] = RejectedCandidate(symbol="ZZZ", reason="some brand new reason")

    body = _run(client, outcomes, direction="Bearish", horizon="Position",
                overrides={"shortlist_max_candidates": 1})

    pipeline = body["pipeline"]
    assert pipeline["scanned"] == 5
    assert pipeline["failed_direction"] == 1
    assert pipeline["failed_shortlist"] == 1
    assert pipeline["other_rejected"] == 2
    assert pipeline["candidates"] == len(body["candidates"]) == 1
    assert _accounted(pipeline) == pipeline["scanned"]
    # 1 gated on trend, 1 trimmed by the cap, 1 returned.
    assert pipeline["failed_direction"] == 1
    assert pipeline["failed_shortlist"] == 1
    assert pipeline["candidates"] == 1
