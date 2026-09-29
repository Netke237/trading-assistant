"""Tests for shortlist cap enforcement in POST /api/scan."""

from contextlib import ExitStack
from unittest.mock import patch, AsyncMock
from app.scoring.stock_scorer import StockScoreCard, RuleResult
from app.scoring.contract_validator import ContractScoreCard, ContractScoreBreakdown

_MOCK_CANDLES = [
    {
        "time": f"2026-04-{i + 1:02d}",
        "open": 184.0, "high": 190.0, "low": 182.0, "close": 187.0,
        "volume": 1_000_000,
    }
    for i in range(30)
]

_MOCK_CHAIN = [
    {
        "strike": 190, "expiry": "2026-06-20", "price": 2.50, "spread": 0.20,
        "delta": 0.45, "theta": -0.05, "ivRank": 55, "dte": 30,
        "right": "C", "volume": 500,
    }
]

_PASS_RULES = [
    RuleResult("trend",    "PASS", 80, {}),
    RuleResult("pullback", "PASS", 75, {}),
    RuleResult("trigger",  "PASS", 70, {}),
    RuleResult("event",    "PASS", 85, {}),
    RuleResult("vol",      "PASS", 80, {}),
]

_PASS_CONTRACT_BREAKDOWN = ContractScoreBreakdown(
    liquidity_score=75, spread_score=75, delta_score=75,
    dte_score=75, iv_rank_score=75, oi_score=75,
)


def _pass_card(symbol, *_, **__) -> StockScoreCard:
    return StockScoreCard(
        symbol=symbol,
        direction="Bullish",
        horizon="Swing",
        score=80,
        status="PASS",
        rules=_PASS_RULES,
    )


def _pass_contract(contract, *_, **__) -> ContractScoreCard:
    sym = contract.get("symbol", "SYM")
    strike = float(contract.get("strike", 190.0))
    expiry = contract.get("expiry", "2026-06-20")
    right = contract.get("right", "C")
    return ContractScoreCard(
        contract_id=f"{sym}|{int(strike)}|{expiry}|{right}",
        symbol=sym,
        strike=strike,
        expiry=expiry,
        is_call=right == "C",
        score=75,
        status="PASS",
        breakdown=_PASS_CONTRACT_BREAKDOWN,
    )


def _enter_shortlist_patches(truncate):
    stack = ExitStack()
    stack.enter_context(patch("app.routers.scan.fetch_price_async",            AsyncMock(return_value=185.0)))
    stack.enter_context(patch("app.routers.scan.fetch_candles_async",           AsyncMock(return_value=_MOCK_CANDLES)))
    stack.enter_context(patch("app.routers.scan.fetch_option_chain_async",      AsyncMock(return_value=_MOCK_CHAIN)))
    stack.enter_context(patch("app.routers.scan.fetch_company_name_async",      AsyncMock(return_value=None)))
    stack.enter_context(patch("app.routers.scan.fetch_fundamentals_calendar",   AsyncMock(return_value=None)))
    stack.enter_context(patch("app.routers.scan.score_stock",                 side_effect=_pass_card))
    stack.enter_context(patch("app.routers.scan.validate_contract",           side_effect=_pass_contract))
    stack.enter_context(patch("app.routers.scan._settings", {"scan": {"shortlist_max_candidates": truncate}}))
    return stack


def test_shortlist_cap_enforced(client):
    """20 symbols all scoring PASS, cap=5 -> <=5 candidates, truncated=True, original_count=20."""
    symbols = [f"SYM{i:02d}" for i in range(20)]

    with _enter_shortlist_patches(truncate=5):
        r = client.post("/api/scan", json={
            "universe": symbols,
            "direction": "Bullish",
            "horizon": "Swing",
        })

    assert r.status_code == 200
    body = r.json()
    assert body["shortlist_truncated"] is True
    assert body["original_count"] == 20
    assert len(body["candidates"]) <= 5


def test_shortlist_not_truncated_when_below_cap(client):
    """2 symbols, cap=10 -> shortlist_truncated=False."""
    with _enter_shortlist_patches(truncate=10):
        r = client.post("/api/scan", json={
            "universe": ["AAPL", "MSFT"],
            "direction": "Bullish",
            "horizon": "Swing",
        })
    assert r.status_code == 200
    body = r.json()
    assert body["shortlist_truncated"] is False


# ── The cap keeps the BEST names, not the first ones ──────────────────────────
#
# `candidates` is built in universe-file order, and the cap used to slice it
# unsorted — so it kept whatever sat early in sp500.csv and dropped higher
# scorers further down (a measured Semi-annual scan lost PFE, CRM, GILD, HPE and
# SMCI while keeping lower scorers), and the dropped names appeared nowhere in
# the response. Each universe below puts the best names LAST, so an unsorted
# slice fails every assertion.

def _enter_ranked_patches(truncate, cards: dict[str, tuple[int, str]]):
    """`cards` maps symbol -> (stock score, stock status)."""
    def _card(symbol, *_, **__):
        score, status = cards[symbol]
        return StockScoreCard(symbol=symbol, direction="Bullish", horizon="Swing",
                              score=score, status=status, rules=_PASS_RULES)
    stack = _enter_shortlist_patches(truncate)
    stack.enter_context(patch("app.routers.scan.score_stock", side_effect=_card))
    return stack


def _scan(client, symbols):
    r = client.post("/api/scan", json={
        "universe": symbols, "direction": "Bullish", "horizon": "Swing",
    })
    assert r.status_code == 200
    return r.json()


def test_shortlist_keeps_highest_scores_not_universe_order(client):
    cards = {f"SYM{i:02d}": (70 + i, "PASS") for i in range(10)}  # best is last
    with _enter_ranked_patches(3, cards):
        body = _scan(client, list(cards))

    assert [c["symbol"] for c in body["candidates"]] == ["SYM09", "SYM08", "SYM07"]
    assert body["shortlist_truncated"] is True
    assert body["original_count"] == 10


def test_trimmed_names_are_recorded_and_counted_once(client):
    cards = {f"SYM{i:02d}": (70 + i, "PASS") for i in range(10)}
    with _enter_ranked_patches(3, cards):
        body = _scan(client, list(cards))

    trimmed = [r for r in body["rejected"] if r["reason"].startswith("Shortlist cap:")]
    assert sorted(r["symbol"] for r in trimmed) == [f"SYM{i:02d}" for i in range(7)]
    # Rank order, and the reason names the score and position that lost.
    assert trimmed[0]["symbol"] == "SYM06"
    assert trimmed[0]["reason"] == "Shortlist cap: PASS score 76 contract 75 ranked 4 of 10 (cap 3)"

    pipeline = body["pipeline"]
    assert pipeline["failed_shortlist"] == 7
    # Classified by its own bucket, NOT also swept into the residual.
    assert pipeline["other_rejected"] == 0
    assert pipeline["candidates"] + pipeline["failed_shortlist"] == pipeline["scanned"]


def test_a_pass_is_never_pushed_out_by_a_higher_scoring_caution(client):
    cards = {
        "EARLY": (95, "CAUTION"),   # higher score, worse status, first in file
        "LATE":  (72, "PASS"),
    }
    with _enter_ranked_patches(1, cards):
        body = _scan(client, list(cards))

    assert [c["symbol"] for c in body["candidates"]] == ["LATE"]
    assert body["candidates"][0]["finalStatus"] == "PASS"
    trimmed = [r for r in body["rejected"] if r["reason"].startswith("Shortlist cap:")]
    assert [r["symbol"] for r in trimmed] == ["EARLY"]


def test_nothing_is_recorded_as_trimmed_below_the_cap(client):
    cards = {"AAA": (71, "PASS"), "BBB": (80, "PASS")}
    with _enter_ranked_patches(10, cards):
        body = _scan(client, list(cards))

    # Ranked even when nothing is cut: _compute_deltas reads position as rank.
    assert [c["symbol"] for c in body["candidates"]] == ["BBB", "AAA"]
    assert not any(r["reason"].startswith("Shortlist cap:") for r in body["rejected"])
    assert body["pipeline"]["failed_shortlist"] == 0


# ── finalStatus, not stock status; contract score breaks ties; ties are stable ─
#
# Every test above gives every contract PASS/75, so finalStatus == stock status
# and contractScore never differs: a sort keyed on `status`, or one missing the
# contract-score tiebreak, would pass all of them. Here each symbol gets its own
# strike (via the chain mock), and the contract validator keys its verdict off
# that strike.

def _enter_contract_patches(truncate, spec: dict[str, tuple[int, str, int, str]]):
    """`spec` maps symbol -> (stock score, stock status, contract score, contract status)."""
    strikes = {sym: 190 + i for i, sym in enumerate(spec)}
    by_strike = {strikes[s]: v for s, v in spec.items()}

    async def _chain(_client, symbol, **_):
        return [{**_MOCK_CHAIN[0], "strike": strikes[symbol]}]

    def _contract(contract, *_, **__):
        strike = float(contract.get("strike"))
        _, _, c_score, c_status = by_strike[int(strike)]
        right = contract.get("right", "C")
        return ContractScoreCard(
            contract_id=f"X|{int(strike)}|2026-06-20|{right}", symbol="X",
            strike=strike, expiry="2026-06-20", is_call=right == "C",
            score=c_score, status=c_status, breakdown=_PASS_CONTRACT_BREAKDOWN,
        )

    stack = _enter_ranked_patches(truncate, {s: (v[0], v[1]) for s, v in spec.items()})
    stack.enter_context(patch("app.routers.scan.fetch_option_chain_async", side_effect=_chain))
    stack.enter_context(patch("app.routers.scan.validate_contract", side_effect=_contract))
    return stack


def test_ranks_on_final_status_not_stock_status(client):
    # EARLY is a PASS stock with a CAUTION contract -> finalStatus CAUTION. Its
    # stock score is higher, so a sort keyed on stock `status` would keep it.
    spec = {"EARLY": (95, "PASS", 75, "CAUTION"), "LATE": (72, "PASS", 75, "PASS")}
    with _enter_contract_patches(1, spec):
        body = _scan(client, list(spec))

    assert [c["symbol"] for c in body["candidates"]] == ["LATE"]
    trimmed = [r for r in body["rejected"] if r["reason"].startswith("Shortlist cap:")]
    assert [r["symbol"] for r in trimmed] == ["EARLY"]
    assert trimmed[0]["reason"].startswith("Shortlist cap: CAUTION score 95")


def test_contract_score_breaks_a_stock_score_tie(client):
    spec = {"AAA": (80, "PASS", 70, "PASS"), "BBB": (80, "PASS", 90, "PASS")}
    with _enter_contract_patches(1, spec):
        body = _scan(client, list(spec))

    assert [c["symbol"] for c in body["candidates"]] == ["BBB"]
    # AAA must leave by the CAP, not the contract validator -- otherwise this
    # passes with no tiebreak in the sort at all.
    trimmed = [r for r in body["rejected"] if r["reason"].startswith("Shortlist cap:")]
    assert [r["reason"] for r in trimmed] == [
        "Shortlist cap: PASS score 80 contract 70 ranked 2 of 2 (cap 1)"]


def test_an_exact_tie_keeps_universe_order(client):
    spec = {"CCC": (80, "PASS", 75, "PASS"), "AAA": (80, "PASS", 75, "PASS"),
            "BBB": (80, "PASS", 75, "PASS")}
    with _enter_contract_patches(2, spec):
        body = _scan(client, list(spec))

    assert [c["symbol"] for c in body["candidates"]] == ["CCC", "AAA"]


# ── The scan passes the validator's DTE floor to the expiry pick ──────────────
# (Lives here for the scan-level patch harness above.) Only one expiry is
# fetched per symbol; without the floor a Custom 15-200d hold (window 30-400,
# centre 215, floor 201) could pick a 199d monthly the validator then rejects.

def test_scan_passes_the_dte_floor_to_the_chain_fetch(client):
    seen = []

    async def _chain(_client, symbol, **kw):
        seen.append((kw.get("dte_bounds"), kw.get("min_dte_floor")))
        return _MOCK_CHAIN

    with _enter_shortlist_patches(10) as stack:
        stack.enter_context(patch("app.routers.scan.fetch_option_chain_async", side_effect=_chain))
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Position",
            "hold_min_days": 15, "hold_max_days": 200,
        })
    assert r.status_code == 200
    assert seen and all(s == ((30, 400), 201) for s in seen), seen


def test_bearish_spread_legs_use_the_main_contracts_expiry(client):
    """Bearish scans fetch two more chains for the spread legs. They must use the
    main contract's expiry, which the legs are labelled with; if they re-picked
    from the bounds, a drift would put another expiry's strikes under this label."""
    seen = []

    async def _chain(_client, symbol, **kw):
        seen.append((kw.get("expiry"), kw.get("dte_bounds"), kw.get("min_dte_floor")))
        return [{**_MOCK_CHAIN[0], "right": kw.get("option_type", "C"),
                 "strike": s, "expiry": "2027-06-18"} for s in (180, 185, 190, 195)]

    with _enter_shortlist_patches(10) as stack:
        stack.enter_context(patch("app.routers.scan.fetch_option_chain_async", side_effect=_chain))
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bearish", "horizon": "Position",
            "hold_min_days": 15, "hold_max_days": 200,
        })
    assert r.status_code == 200
    main, legs = seen[0], seen[1:]
    assert main == (None, (30, 400), 201)
    assert r.json()["candidates"], r.json()["rejected"]  # else nothing below is exercised
    assert len(legs) == 2, seen
    assert all(e == "2027-06-18" and b == (30, 400) and f == 201 for e, b, f in legs), seen
