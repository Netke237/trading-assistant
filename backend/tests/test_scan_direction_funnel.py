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
    TradeEntry, TradeExit,
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


def _run(client, cards: list[TradeCardData], *, direction: str, horizon: str,
         overrides: dict | None = None):
    """POST /api/scan with _process_symbol stubbed to yield `cards`."""
    symbols = [c.symbol for c in cards]
    with ExitStack() as stack:
        stack.enter_context(patch(
            "app.routers.scan._process_symbol",
            AsyncMock(side_effect=list(cards)),
        ))
        stack.enter_context(patch(
            "app.routers.scan.get_tradier_creds",
            return_value=("tok", "https://example.invalid"),
        ))
        r = client.post("/api/scan", json={
            "universe": symbols, "direction": direction, "horizon": horizon,
            "overrides": overrides or {},
        })
    assert r.status_code == 200, r.text
    return r.json()


def test_funnel_candidates_matches_returned_list_when_gate_strips_all(client):
    """Bearish/Position gates out trend > 40. Five candidates all above it must
    leave the funnel reporting 0 — not 5 — and name where they went."""
    cards = [_card(s, trend=60) for s in ("AAA", "BBB", "CCC", "DDD", "EEE")]
    body = _run(client, cards, direction="Bearish", horizon="Position")

    assert body["candidates"] == []
    pipeline = body["pipeline"]
    assert pipeline["candidates"] == 0, (
        "funnel still reports the pre-filter count — this is the reported bug"
    )
    assert pipeline["failed_direction"] == 5
    assert body["direction_banner"], "an empty table must explain itself"


def test_funnel_candidates_matches_returned_list_on_a_partial_strip(client):
    """The survivors, and only the survivors, are counted as candidates."""
    cards = [
        _card("AAA", trend=60),   # stripped: 60 > 40
        _card("BBB", trend=20),   # kept
        _card("CCC", trend=30),   # kept
    ]
    body = _run(client, cards, direction="Bearish", horizon="Position")

    pipeline = body["pipeline"]
    assert pipeline["candidates"] == len(body["candidates"]) == 2
    assert pipeline["failed_direction"] == 1
    assert {c["symbol"] for c in body["candidates"]} == {"BBB", "CCC"}
    assert not body["direction_banner"], "survivors exist — no all-stripped banner"


def test_funnel_reports_no_direction_failures_when_no_gate_applies(client):
    """Intraday is exempt from the gate, so nothing is attributed to it."""
    cards = [_card(s, trend=90) for s in ("AAA", "BBB")]
    body = _run(client, cards, direction="Bearish", horizon="Intraday")

    pipeline = body["pipeline"]
    assert pipeline["failed_direction"] == 0
    assert pipeline["candidates"] == len(body["candidates"]) == 2


def test_shortlist_cap_is_accounted_for_rather_than_silently_trimming(client):
    """The cap trims the returned list, so the funnel must show that too —
    otherwise moving `candidates` past the cap just relocates the same lie."""
    cards = [_card(s, trend=10) for s in ("AAA", "BBB", "CCC")]
    body = _run(client, cards, direction="Bearish", horizon="Position",
                overrides={"shortlist_max_candidates": 2})

    pipeline = body["pipeline"]
    assert pipeline["candidates"] == len(body["candidates"]) == 2
    assert pipeline["failed_shortlist"] == 1
    assert body["original_count"] == 3
    assert body["shortlist_truncated"] is True


def test_every_scanned_symbol_is_accounted_for_in_the_funnel(client):
    """scanned == candidates + every drop bucket, with nothing unexplained
    between the last funnel stage and the bottom line."""
    cards = [_card("AAA", trend=60), _card("BBB", trend=10), _card("CCC", trend=10)]
    body = _run(client, cards, direction="Bearish", horizon="Position",
                overrides={"shortlist_max_candidates": 1})

    pipeline = body["pipeline"]
    accounted = (
        pipeline["candidates"]
        + pipeline["failed_data"]
        + pipeline["failed_pre_screen"]
        + pipeline["no_chain"]
        + pipeline["failed_score"]
        + pipeline["failed_contracts"]
        + pipeline["failed_direction"]
        + pipeline["failed_shortlist"]
    )
    assert accounted == pipeline["scanned"] == 3
    # 1 gated on trend, 1 trimmed by the cap, 1 returned.
    assert pipeline["failed_direction"] == 1
    assert pipeline["failed_shortlist"] == 1
    assert pipeline["candidates"] == 1
