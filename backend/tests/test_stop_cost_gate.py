"""Stop-vs-premium gate on the Black-Scholes-at-today basis (Q3 / Q7).

Spec: docs/superpowers/plans/2026-09-02-gate-basis-spec.md §2.1-2.2, tests 3-8.
The frontend presenter rewrite (§3, tests 1-2) is a separate batch; nothing
here touches it.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.scoring.stop_cost import (
    MIN_PREMIUM, RISK_FREE_RATE, compute_stop_cost, horizon_key,
    pass_max_fraction_for,
)
from app.scoring.structural_stop import StructuralStop

FIXTURES = Path(__file__).parent / "fixtures"


def _client() -> TestClient:
    from app.routers.contracts import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# The reference chain of the spec's §1 and of the schematic artifact
# (docs/superpowers/specs/2026-09-02-trade-card-schematic.html): stock $201.86
# → stop $185.87 (−7.9%), 45 DTE, calls, skewed surface. Premium and the
# artifact's published "left at stop" / "new %" columns; the IV is NOT given —
# the gate backs it out of the premium, which is the whole point of the test.
REF_STOCK, REF_STOP, REF_DTE = 201.86, 185.87, 45
REF_CHAIN = [
    # strike, premium, left at stop, fraction, Swing @ 0.70 verdict
    (195, 13.21, 4.87, 0.63, "PASS"),
    (200, 10.66, 3.70, 0.65, "PASS"),
    (205,  8.49, 2.76, 0.67, "PASS"),
    (210,  6.67, 2.03, 0.70, "CAUTION"),
    (215,  5.21, 1.49, 0.71, "CAUTION"),   # ← the project's reference contract
    (220,  4.05, 1.10, 0.73, "CAUTION"),
    (230,  2.48, 0.62, 0.75, "CAUTION"),
    (240,  1.55, 0.36, 0.77, "CAUTION"),
]


def _ref_cost(strike: float, premium: float, **kw):
    return compute_stop_cost(
        stop_price=REF_STOP, stock_price=REF_STOCK, strike=strike, dte=REF_DTE,
        premium=premium, is_call=True, horizon_preset="Swing", **kw,
    )


# ── Test 6 — the reference chain, and the split it must produce ───────────────

class TestReferenceChain:
    def test_reproduces_the_published_chain_to_within_a_cent(self):
        """Spec test 6. The artifact's dollars-left column is the contract this
        gate signs up to: back the IV out of each mid, reprice at the stop with
        today's remaining life, and the eight strikes come back where the
        artifact published them."""
        for strike, premium, left, fraction, _ in REF_CHAIN:
            cost = _ref_cost(strike, premium)
            assert cost is not None, f"K={strike} returned no cost"
            # "to within a cent", inclusive — 2.77 against a published 2.76 is
            # a one-cent agreement, and binary subtraction puts that difference
            # a hair OVER 0.01, so the tolerance carries an epsilon.
            assert abs(cost.value_at_stop - left) <= 0.01 + 1e-9, (
                f"K={strike}: valueAtStop {cost.value_at_stop} vs published {left}"
            )
            assert abs(cost.loss_dollar - (premium - left)) <= 0.01 + 1e-9
            assert cost.fraction == pytest.approx(fraction, abs=0.005), (
                f"K={strike}: fraction {cost.fraction} vs published {fraction}"
            )
            assert cost.basis == "bs_today"

    def test_the_swing_line_splits_the_chain_three_pass_five_caution(self):
        """Spec test 6, second half — asserted, not a guide (the spec and the
        artifact agree exactly on this split). It is simultaneously the
        regression guard on Q7's Swing value: at the OLD 0.80 line all eight
        strikes read PASS and the gate says nothing at all."""
        verdicts = [_ref_cost(k, p).status for k, p, _, _, _ in REF_CHAIN]
        assert verdicts == [v for *_, v in REF_CHAIN]
        assert verdicts.count("PASS") == 3
        assert verdicts.count("CAUTION") == 5

    def test_the_old_delta_linear_ruler_could_not_produce_this_split(self):
        """Why the basis had to change. The old measure is
        min(|stop − spot| × |delta|, premium) / premium; on this stop it pins
        the four cheapest strikes at exactly 1.0, so no threshold anywhere can
        rank them. Delta here is the gate's own floor-free |Δ| at the money-ish
        strikes — the point stands for any delta at all, because the CAP is
        what destroys the ranking, not the slope."""
        move = REF_STOCK - REF_STOP
        pinned = sum(1 for _, premium, _, _, _ in REF_CHAIN if move * 0.45 >= premium)
        assert pinned >= 4

    def test_a_tight_stop_passes_the_whole_chain(self):
        """The artifact's own caveat, made executable: this is a stop-DISTANCE
        meter, not a strike picker. On a −2.5% stop the same eight contracts
        all pass, so a CAUTION here is a statement about the stop, and a reader
        who takes it as "this strike is bad" is misreading it."""
        tight = round(REF_STOCK * 0.975, 2)
        for strike, premium, _, _, _ in REF_CHAIN:
            cost = compute_stop_cost(
                stop_price=tight, stock_price=REF_STOCK, strike=strike, dte=REF_DTE,
                premium=premium, is_call=True, horizon_preset="Swing",
            )
            assert cost is not None and cost.status == "PASS", f"K={strike}: {cost}"


# ── Test 7 — the thresholds themselves ────────────────────────────────────────

class TestThresholds:
    def test_yaml_carries_q7s_re_derived_lines(self):
        """Spec test 7. 0.80 / 0.70 / 0.60 — they had to move with the basis:
        under the new ruler the WORST contract on the reference chain reads
        77%, so on the old Swing line of 0.80 the gate would be permanently
        silent."""
        assert pass_max_fraction_for("Intraday") == 0.80
        assert pass_max_fraction_for("Swing") == 0.70
        assert pass_max_fraction_for("Position") == 0.60

    def test_an_absent_or_unknown_preset_falls_toward_caution(self):
        """Swing, not the loosest line — "no preset was sent" must not buy a
        contract the Intraday tolerance."""
        assert horizon_key(None) == "swing"
        assert horizon_key("Weekly") == "swing"
        assert horizon_key("") == "swing"
        assert horizon_key("  swing  ") == "swing"
        assert horizon_key("INTRADAY") == "intraday"
        assert pass_max_fraction_for("Weekly") == pass_max_fraction_for("Swing")

    @pytest.mark.parametrize("preset,expected", [
        # The seven-key preset domain, collapsed exactly as HORIZON_PRESETS'
        # scoringHorizon column does.
        ("Intraday", "intraday"), ("Swing", "swing"), ("Position", "position"),
        ("Quarterly", "position"), ("SemiAnnual", "position"), ("Annual", "position"),
        ("Custom", "swing"),
        # The labels and display strings the same helpers produce.
        ("Semi-annual", "position"), ("Position (15-45d)", "position"),
        ("Swing (5-15d)", "swing"), ("Custom (60-185d)", "swing"),
    ])
    def test_the_long_presets_collapse_to_position_not_to_swing(self, preset, expected):
        """`horizon_preset` reaches the backend carrying EITHER domain — the
        seven presets (what FirstPassageRequest takes) or the three scoring
        horizons (what the card resolves to before looking a threshold up). A
        bare "is it one of the three?" test sends Quarterly / SemiAnnual /
        Annual to Swing, so a 200-day hold would be graded at 0.70 here and at
        0.60 on the card beside it — two verdicts, one contract."""
        assert horizon_key(preset) == expected

    def test_a_long_preset_grades_at_the_position_line_end_to_end(self):
        """The mapping is only worth having if it reaches the threshold: K=205
        reads 0.67, which is PASS at Swing (0.70) and CAUTION at Position
        (0.60)."""
        assert _ref_cost(205, 8.49).status == "PASS"
        quarterly = compute_stop_cost(
            stop_price=REF_STOP, stock_price=REF_STOCK, strike=205, dte=REF_DTE,
            premium=8.49, is_call=True, horizon_preset="Quarterly",
        )
        assert quarterly.pass_max_fraction == 0.60
        assert quarterly.status == "CAUTION"

    def test_the_horizon_actually_changes_the_verdict(self):
        """A threshold that is echoed but never applied is the failure this
        guards: K=210 reads 0.70, which is CAUTION at Swing and PASS at the
        Intraday line of 0.80."""
        assert _ref_cost(210, 6.67).status == "CAUTION"
        intraday = compute_stop_cost(
            stop_price=REF_STOP, stock_price=REF_STOCK, strike=210, dte=REF_DTE,
            premium=6.67, is_call=True, horizon_preset="Intraday",
        )
        assert intraday.status == "PASS"
        assert intraday.pass_max_fraction == 0.80
        assert intraday.fraction == _ref_cost(210, 6.67).fraction

    def test_a_fraction_exactly_on_the_line_is_caution(self):
        """"At or above the threshold" — the line belongs to CAUTION, and the
        one printed number decides it, so the badge can never read a percentage
        that contradicts its own colour."""
        cost = _ref_cost(210, 6.67)
        assert cost.fraction == pytest.approx(0.70)
        assert cost.pass_max_fraction == 0.70
        assert cost.status == "CAUTION"


# ── Test 5 — "not computed" is a state, and it is never a PASS ────────────────

class TestNotComputed:
    def test_unsolvable_iv_returns_no_cost(self):
        """Spec test 5. A mid at or under intrinsic is arbitrage-violating and
        both solvers answer it with a confidently wrong sigma
        (2026-09-03-bs-iv-convergence-findings.md); the bracketed solver
        refuses instead, and a refusal must surface as "not computed"."""
        assert compute_stop_cost(
            stop_price=REF_STOP, stock_price=REF_STOCK, strike=150, dte=REF_DTE,
            premium=51.86, is_call=True, horizon_preset="Swing",
        ) is None

    def test_expiring_contract_returns_no_cost(self):
        """bs_price returns 0.0 for T <= 0, which would report EVERY expiring
        contract as a 100% loss at any stop — including one deep in the money
        at that stop and worth its intrinsic value. Refuse rather than print
        the most alarming possible number for the wrong reason."""
        for dte in (0,):
            assert _ref_cost(215, 5.21) is not None
            assert compute_stop_cost(
                stop_price=REF_STOP, stock_price=REF_STOCK, strike=215, dte=dte,
                premium=5.21, is_call=True, horizon_preset="Swing",
            ) is None

    def test_sub_cent_premium_returns_no_cost(self):
        """Every figure the card prints is rounded to cents, so a premium under
        a cent has no printable card — it would render a percentage beside
        "$0.00 of $0.00 premium". Tested on the RAW premium: (0.005).toFixed(2)
        rounds UP, so a guard on the rounded value never fires for the case it
        exists for. Mirrors frontend/lib/risk.ts's floor."""
        assert MIN_PREMIUM == 0.01
        assert compute_stop_cost(
            stop_price=REF_STOP, stock_price=REF_STOCK, strike=215, dte=REF_DTE,
            premium=0.005, is_call=True, horizon_preset="Swing",
        ) is None

    def test_non_finite_and_non_positive_inputs_return_no_cost(self):
        for kw in (
            {"stop_price": float("nan")}, {"stop_price": 0}, {"stop_price": float("inf")},
            {"stock_price": 0}, {"strike": 0}, {"premium": float("nan")},
        ):
            args = dict(
                stop_price=REF_STOP, stock_price=REF_STOCK, strike=215, dte=REF_DTE,
                premium=5.21, is_call=True, horizon_preset="Swing",
            )
            args.update(kw)
            assert compute_stop_cost(**args) is None, kw


# ── The supplied-IV path, and its units ───────────────────────────────────────

class TestSuppliedIv:
    def test_a_supplied_iv_is_percent_and_reproduces_the_solved_answer(self):
        """`iv` is ABSOLUTE volatility in PERCENT — the unit of
        ContractDetails.iv, which is what a caller actually holds. Feeding back
        the IV the solver itself found must land on the same numbers."""
        from app.data.market import _compute_iv_bs
        solved = _compute_iv_bs(
            mid=5.21, S=REF_STOCK, K=215, dte=REF_DTE, is_call=True, r=RISK_FREE_RATE,
        )
        assert solved is not None
        supplied = _ref_cost(215, 5.21, iv_pct=round(solved * 100, 2))
        derived = _ref_cost(215, 5.21)
        assert supplied.value_at_stop == pytest.approx(derived.value_at_stop, abs=0.01)
        assert supplied.status == derived.status

    def test_an_iv_that_disagrees_with_the_quote_cannot_report_a_negative_loss(self):
        """A supplied IV need not reproduce the contract's own mid, so BS at
        the stop can legitimately come back ABOVE the premium. The fraction is
        clamped to [0, 1]; the dollars are reported unclamped, because that
        disagreement is the one signal the IV and the quote do not describe the
        same contract."""
        cost = _ref_cost(215, 5.21, iv_pct=400.0)
        assert cost is not None
        assert cost.value_at_stop > 5.21
        assert cost.loss_dollar < 0
        assert cost.fraction == 0.0
        assert cost.status == "PASS"


# ── Tests 3 and 4 — the endpoints ─────────────────────────────────────────────

_REF_STRUCTURAL = StructuralStop(
    price=REF_STOP, source="swing_low", confidence=80,
    distance_pct=round((REF_STOCK - REF_STOP) / REF_STOCK * 100, 2),
)


def _structural_stop_post(body: dict):
    candles = json.loads((FIXTURES / "AAPL_candles.json").read_text())
    with patch("app.routers.contracts.fetch_candles_async", AsyncMock(return_value=candles)), \
         patch("app.routers.contracts.find_structural_stop", return_value=_REF_STRUCTURAL):
        return _client().post("/api/contracts/structural-stop", json=body)


class TestStructuralStopEndpoint:
    _CONTRACT = {"strike": 215, "dte": REF_DTE, "premium": 5.21}

    def test_full_contract_set_returns_a_stop_cost(self):
        """Spec test 3, first half — and the reference contract's own numbers,
        end to end: $5.21 premium − $1.49 at $185.87 = $3.72, 71%, CAUTION at
        the Swing line."""
        r = _structural_stop_post({
            "symbol": "AAPL", "direction": "Bullish", "stock_price": REF_STOCK,
            "horizon_preset": "Swing", **self._CONTRACT,
        })
        assert r.status_code == 200, r.text
        cost = r.json()["stopCost"]
        assert cost is not None
        assert cost["valueAtStop"] == pytest.approx(1.49, abs=0.01)
        assert cost["lossDollar"] == pytest.approx(3.72, abs=0.01)
        assert cost["fraction"] == pytest.approx(0.71, abs=0.005)
        assert cost["status"] == "CAUTION"
        assert cost["passMaxFraction"] == 0.70
        assert cost["basis"] == "bs_today"

    def test_no_contract_fields_returns_no_stop_cost(self):
        """Spec test 3, second half. This endpoint is NOT options-specific —
        the stocks-mode card calls it with no contract at all — so the block is
        omitted there rather than the request rejected."""
        r = _structural_stop_post({
            "symbol": "AAPL", "direction": "Bullish", "stock_price": REF_STOCK,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["available"] is True
        assert body["price"] == REF_STOP
        assert body["stopCost"] is None

    @pytest.mark.parametrize("drop", ["strike", "dte", "premium"])
    def test_partial_contract_set_is_a_422(self, drop):
        """Spec test 4. Silently omitting the gate because one field went
        missing is how a contract with NO verdict comes to read like an
        unremarkable one."""
        contract = {k: v for k, v in self._CONTRACT.items() if k != drop}
        r = _structural_stop_post({
            "symbol": "AAPL", "direction": "Bullish", "stock_price": REF_STOCK, **contract,
        })
        assert r.status_code == 422, r.text

    def test_iv_without_a_contract_is_a_422(self):
        """An IV with nothing to price is the same silent-skip failure wearing
        a different field."""
        r = _structural_stop_post({
            "symbol": "AAPL", "direction": "Bullish", "stock_price": REF_STOCK, "iv": 34.5,
        })
        assert r.status_code == 422, r.text

    def test_a_decimal_iv_is_rejected_rather_than_priced(self):
        """The units trap: 0.345 meaning 34.5% would otherwise price the
        contract at 0.345% vol, reporting essentially the whole premium as lost
        at any stop — a confident, plausible-looking, wrong CAUTION. Loud 422
        instead."""
        r = _structural_stop_post({
            "symbol": "AAPL", "direction": "Bullish", "stock_price": REF_STOCK,
            "iv": 0.345, **self._CONTRACT,
        })
        assert r.status_code == 422, r.text

    def test_no_structural_level_means_no_stop_cost(self):
        """There is nothing to price against. `available: false` already says
        so; the gate must not invent a level to grade."""
        candles = json.loads((FIXTURES / "AAPL_candles.json").read_text())
        with patch("app.routers.contracts.fetch_candles_async", AsyncMock(return_value=candles)), \
             patch("app.routers.contracts.find_structural_stop", return_value=None):
            r = _client().post("/api/contracts/structural-stop", json={
                "symbol": "AAPL", "direction": "Bullish", "stock_price": REF_STOCK,
                **self._CONTRACT,
            })
        assert r.status_code == 200, r.text
        assert r.json()["available"] is False
        assert r.json()["stopCost"] is None

    def test_unsolvable_iv_renders_not_computed_not_a_pass(self):
        """Spec test 5 at the endpoint. The request is well-formed and the stop
        exists — only the arithmetic refuses, and `null` is how that must
        arrive. A missing block is "not computed"; it is never a PASS."""
        r = _structural_stop_post({
            "symbol": "AAPL", "direction": "Bullish", "stock_price": REF_STOCK,
            "strike": 150, "dte": REF_DTE, "premium": 51.86,
        })
        assert r.status_code == 200, r.text
        assert r.json()["stopCost"] is None

    def test_bearish_prices_a_put_against_a_stop_above_the_price(self):
        """Direction picks the right, and a Bearish stop sits ABOVE spot. The
        put must lose value as the stock rises into it — a call priced here by
        mistake would gain, and the gate would report a wildly optimistic
        loss."""
        stop_above = StructuralStop(price=215.0, source="swing_high", confidence=70, distance_pct=6.5)
        candles = json.loads((FIXTURES / "AAPL_candles.json").read_text())
        with patch("app.routers.contracts.fetch_candles_async", AsyncMock(return_value=candles)), \
             patch("app.routers.contracts.find_structural_stop", return_value=stop_above):
            r = _client().post("/api/contracts/structural-stop", json={
                "symbol": "AAPL", "direction": "Bearish", "stock_price": REF_STOCK,
                "strike": 195, "dte": REF_DTE, "premium": 5.10, "horizon_preset": "Swing",
            })
        assert r.status_code == 200, r.text
        cost = r.json()["stopCost"]
        assert cost is not None
        assert 0 < cost["valueAtStop"] < 5.10
        assert cost["lossDollar"] > 0


class TestExitPlanEndpoint:
    def _post(self, **overrides):
        candles = json.loads((FIXTURES / "AAPL_candles.json").read_text())
        entry_price = candles[-1]["close"]
        body = {
            "symbol": "AAPL", "direction": "Bullish", "entry_price": entry_price,
            "strike": round(entry_price * 1.05), "dte": 45, "premium": 5.20,
            "trend_score": 65, "horizon_preset": "Swing",
        }
        body.update(overrides)
        with patch("app.routers.contracts.fetch_candles_async", AsyncMock(return_value=candles)):
            return _client().post("/api/contracts/exit-plan", json=body), entry_price

    def test_stop_carries_a_stop_cost(self):
        """Spec test 3 for §2.2. The contract is already mandatory on this
        endpoint, so the block is always attempted."""
        r, _ = self._post()
        assert r.status_code == 200, r.text
        cost = r.json()["stop"]["stopCost"]
        assert cost is not None
        assert cost["basis"] == "bs_today"
        assert cost["passMaxFraction"] == 0.70
        assert cost["status"] in ("PASS", "CAUTION")
        assert 0.0 <= cost["fraction"] <= 1.0

    def test_the_cost_is_priced_against_the_stop_that_is_printed(self):
        """The badge reads "$5.20 premium − $X at <stop>". If the priced level
        and the PRINTED level were not the same number — the response rounds
        the stop to cents — that line would not add up. So this recomputes
        against the printed stop and demands the same answer, rather than only
        checking that a block came back."""
        r, entry_price = self._post()
        body = r.json()
        cost = body["stop"]["stopCost"]
        expected = compute_stop_cost(
            stop_price=body["stop"]["price"], stock_price=entry_price,
            strike=round(entry_price * 1.05), dte=45, premium=5.20,
            is_call=True, horizon_preset="Swing",
        )
        assert expected is not None
        assert cost["valueAtStop"] == pytest.approx(expected.value_at_stop, abs=1e-9)
        assert cost["lossDollar"] == pytest.approx(expected.loss_dollar, abs=1e-9)
        assert cost["lossDollar"] == pytest.approx(5.20 - cost["valueAtStop"], abs=0.005)


    def test_exit_plan_and_structural_stop_may_legitimately_disagree(self):
        """Spec test 8. The exit-plan stop is the WIDER of the structural level
        and an ATR floor, so it costs at least as much of the premium as the
        raw structural level does. A different verdict between the two
        endpoints is the model working, not a bug — asserted here so nobody
        "fixes" it later."""
        candles = json.loads((FIXTURES / "AAPL_candles.json").read_text())
        entry_price = candles[-1]["close"]
        contract = {"strike": round(entry_price * 1.05), "dte": 45, "premium": 5.20}

        with patch("app.routers.contracts.fetch_candles_async", AsyncMock(return_value=candles)):
            ep = _client().post("/api/contracts/exit-plan", json={
                "symbol": "AAPL", "direction": "Bullish", "entry_price": entry_price,
                "trend_score": 65, "horizon_preset": "Swing", **contract,
            })
            ss = _client().post("/api/contracts/structural-stop", json={
                "symbol": "AAPL", "direction": "Bullish", "stock_price": entry_price,
                "horizon_preset": "Swing", **contract,
            })
        assert ep.status_code == 200, ep.text
        assert ss.status_code == 200, ss.text

        ep_stop = ep.json()["stop"]
        ep_cost = ep_stop["stopCost"]
        assert ep_cost is not None

        if not ss.json()["available"] or ss.json()["stopCost"] is None:
            pytest.skip("fixture yields no structural level to compare against")

        ss_stop, ss_cost = ss.json()["price"], ss.json()["stopCost"]
        # Bullish: the exit-plan stop is at or below the structural one (wider),
        # so it must cost at least as much of the premium.
        assert ep_stop["price"] <= ss_stop + 1e-9
        assert ep_cost["fraction"] >= ss_cost["fraction"] - 1e-9


# ── B2 — the block carries every figure the card prints, and they add up ──────

class TestPrintedFiguresReconcile:
    """The frontend presenter takes this block AND NOTHING ELSE (spec §3:
    `stopPremiumRisk(c: StopCostOut | null)`), so the premium the gate priced
    and the stop it priced to travel with the verdict. Without them the card
    composes its equation from `contractDetails.mid` and whatever stop is in
    state at render time — which are not necessarily the two numbers this block
    was computed from.

    And the three figures have to subtract EXACTLY as printed. The card's whole
    premise is arithmetic a non-coder can check by hand, so a line reading
    "$5.21 premium − $0.79 at $185.87 = $4.41" must not be off by the cent that
    rounding `premium - value_at_stop` from a RAW premium introduces.
    """

    def _cost(self, premium: float, **over):
        kwargs = dict(
            stop_price=185.87, stock_price=201.86, strike=205, dte=45,
            premium=premium, is_call=True, horizon_preset="Swing",
        )
        kwargs.update(over)
        return compute_stop_cost(**kwargs)

    def test_the_block_echoes_the_premium_and_the_stop_it_priced(self):
        cost = self._cost(5.20)
        assert cost is not None
        assert cost.premium == 5.20
        assert cost.stop_price == 185.87

    def test_a_half_cent_mid_still_prints_a_line_that_subtracts(self):
        # A mid is (bid + ask) / 2, so a half-cent premium is an ORDINARY quote,
        # not a contrived one. Rounding the subtraction from the raw premium
        # instead put the printed premium and the printed loss a cent apart.
        #
        # $0.015 is the smallest premium on this contract where the two
        # arithmetics actually differ, and it is named rather than swept
        # because a case that passes under BOTH versions pins nothing: the
        # pre-fix code printed "$0.01 premium − $0.00 = $0.02", a line whose
        # own two terms contradict its result.
        cost = self._cost(0.015)
        assert cost is not None
        assert cost.premium == 0.01
        assert cost.value_at_stop == 0.0
        assert cost.loss_dollar == 0.01
        assert round(cost.premium - cost.value_at_stop, 2) == cost.loss_dollar

        # And the same property on an ordinary-sized quote.
        rich = self._cost(5.205)
        assert rich is not None
        assert rich.premium == 5.21
        assert round(rich.premium - rich.value_at_stop, 2) == rich.loss_dollar

    def test_the_equation_subtracts_across_a_sweep_of_ordinary_premiums(self):
        checked = 0
        for hundredths in range(1, 2000):
            for half in (0.0, 0.005):
                premium = hundredths / 100 + half
                cost = self._cost(premium)
                if cost is None:
                    continue
                checked += 1
                assert round(cost.premium - cost.value_at_stop, 2) == cost.loss_dollar, premium
                # And the fraction is that same printed pair, so the verdict and
                # the percentage beside it cannot be read off two quantities.
                assert cost.fraction == round(
                    min(max(cost.loss_dollar / cost.premium, 0.0), 1.0), 2
                ), premium
        assert checked > 3000

    def test_the_premium_floor_is_still_tested_on_the_RAW_value(self):
        # $0.0099 must be refused, not rounded up to a printable $0.01. Guarding
        # after the quantization would have re-opened exactly the sub-cent card
        # the floor exists to prevent.
        assert self._cost(0.0099) is None
        assert self._cost(0.005) is None
        assert self._cost(0.01) is not None
