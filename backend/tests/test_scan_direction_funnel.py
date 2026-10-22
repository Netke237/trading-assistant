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


def _card(symbol: str, trend: int, direction: str = "Bearish") -> TradeCardData:
    """A minimal PASS candidate whose only interesting axis is `trend` — the
    single field the direction-conviction gate reads.

    `direction` only dresses the card consistently (a Bullish card should not
    describe itself as a put). The gate reads `req.direction` off the REQUEST,
    never `_c.direction`, so these cases exercise the right floor either way —
    but a card that says "Bearish" inside an assertion about Bullish behaviour
    is a trap for the first code path that ever does consult the card.
    """
    right = "P" if direction == "Bearish" else "C"
    return TradeCardData(
        symbol=symbol,
        company=symbol,
        price=100.0,
        direction=direction,
        status="PASS",
        stockScore=70,
        stockConfidence="PASS",
        stockBreakdown=ScoreBreakdown(
            trend=trend, pullback=50, trigger=50, event=50, volatility=50,
        ),
        contract=f"{symbol}|100|2026-06-20|{right}",
        contractScore=60,
        contractConfidence="PASS",
        contractBreakdown=ContractScoreBreakdown(
            dteFit=50, delta=50, ivAttractiveness=50, liquidity=50, spread=50,
        ),
        contractDetails=ContractDetails(
            strike=100, expiry="2026-06-20", right=right, mid=1.0,
            delta=-0.5 if direction == "Bearish" else 0.5,
            theta=-0.05, ivRank=50, dte=55,
        ),
        entry=TradeEntry(limit=1.0, maxFill=1.05, orderType="Limit"),
        exit=TradeExit(
            invalidation=105.0 if direction == "Bearish" else 95.0,
            premiumStop=0.6, timeStopDays=10,
            target=90.0 if direction == "Bearish" else 110.0,
        ),
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


def _cards(*specs: tuple[str, int], direction: str = "Bearish") -> dict[str, object]:
    return {sym: _card(sym, trend, direction) for sym, trend in specs}


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
        + pipeline["failed_direction_unmeasured"]
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
    # P3c item 1: the producer's literal lives in stock_scan._regime_data_drop,
    # which the regex above cannot see, so the guard relies on this entry.
    ("regime data unavailable: no completed 15-min bars for X", "failed_data"),
    ("regime data unavailable: no completed 15-min bars for X (fetch failed: boom)", "failed_data"),
    # P3c item 2: literal lives in stock_scan._direction_conviction_drop.
    # Its own bucket (open_questions[53]): removed before the chain fetch.
    ("direction_conviction_unmeasured: no trend measurement for Bullish Swing", "failed_direction_unmeasured"),
    # STOCKS-HORIZON-P0A A2: a `scope: scan` symbol from universe_exclusions.yaml,
    # skipped before any per-symbol work. A data drop.
    ("Excluded (data): price feed ended 2024-05-03; likely delisted", "failed_data"),
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


# ── The gate's thresholds, on the OPTIONS path ───────────────────────────────
#
# This file used to exercise the gate only at Bearish/Position and
# Bearish/Intraday — no Bullish case, no Swing case, and no boundary value
# anywhere. The cross-mode check that covered the rest lived in
# test_stock_scan_funnel.py and worked by regex-parsing the `_DIRECTION_TREND_GATE`
# dict out of scan.py's source; when the thresholds moved into
# scoring_rules.yaml that dict went away and its coverage of THIS path went with
# it. So the options gate is pinned here directly, against the same literal
# contract the stock suite uses.
#
# Deliberately literal rather than read back from config_loader: a test that
# derives its expectations from the code under test asserts only that the code
# equals itself. A threshold change is supposed to fail here.
_OPTIONS_FLOORS: dict[tuple[str, str], int | None] = {
    ("Bearish", "Swing"):    30,
    ("Bearish", "Position"): 40,
    ("Bullish", "Swing"):    30,
    ("Bullish", "Position"): 40,
    ("Bearish", "Intraday"): None,   # exempt
    ("Bullish", "Intraday"): None,   # exempt
}


@pytest.mark.parametrize("direction,horizon,trend,gated", [
    # One point either side of each of the four real floors.
    ("Bearish", "Position", 39, True),  ("Bearish", "Position", 40, False),
    ("Bearish", "Swing",    29, True),  ("Bearish", "Swing",    30, False),
    ("Bullish", "Position", 39, True),  ("Bullish", "Position", 40, False),
    ("Bullish", "Swing",    29, True),  ("Bullish", "Swing",    30, False),
    # A strong trend in the traded direction survives on BOTH sides. The
    # bearish half is the inversion regression: under the old ceiling, 85 on a
    # Bearish scan was thrown away by the options path too.
    ("Bearish", "Position", 85, False), ("Bullish", "Position", 85, False),
    ("Bearish", "Swing",    85, False), ("Bullish", "Swing",    85, False),
    # Intraday is exempt in both directions, at any score.
    ("Bearish", "Intraday",  1, False), ("Bullish", "Intraday",  1, False),
])
def test_options_gate_matches_the_mirrored_floor_contract(
    client, direction, horizon, trend, gated,
):
    """The options endpoint screens on the floors in _OPTIONS_FLOORS.

    These are the same numbers test_stock_scan_funnel.py's _MIRRORED_FLOORS
    pins for the stock endpoint. The two modes are supposed to screen
    identically; asserting the same contract from both sides is what makes a
    divergence fail rather than pass quietly in one of them.
    """
    floor = _OPTIONS_FLOORS[(direction, horizon)]
    assert gated == (floor is not None and trend < floor), (
        "the parametrize case disagrees with the floor contract it is meant to "
        "exercise — fix the case, not the assertion"
    )

    body = _run(client, _cards(("AAA", trend), direction=direction),
                direction=direction, horizon=horizon)
    assert body["pipeline"]["failed_direction"] == (1 if gated else 0)
    assert len(body["candidates"]) == (0 if gated else 1)


@pytest.mark.parametrize("horizon", ["Swing", "Position"])
def test_options_bearish_gate_is_a_floor_not_a_ceiling(client, horizon):
    """The inversion regression on the options path, stated as the trading
    claim: the strongest short setup must reach the ranking table.

    Asserted through the endpoint, not against the resolver's return value —
    flipping the comparison in scan.py has to break this.
    """
    strong_downtrend = _run(client, _cards(("AAA", 95)),
                            direction="Bearish", horizon=horizon)
    assert strong_downtrend["pipeline"]["failed_direction"] == 0, (
        f"Bearish/{horizon} threw away a trend score of 95 — the strongest "
        f"short setup there is. The gate is inverted again."
    )
    assert [c["symbol"] for c in strong_downtrend["candidates"]] == ["AAA"]

    no_structure = _run(client, _cards(("AAA", 5)),
                        direction="Bearish", horizon=horizon)
    assert no_structure["pipeline"]["failed_direction"] == 1, (
        f"Bearish/{horizon} admitted a trend score of 5 — the gate no longer "
        f"removes candidates with no directional structure, which is its job."
    )


def test_options_rejection_reason_names_the_floor_it_applied(client):
    """The reason string the user reads must say `<` and carry the threshold as
    an integer. `direction_conviction:` is also the prefix both funnel
    classifiers match on, so a reword here silently relocates these rejections
    into the residual and the UI renders them as errors."""
    body = _run(client, _cards(("AAA", 10)), direction="Bearish", horizon="Position")

    reasons = [r["reason"] for r in body["rejected"]]
    assert reasons == ["direction_conviction: trend 10 < 40 for Bearish Position"], reasons
    assert body["pipeline"]["failed_direction"] == 1
    assert body["pipeline"]["other_rejected"] == 0


# ── The config fail-fast, end to end ─────────────────────────────────────────
#
# Round 2 audit: deleting the whole try/except fail-fast from this router left
# the suite green, so none of that protection was actually guarded.

_BAD_CFG = {"horizons": {"position": {"direction_conviction": {"bearish_min_tren": 30}}}}


def test_a_malformed_threshold_fails_the_options_scan_before_any_fetching(client):
    """A config typo must stop the scan, name itself, and cost nothing.

    500 rather than 4xx deliberately: the request is fine and the server's YAML
    is broken, so it must not be confused with the genuine 422 this same
    endpoint raises for a malformed user override, and it has to reach
    server-error alerting. The check sits above the batch quote call, so a
    broken config does not burn a rate-limited scan of the whole universe
    first — it used to run after the entire fan-out.
    """
    from unittest.mock import MagicMock

    fetch = MagicMock(return_value={})
    with ExitStack() as stack:
        stack.enter_context(patch("app.services.config_loader.load_scoring_cfg",
                                  return_value=_BAD_CFG))
        stack.enter_context(patch("app.routers.scan.fetch_quotes", fetch))
        stack.enter_context(patch(
            "app.routers.scan.get_tradier_creds",
            return_value=("tok", "https://example.invalid"),
        ))
        r = client.post("/api/scan", json={
            "universe": ["AAA"], "direction": "Bearish", "horizon": "Position",
            "overrides": {},
        })

    assert r.status_code == 500, r.text
    assert "bearish_min_tren" in r.json()["detail"], r.json()
    assert fetch.call_count == 0, (
        "the universe quote fetch ran before the config was checked — the "
        "fail-fast moved back below the fan-out"
    )


# ── Universe exclusion list (STOCKS-HORIZON-P0A A2) ──────────────────────────
#
# A `scope: scan` symbol in config/universe_exclusions.yaml is skipped before
# any per-symbol work, reported in `rejected` as "Excluded (data): <reason>",
# counted in `scanned` and in the `failed_data` bucket, so the sum invariant
# still holds. The shipped file lists PXD with scope scan (pinned by
# test_universe_exclusions.py).

_BROKEN_LIST = "universe_exclusions.yaml: 'version' must be 1, got 2"


def _pxd_reason() -> str:
    from app.data.universe_exclusions import load_exclusions
    return load_exclusions()["PXD"].reason


def _post_options_scan(client, universe, fake_process, *extra_patches):
    from unittest.mock import MagicMock

    quotes = MagicMock(return_value={})
    with ExitStack() as stack:
        stack.enter_context(patch("app.routers.scan._process_symbol", fake_process))
        stack.enter_context(patch(
            "app.routers.scan.get_tradier_creds",
            return_value=("tok", "https://example.invalid"),
        ))
        stack.enter_context(patch("app.routers.scan.fetch_quotes", quotes))
        stack.enter_context(patch(
            "app.services.historical_store.get_bars", AsyncMock(return_value=[]),
        ))
        stack.enter_context(patch(
            "app.routers.scan.get_fundamentals", AsyncMock(return_value=None),
        ))
        for p in extra_patches:
            stack.enter_context(p)
        r = client.post("/api/scan", json={
            "universe": universe, "direction": "Bearish", "horizon": "Position",
            "overrides": {},
        })
    return r, quotes


def test_an_excluded_symbol_is_rejected_as_data_and_never_processed(client):
    """A typed excluded ticker is skipped too: the filter runs on the FINAL list."""
    processed: list[str] = []

    async def _fake_process(symbol, *_a, **_kw):
        processed.append(symbol)
        return _card(symbol, 60)   # clears the Bearish/Position floor

    r, quotes = _post_options_scan(client, ["AAPL", "PXD"], _fake_process)
    assert r.status_code == 200, r.text
    body = r.json()

    assert processed == ["AAPL"], "PXD reached per-symbol work"
    assert "PXD" not in quotes.call_args.args[0], "PXD reached the batch quote fetch"
    reasons = {x["symbol"]: x["reason"] for x in body["rejected"]}
    assert reasons["PXD"] == f"Excluded (data): {_pxd_reason()}"
    assert [c["symbol"] for c in body["candidates"]] == ["AAPL"]

    pipeline = body["pipeline"]
    assert pipeline["failed_data"] == 1
    assert pipeline["other_rejected"] == 0, "the exclusion leaked into the residual"
    assert pipeline["scanned"] == 2 == _accounted(pipeline)


def test_a_broken_exclusion_list_fails_the_options_scan_before_any_symbol_work(client):
    """A broken list must not silently scan everything: named 500, nothing fetched."""
    from app.data.universe_exclusions import ExclusionListError

    processed: list[str] = []

    async def _fake_process(symbol, *_a, **_kw):
        processed.append(symbol)
        return _card(symbol, 60)

    r, quotes = _post_options_scan(
        client, ["AAPL"], _fake_process,
        patch("app.data.universe_exclusions.load_exclusions",
              side_effect=ExclusionListError(_BROKEN_LIST)),
    )
    assert r.status_code == 500, r.text
    assert r.json()["detail"] == _BROKEN_LIST
    assert processed == []
    assert quotes.call_count == 0
