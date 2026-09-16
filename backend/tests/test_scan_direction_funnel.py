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
    """Bearish/Position gates out trend < 40. Five candidates all below it must
    leave the funnel reporting 0 — not 5 — and name where they went.

    trend=20, not the 60 this used to use: the gate became a FLOOR on the
    bearish side on 2026-09-16, so 60 is a strong downtrend and now survives.
    """
    body = _run(client, _cards(*((s, 20) for s in ("AAA", "BBB", "CCC", "DDD", "EEE"))),
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
    body = _run(client, _cards(("AAA", 20), ("BBB", 60), ("CCC", 70)),
                direction="Bearish", horizon="Position")

    pipeline = body["pipeline"]
    assert pipeline["candidates"] == len(body["candidates"]) == 2
    assert pipeline["failed_direction"] == 1
    assert {c["symbol"] for c in body["candidates"]} == {"BBB", "CCC"}
    assert not body["direction_banner"], "survivors exist — no all-stripped banner"


def test_funnel_reports_no_direction_failures_when_no_gate_applies(client):
    """Intraday is exempt from the gate, so nothing is attributed to it.

    trend=10, not 90: at Position these two would be gated, so the exemption is
    what carries the assertion. With 90 — which now clears every floor — the
    test would pass whether Intraday were exempt or not.
    """
    body = _run(client, _cards(("AAA", 10), ("BBB", 10)),
                direction="Bearish", horizon="Intraday")

    pipeline = body["pipeline"]
    assert pipeline["failed_direction"] == 0
    assert pipeline["candidates"] == len(body["candidates"]) == 2


def test_shortlist_cap_is_accounted_for_rather_than_silently_trimming(client):
    """The cap trims the returned list, so the funnel must show that too —
    otherwise moving `candidates` past the cap just relocates the same lie."""
    body = _run(client, _cards(("AAA", 60), ("BBB", 60), ("CCC", 60)),
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
    outcomes: dict[str, object] = _cards(("AAA", 60))   # clears the bearish floor
    outcomes["BOOM"] = RuntimeError("")   # empty message, as asyncio errors often are

    body = _run(client, outcomes, direction="Bearish", horizon="Position")

    pipeline = body["pipeline"]
    assert pipeline["other_rejected"] == 1, "the raising symbol vanished from the funnel"
    assert _accounted(pipeline) == pipeline["scanned"] == 2
    assert body["state"] == "PARTIAL", "one raised, one survived"


def test_a_rejection_matching_no_predicate_is_counted_not_dropped(client):
    """The buckets match on reason text. A reason nobody classified must still
    land somewhere rather than silently leaving the funnel short."""
    outcomes: dict[str, object] = _cards(("AAA", 60))   # clears the bearish floor
    outcomes["ZZZ"] = RejectedCandidate(symbol="ZZZ", reason="some brand new reason")

    body = _run(client, outcomes, direction="Bearish", horizon="Position")

    pipeline = body["pipeline"]
    assert pipeline["other_rejected"] == 1
    assert _accounted(pipeline) == pipeline["scanned"] == 2


#  The reason strings `_process_symbol` actually emits, copied from their
#  producers in routers/scan.py. The residual makes a misclassification
#  INVISIBLE to the accounting invariant: reword a producer and its bucket
#  collapses to 0, `other_rejected` silently absorbs it, and `scanned == sum`
#  still holds. Only pinning real strings to real buckets catches that.
_REAL_REASONS = [
    # scan.py:511, 515, 517, 526, 530, 599, 607, 688, 715, 717 — verbatim.
    ("no market data",                              "failed_data"),
    ("price filter ($12.30 < $20.00 min)",          "failed_data"),
    ("price filter ($812.30 > $500.00 max)",        "failed_data"),
    ("cap filter ($1.2B < $2.0B min)",              "failed_data"),
    ("cap filter ($900.0B > $500.0B max)",          "failed_data"),
    ("Pre-screen: score 29 rejected",               "failed_pre_screen"),
    ("no option chain",                             "no_chain"),
    ("Score gate: score 58 rejected",               "failed_score"),
    ("contracts rejected: spread_too_wide",         "failed_contracts"),
    ("all contracts rejected",                      "failed_contracts"),
]


def test_every_options_reason_producer_is_classified():
    """Guards _REAL_REASONS against going stale. The previous commit claimed the
    options path got the same staleness guard as the stock one; it did not, so
    the failure mode described at length there — reword a producer, its bucket
    collapses to 0, the residual absorbs it, `scanned == sum` still holds and
    nothing fails — stayed live on this path."""
    import inspect, re
    from app.routers import scan as mod

    src = inspect.getsource(mod)
    # Reasons appear as reason="..." or reason=f"..." on RejectedCandidate.
    emitted = {s.strip() for s in re.findall(r'reason=f?"([^"{]*)', src)}
    emitted = {s for s in emitted if s}
    assert emitted, "reason-producer regex matched nothing — this test is vacuous"

    # `c.startswith(e)` ONLY — the same strictness as the stock guard. The
    # reverse direction (`e.startswith(c)`) was load-bearing purely to let the
    # bare "direction_conviction:" entry match the captured
    # "direction_conviction: trend " prefix, and it cost far more than it
    # bought: with it, a genuinely novel reason like
    # "no option chain within the DTE window" was accepted as covered by
    # "no option chain" — while `_is_no_chain` matches on equality, so that
    # reason lands in the residual and is shown to the user as an error.
    # Listing the real captured prefix instead removes the need for it.
    covered = [r for r, _ in _REAL_REASONS] + ["direction_conviction: trend "]
    unclassified = [
        e for e in emitted if not any(c.startswith(e) for c in covered)
    ]
    assert not unclassified, (
        f"new rejection reason(s) with no bucket decision: {sorted(unclassified)}"
    )


@pytest.mark.parametrize("reason,bucket", _REAL_REASONS)
def test_each_real_reason_lands_in_its_own_bucket(client, reason, bucket):
    """One symbol, one real reason, one bucket — and nothing in the residual."""
    body = _run(client, {"ZZZ": RejectedCandidate(symbol="ZZZ", reason=reason)},
                direction="Bearish", horizon="Position")

    pipeline = body["pipeline"]
    assert pipeline[bucket] == 1, f"{reason!r} no longer classifies as {bucket}"
    assert pipeline["other_rejected"] == 0, (
        f"{reason!r} fell through to the residual — its producer was reworded "
        f"without updating the predicate, and the funnel would report it as an error"
    )
    assert _accounted(pipeline) == pipeline["scanned"] == 1


def test_every_scanned_symbol_is_accounted_for_in_the_funnel(client):
    """The full invariant, with every bucket non-trivially exercised at once:
    a direction strip, a shortlist trim, a raising symbol and an unclassified
    rejection — so the assertion cannot pass by everything being zero."""
    outcomes: dict[str, object] = _cards(
        ("AAA", 10),   # stripped by the direction gate — below the floor
        ("BBB", 60),   # survives
        ("CCC", 60),   # survives, then trimmed by the cap
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
