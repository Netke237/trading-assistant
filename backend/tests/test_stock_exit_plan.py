"""POST /api/stocks/exit-plan — piece 6, the stocks arithmetic plan.

The options exit-plan pipeline with the premium half removed. What these tests
are actually defending, beyond "it returns numbers":

  * that the stock path IS the options path minus the premium half, by calling
    the same two functions with the same arguments rather than reimplementing
    them (TestSharedPipeline);
  * that both collapse guards came over intact (TestGuards) — without them the
    ATR floor lands on the entry price and every target lands there with it,
    which reads as a computed plan and is not one;
  * that no options field can leak back into the response later (TestNoOptionsFields);
  * that the printed arithmetic reconciles, because a card whose whole point is
    "risk $15.69, so 2R is $242.97" is worthless if the user checks it and it is
    off by a penny (TestPrintedChainReconciles).
"""
from __future__ import annotations

import json
import math
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.scoring.exit_plan import compute_final_stop, compute_target_row
from app.scoring.structural_stop import StructuralStop

FIXTURES = Path(__file__).parent / "fixtures"


def _aapl() -> list[dict]:
    return json.loads((FIXTURES / "AAPL_candles.json").read_text())


def _flat(price: float = 100.0, n: int = 60) -> list[dict]:
    """A stale/repeated feed: every bar identical, so every true range is 0 and
    _atr returns 0.0. Clears the len<2 guard and still collapses the plan."""
    return [{"time": str(i), "open": price, "high": price, "low": price,
             "close": price, "volume": 1_000_000} for i in range(n)]


def _client() -> TestClient:
    from app.routers.stock_scan import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _post(candles: list[dict] | None = None, **overrides):
    payload = {
        "symbol": "AAPL", "direction": "Bullish", "entry_price": 211.59,
        "trend_score": 70.0, "horizon": "Swing",
    }
    payload.update(overrides)
    bars = _aapl() if candles is None else candles
    with patch("app.routers.stock_scan.fetch_candles_async", AsyncMock(return_value=bars)):
        return _client().post("/api/stocks/exit-plan", json=payload)


# ── Spec test 1 — the stock path is the options path minus the premium half ───

class TestSharedPipeline:
    """compute_final_stop and compute_target_row take candles, a direction, a
    price and config — no contract input, and never had one. The guarantee this
    class pins is that /stocks/exit-plan REUSES them rather than growing its own
    copy that drifts."""

    def _record(self, module: str, symbol_kwargs: dict, path: str):
        calls = {"stop": [], "target": []}

        def rec_stop(*a, **k):
            res = compute_final_stop(*a, **k)
            calls["stop"].append((a, k, res))
            return res

        def rec_target(*a, **k):
            res = compute_target_row(*a, **k)
            calls["target"].append((a, k, res))
            return res

        candles = _aapl()
        with patch(f"{module}.fetch_candles_async", AsyncMock(return_value=candles)), \
             patch(f"{module}.compute_final_stop", side_effect=rec_stop), \
             patch(f"{module}.compute_target_row", side_effect=rec_target):
            from app.routers.contracts import router as contracts_router
            from app.routers.stock_scan import router as stock_router
            app = FastAPI()
            app.include_router(contracts_router if "contracts" in module else stock_router)
            r = TestClient(app).post(path, json=symbol_kwargs)
        assert r.status_code == 200, r.text
        return calls

    def test_both_endpoints_call_compute_final_stop_identically(self):
        entry = _aapl()[-1]["close"]
        opt = self._record(
            "app.routers.contracts",
            {"symbol": "AAPL", "direction": "Bullish", "entry_price": entry,
             "strike": round(entry * 1.05), "dte": 30, "premium": 2.50, "trend_score": 65},
            "/api/contracts/exit-plan",
        )
        stk = self._record(
            "app.routers.stock_scan",
            {"symbol": "AAPL", "direction": "Bullish", "entry_price": entry,
             "trend_score": 65, "horizon": "Swing"},
            "/api/stocks/exit-plan",
        )
        assert len(opt["stop"]) == len(stk["stop"]) == 1
        (a_opt, k_opt, r_opt) = opt["stop"][0]
        (a_stk, k_stk, r_stk) = stk["stop"][0]
        assert a_opt == a_stk and k_opt == k_stk
        assert r_opt == r_stk

    def test_compute_target_row_differs_only_by_the_cent_quantized_stop(self):
        """The ONE deliberate difference, pinned so it cannot silently grow.

        The stock card's entire value is arithmetic the user checks in his head,
        so the stop is quantized to cents BEFORE the targets are built off it —
        otherwise 'stop 195.90, risk 15.69, 2R = 242.97' fails by a penny on
        essentially every atr_widened row, ATR being a mean of true ranges. The
        options card prints contract prices and needs no such guarantee, so it
        passes the raw stop through. Everything else about the call is identical.
        """
        entry = _aapl()[-1]["close"]
        opt = self._record(
            "app.routers.contracts",
            {"symbol": "AAPL", "direction": "Bullish", "entry_price": entry,
             "strike": round(entry * 1.05), "dte": 30, "premium": 2.50, "trend_score": 65},
            "/api/contracts/exit-plan",
        )
        stk = self._record(
            "app.routers.stock_scan",
            {"symbol": "AAPL", "direction": "Bullish", "entry_price": entry,
             "trend_score": 65, "horizon": "Swing"},
            "/api/stocks/exit-plan",
        )
        assert len(opt["target"]) == len(stk["target"]) == 2
        for (a_opt, _, _), (a_stk, _, _) in zip(opt["target"], stk["target"]):
            candles_o, dir_o, entry_o, stop_o, atr_o, rr_o, snap_o = a_opt
            candles_s, dir_s, entry_s, stop_s, atr_s, rr_s, snap_s = a_stk
            assert (candles_o, dir_o, entry_o, atr_o, rr_o, snap_o) == \
                   (candles_s, dir_s, entry_s, atr_s, rr_s, snap_s)
            assert stop_s.price == round(stop_o.price, 2)
            assert stop_s.source == stop_o.source
            assert stop_s.structural == stop_o.structural
            assert stop_s.atr_floor_price == stop_o.atr_floor_price


# ── Spec test 2 — both 422 guards carried over ────────────────────────────────

class TestGuards:
    _MSG = "insufficient price history to compute an exit plan"

    def test_fewer_than_two_candles_is_422(self):
        r = _post(candles=[{"time": "0", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}])
        assert r.status_code == 422
        assert r.json()["detail"] == self._MSG

    def test_no_candles_at_all_is_422(self):
        r = _post(candles=[])
        assert r.status_code == 422
        assert r.json()["detail"] == self._MSG

    def test_a_flat_feed_with_zero_atr_is_422(self):
        """Passes the len<2 guard and still collapses the ATR floor onto the
        entry price — the same failure reached a different way, and the reason
        this is a SECOND guard rather than a stricter first one."""
        r = _post(candles=_flat(), entry_price=100.0)
        assert r.status_code == 422
        assert r.json()["detail"] == self._MSG

    def test_a_stop_that_rounds_onto_the_entry_price_is_422(self):
        """The third route to a collapsed plan: an ATR small enough that
        2 x ATR rounds away entirely at this price. Every target would land on
        entry and every R:R would be infinite."""
        # ATR ~ 0.001 on a $100 name -> floor distance 0.002 -> stop rounds to 100.00.
        bars = [{"time": str(i), "open": 100.0, "high": 100.001, "low": 100.0,
                 "close": 100.0, "volume": 1_000_000} for i in range(60)]
        r = _post(candles=bars, entry_price=100.0)
        assert r.status_code == 422
        assert r.json()["detail"] == self._MSG

    def test_rejects_nonpositive_entry_price(self):
        assert _post(entry_price=0).status_code == 422

    def test_rejects_out_of_range_trend_score(self):
        assert _post(trend_score=150).status_code == 422

    @pytest.mark.parametrize("ratios", [[0.0], [-1.0], [2.0, 0.0]])
    def test_rejects_non_positive_rr_ratios(self, ratios):
        """An R:R of 0 puts the target ON the entry price; a negative one puts it
        on the losing side. Either would render as a 'profit target' that is
        nothing of the kind."""
        assert _post(rr_ratios=ratios).status_code == 422

    def test_rejects_an_empty_rr_ratios_list(self):
        assert _post(rr_ratios=[]).status_code == 422


# ── Spec test 3 — rr_ratios ───────────────────────────────────────────────────

class TestRrRatios:
    def test_omitted_falls_back_to_the_config_default(self):
        from app.services.config_loader import load_exit_plan_cfg
        body = _post().json()
        assert [t["rrRatio"] for t in body["targets"]] == \
            [float(r) for r in load_exit_plan_cfg()["target"]["rr_ratios"]]

    def test_an_override_is_respected(self):
        body = _post(rr_ratios=[1.0, 1.5, 4.0]).json()
        assert [t["rrRatio"] for t in body["targets"]] == [1.0, 1.5, 4.0]

    def test_a_larger_ratio_is_never_a_nearer_target(self):
        body = _post(rr_ratios=[1.0, 2.0, 5.0]).json()
        prices = [t["price"] for t in body["targets"]]
        assert prices == sorted(prices)


# ── Spec tests 4 and 5 — the structural snap band ─────────────────────────────

class TestStructuralSnap:
    def _with_structural_target_at(self, price: float):
        return patch(
            "app.scoring.exit_plan.find_structural_target",
            return_value=StructuralStop(
                price=price, source="swing_high", confidence=70, distance_pct=1.0,
            ),
        )

    def test_a_level_inside_the_band_snaps(self):
        # Stop resolves to 195.90 -> risk 15.69 -> 2R arithmetic 242.97, and the
        # band is 0.3 x ATR(7.84) = 2.35. A level 1.00 away is inside it.
        with self._with_structural_target_at(243.97):
            body = _post(rr_ratios=[2.0]).json()
        row = body["targets"][0]
        assert row["tpSource"] == "structural_snap"
        assert row["price"] == 243.97
        assert row["arithmeticPrice"] == 242.97
        assert row["distanceDollar"] <= row["toleranceDollar"]

    def test_a_level_outside_the_band_does_not_snap(self):
        with self._with_structural_target_at(255.0):
            body = _post(rr_ratios=[2.0]).json()
        row = body["targets"][0]
        assert row["tpSource"] == "arithmetic"
        assert row["price"] == row["arithmeticPrice"] == 242.97
        assert row["distanceDollar"] > row["toleranceDollar"]

    def test_no_structural_level_ahead_leaves_the_arithmetic_price_and_no_distance(self):
        with patch("app.scoring.exit_plan.find_structural_target", return_value=None):
            body = _post(rr_ratios=[2.0]).json()
        row = body["targets"][0]
        assert row["tpSource"] == "arithmetic"
        assert row["structuralPrice"] is None
        assert row["distanceDollar"] is None
        # The band is ALWAYS computable — it is 0.3 x ATR, independent of whether
        # any level was found to compare against.
        assert row["toleranceDollar"] > 0


# ── Spec test 6 — sizing off the risk budget ──────────────────────────────────

class TestRecommendedShares:
    def test_is_the_risk_budget_divided_by_the_risk_per_share(self):
        body = _post().json()
        assert body["recommendedShares"] == \
            math.floor(body["riskBudget"] / body["stop"]["riskPerShare"])

    def test_risk_budget_is_portfolio_value_times_max_loss_per_trade_pct(self):
        """Surfaced so the division is checkable on the card, and read from the
        SAME risk_rules.yaml keys the Settings > Risk form writes."""
        from app.services import portfolio_risk
        cfg = portfolio_risk._load_config()["portfolio"]
        expected = round(
            float(cfg["portfolio_value"]) * float(cfg["max_loss_per_trade_pct"]), 2,
        )
        assert _post().json()["riskBudget"] == expected

    def test_a_zero_risk_budget_yields_none_not_an_unbounded_size(self):
        from app.services import portfolio_risk
        with patch.object(
            portfolio_risk, "_load_config",
            return_value={"portfolio": {"portfolio_value": 0.0, "max_loss_per_trade_pct": 0.0375}},
        ):
            body = _post().json()
        assert body["riskBudget"] == 0.0
        assert body["recommendedShares"] is None

    def test_a_missing_portfolio_block_yields_none_rather_than_a_crash(self):
        from app.services import portfolio_risk
        with patch.object(portfolio_risk, "_load_config", return_value={}):
            body = _post().json()
        assert body["recommendedShares"] is None

    @pytest.mark.parametrize("portfolio_value,pct,band,expected", [
        # Each row is a pair where FLOAT floor-division lands a share short,
        # because neither cent-quantized operand is exactly representable in
        # binary: int(2000.0 // 1.6) is 1249, not 1250. Round 1 of the
        # adversarial audit found this; the general assertion below would have
        # caught it and simply never saw an exact quotient.
        #
        # `band` is half the ATR: on a flat-close series the true range is
        # high - low = 2 x band, so ATR(14) == 2 x band and the 2x ATR floor
        # sits 4 x band from entry.
        (50000.0,  0.04, 0.40, 1250),   # budget 2000.00 / risk 1.60
        (100000.0, 0.02, 0.20, 2500),   # budget 2000.00 / risk 0.80
        (100000.0, 0.03, 0.20, 3750),   # budget 3000.00 / risk 0.80
    ])
    def test_an_exact_quotient_is_not_a_share_short(
        self, portfolio_value, pct, band, expected,
    ):
        from app.services import portfolio_risk
        bars = [{"time": str(i), "open": 100.0, "high": 100.0 + band,
                 "low": 100.0 - band, "close": 100.0, "volume": 1_000_000}
                for i in range(60)]
        with patch.object(
            portfolio_risk, "_load_config",
            return_value={"portfolio": {"portfolio_value": portfolio_value,
                                        "max_loss_per_trade_pct": pct}},
        ):
            body = _post(candles=bars, entry_price=100.0).json()
        # The quotient is exact by construction — that is the whole point of
        # these three rows, so pin it rather than trusting the fixture. In
        # Decimal, because `2000.0 % 1.6` is 1.59999999999995 in float: the
        # very error this test exists to defend against would otherwise sit
        # inside the assertion meant to prove the fixture is clean.
        assert Decimal(str(body["riskBudget"])) % Decimal(str(body["stop"]["riskPerShare"])) == 0
        assert body["recommendedShares"] == expected

    def test_a_budget_too_small_for_one_share_is_none_not_zero(self):
        """Zero is not a size — it is "the risk budget cannot buy one share at
        this stop". Returning 0 let the card print a SHARES readout of 0 and
        offer an "Apply 0 shares" button that wrote a 0-share position into the
        portfolio, past the SHARES field's own clamp. Reachable on a small
        account: a $2,000 portfolio at 0.1% per trade is a $2.00 budget."""
        from app.services import portfolio_risk
        with patch.object(
            portfolio_risk, "_load_config",
            return_value={"portfolio": {"portfolio_value": 2000.0,
                                        "max_loss_per_trade_pct": 0.001}},
        ):
            body = _post().json()
        assert body["riskBudget"] == 2.0
        assert body["stop"]["riskPerShare"] > 2.0
        assert body["recommendedShares"] is None

    def test_the_share_count_never_rounds_up(self):
        """floor, not round: rounding up would size past the risk budget, which
        is the one thing this number exists to bound."""
        body = _post().json()
        shares, rps, budget = (
            body["recommendedShares"], body["stop"]["riskPerShare"], body["riskBudget"],
        )
        assert shares * rps <= budget
        assert (shares + 1) * rps > budget


# ── Spec test 7 — Bearish mirrors Bullish ─────────────────────────────────────

class TestBearishMirrorsBullish:
    def test_stop_above_entry_and_targets_below(self):
        entry = 211.59
        body = _post(direction="Bearish", entry_price=entry).json()
        assert body["stop"]["price"] > entry
        assert body["stop"]["riskPerShare"] == round(body["stop"]["price"] - entry, 2)
        for t in body["targets"]:
            assert t["price"] < entry
            assert t["rewardPerShare"] == round(entry - t["price"], 2)
        prices = [t["price"] for t in body["targets"]]
        assert prices == sorted(prices, reverse=True)

    def test_the_race_stop_barrier_is_the_bearish_stop(self):
        body = _post(direction="Bearish").json()
        assert body["race"]["stopPrice"] == body["stop"]["price"]


# ── Spec test 8 — the day-count basis is disclosed, not unified ───────────────

class TestDaysBasis:
    def test_days_basis_is_trading(self):
        """Spec 3.2. This engine counts TRADING days (its window is a bar count,
        its sigma annualizes with sqrt(252)); the options card counts CALENDAR
        days (its window is DTE). Both are internally right; the payload says
        which, so the card can print the word instead of a bare 'd'."""
        assert _post().json()["daysBasis"] == "trading"

    def test_horizon_days_comes_from_scoring_rules(self):
        from app.scoring.signal_confidence import load_backtest_cfg
        for horizon in ("Intraday", "Swing", "Position"):
            assert _post(horizon=horizon).json()["horizonDays"] == \
                int(load_backtest_cfg(horizon)["n_days"])

    def test_expected_days_never_exceeds_the_window(self):
        body = _post().json()
        window = body["horizonDays"]
        for value in [body["stop"]["expectedDays"]] + [t["expectedDays"] for t in body["targets"]]:
            if value is not None:
                assert 1 <= value <= window


# ── Spec test 9 — no options field can leak back in ───────────────────────────

_FORBIDDEN_WORDS = {
    "premium", "strike", "dte", "iv", "delta", "greeks", "theta", "gamma",
    "vega", "contract", "contracts", "stopcost", "rrmodel", "option",
}


def _camel_words(name: str) -> list[str]:
    out, cur = [], ""
    for ch in name:
        if ch.isupper() and cur:
            out.append(cur.lower())
            cur = ch
        else:
            cur += ch
    if cur:
        out.append(cur.lower())
    return out


def _all_keys(node) -> set[str]:
    keys: set[str] = set()
    if isinstance(node, dict):
        for k, v in node.items():
            keys.add(k)
            keys |= _all_keys(v)
    elif isinstance(node, list):
        for item in node:
            keys |= _all_keys(item)
    return keys


class TestNoOptionsFields:
    """The anti-regression the spec asks for by name. Asserted on the KEY SET,
    not on a hand-listed shape, so an options field added to this response later
    fails here rather than quietly shipping a stocks card that talks about
    premium."""

    def test_no_option_field_appears_anywhere_in_the_response(self):
        body = _post().json()
        offenders = {
            k for k in _all_keys(body)
            if _FORBIDDEN_WORDS & set(_camel_words(k))
        }
        assert offenders == set(), f"options fields leaked into the stocks plan: {offenders}"

    def test_the_same_holds_on_the_generated_schema_not_just_one_payload(self):
        """A payload only proves the fields it happened to populate. The schema
        covers every optional one too."""
        from app.routers.stock_scan import StockExitPlanResponse
        schema = StockExitPlanResponse.model_json_schema()
        names: set[str] = set()
        for model in schema.get("$defs", {}).values():
            names |= set(model.get("properties", {}))
        names |= set(schema.get("properties", {}))
        offenders = {n for n in names if _FORBIDDEN_WORDS & set(_camel_words(n))}
        assert offenders == set(), f"options fields in the schema: {offenders}"

    def test_there_is_no_stop_cost_gate(self):
        """Spec section 1: Q-A is closed. A stock's stop cost is exact —
        riskPerShare, times however many shares — so a badge that looked like the
        options gate but answered a different question is forbidden, not merely
        unbuilt."""
        stop = _post().json()["stop"]
        assert "stopCost" not in stop
        assert stop["riskPerShare"] > 0


# ── Spec test 10 — the response shape the frontend type mirrors ───────────────

class TestResponseShape:
    def test_top_level_keys_are_exactly_these(self):
        assert set(_post().json()) == {
            "stop", "targets", "atr", "recommendedShares", "riskBudget",
            "daysBasis", "horizonDays", "modelCaveat", "race",
        }

    def test_stop_keys_are_exactly_these(self):
        assert set(_post().json()["stop"]) == {
            "price", "source", "structuralSource", "structuralConfidence",
            "structuralPrice", "atrFloorPrice", "distanceDollar", "riskPerShare",
            "probability", "expectedDays",
        }

    def test_target_row_keys_are_exactly_these(self):
        assert set(_post().json()["targets"][0]) == {
            "rrRatio", "arithmeticPrice", "price", "tpSource", "structuralPrice",
            "distanceDollar", "toleranceDollar", "rewardPerShare", "probability",
            "expectedDays", "qualityGood", "qualityReasons",
        }

    def test_race_keys_are_exactly_these(self):
        body = _post().json()
        assert set(body["race"]) == {"outcomes", "stopPrice", "nPaths"}
        assert set(body["race"]["outcomes"][0]) == {
            "targetPrice", "pTargetFirst", "pStopFirst", "pNeither",
            "daysTarget", "daysStop", "weightTarget", "weightStop",
            "weightNeither", "terminalMean",
        }

    def test_optional_fields_are_null_rather_than_absent(self):
        """Every Optional in the response model has an explicit default, so the
        key is always present. A TS type declaring `x: number | null` breaks on
        an absent key in a way `x?: number` does not — pinning this keeps the
        two in step."""
        with patch("app.scoring.exit_plan.find_structural_stop", return_value=None), \
             patch("app.scoring.exit_plan.find_structural_target", return_value=None):
            body = _post().json()
        assert body["stop"]["structuralPrice"] is None
        assert body["stop"]["structuralSource"] is None
        assert body["stop"]["structuralConfidence"] is None
        assert body["stop"]["distanceDollar"] is None
        assert body["targets"][0]["structuralPrice"] is None
        assert body["targets"][0]["distanceDollar"] is None
        assert body["modelCaveat"] is None


# ── The printed arithmetic ────────────────────────────────────────────────────

class TestPrintedChainReconciles:
    """Kenneth checks this card's arithmetic in his head. Every identity below is
    one he can verify on screen, so each is pinned rather than left to rounding
    luck."""

    @pytest.mark.parametrize("direction", ["Bullish", "Bearish"])
    def test_risk_per_share_is_exactly_entry_minus_stop(self, direction):
        entry = 211.59
        body = _post(direction=direction, entry_price=entry).json()
        assert body["stop"]["riskPerShare"] == round(abs(entry - body["stop"]["price"]), 2)

    @pytest.mark.parametrize("direction", ["Bullish", "Bearish"])
    def test_the_arithmetic_target_is_exactly_entry_plus_rr_times_risk(self, direction):
        entry = 211.59
        body = _post(direction=direction, entry_price=entry, rr_ratios=[1.0, 2.0, 3.0]).json()
        rps = body["stop"]["riskPerShare"]
        sign = 1 if direction == "Bullish" else -1
        for row in body["targets"]:
            assert row["arithmeticPrice"] == round(entry + sign * row["rrRatio"] * rps, 2)

    def test_reward_per_share_matches_the_price_actually_used_not_the_arithmetic_one(self):
        """On a snapped row the reward must be measured to where the target
        actually sits, or the R:R printed beside it describes a different trade."""
        with patch(
            "app.scoring.exit_plan.find_structural_target",
            return_value=StructuralStop(price=243.97, source="swing_high",
                                        confidence=70, distance_pct=1.0),
        ):
            body = _post(rr_ratios=[2.0], entry_price=211.59).json()
        row = body["targets"][0]
        assert row["tpSource"] == "structural_snap"
        assert row["rewardPerShare"] == round(row["price"] - 211.59, 2)
        assert row["rewardPerShare"] != round(row["arithmeticPrice"] - 211.59, 2)


# ── The two-barrier race (spec section 5) ─────────────────────────────────────

class TestBarrierRace:
    def test_one_outcome_per_target_in_the_same_order(self):
        body = _post(rr_ratios=[1.0, 2.0, 3.0]).json()
        assert [o["targetPrice"] for o in body["race"]["outcomes"]] == \
               [t["price"] for t in body["targets"]]

    def test_the_three_probabilities_sum_to_one(self):
        """The whole point: an ATTRIBUTION, not three independent estimates.
        Every path lands in exactly one bucket."""
        for o in _post().json()["race"]["outcomes"]:
            total = o["pTargetFirst"] + o["pStopFirst"] + o["pNeither"]
            assert total == pytest.approx(1.0, abs=1e-6)

    def test_the_printed_weights_sum_to_exactly_one(self):
        """The card prints THESE, not the raw probabilities, so a row can never
        render as 18% / 40% / 42% adding to 99%. Same largest-remainder
        allocator as the option race — one rounding rule, one implementation."""
        for o in _post().json()["race"]["outcomes"]:
            total = round(o["weightTarget"] + o["weightStop"] + o["weightNeither"], 10)
            assert total == 1.0
            for w in (o["weightTarget"], o["weightStop"], o["weightNeither"]):
                assert round(w * 100) == pytest.approx(w * 100, abs=1e-9)

    def test_the_race_disagrees_with_the_independent_probabilities_and_that_is_the_point(self):
        """stop.probability and targets[].probability are each measured alone and
        routinely sum past 100% — a path can touch both barriers. The race is the
        only place the numbers are forced to be exclusive, so p_stop_first must
        be no larger than the independent stop probability."""
        body = _post().json()
        for row, outcome in zip(body["targets"], body["race"]["outcomes"]):
            assert outcome["pStopFirst"] <= body["stop"]["probability"] + 1e-9
            assert outcome["pTargetFirst"] <= row["probability"] + 1e-9

    def test_a_farther_target_wins_less_often_and_loses_the_race_more_often(self):
        body = _post(rr_ratios=[1.0, 3.0]).json()
        near, far = body["race"]["outcomes"]
        assert far["pTargetFirst"] <= near["pTargetFirst"]
        assert far["pStopFirst"] >= near["pStopFirst"]

    def test_the_stop_barrier_is_the_stop_the_plan_actually_reports(self):
        """An echo, for auditability: if these ever diverge, the race is
        measuring a level the card is not showing."""
        body = _post().json()
        assert body["race"]["stopPrice"] == body["stop"]["price"]

    def test_conditional_medians_stay_inside_the_window(self):
        body = _post().json()
        window = body["horizonDays"]
        for o in body["race"]["outcomes"]:
            for d in (o["daysTarget"], o["daysStop"]):
                if d is not None:
                    assert 1 <= d <= window

    def test_the_neither_bucket_carries_a_terminal_price(self):
        """A stock that reached no barrier is still an open position at a
        knowable average price — not a write-off the way an expired option is.
        That is why this bucket has a number here and the option race's does
        not."""
        for o in _post().json()["race"]["outcomes"]:
            if o["pNeither"] > 0:
                assert o["terminalMean"] is not None
                assert o["terminalMean"] > 0

    def test_ties_resolve_to_the_stop_not_the_target(self):
        """Daily closes mean both barriers can be crossed on the same simulated
        day. The tie goes PESSIMISTICALLY to the stop — same rule, same reason,
        as the option race's `_attribute`: it never flatters the trade.

        The levels below are deliberately absurd (a $0.01 target, a $1,000,000
        stop) because a TIE is what is under test, not a plausible plan: both
        are crossed by every path on day 1, so every path is a tie and the rule
        decides all 2000 of them.
        """
        from app.scoring.first_passage import estimate_stock_first_passage
        res = estimate_stock_first_passage(
            stock_price=100.0, direction="Bullish", trend_score=50.0,
            stop_price=1_000_000.0, targets=[0.01], candles=_aapl(),
            horizon_days=10, seed=3, compute_race=True,
        )
        outcome = res.race.outcomes[0]
        assert outcome.days_target is None      # the target won nothing
        assert outcome.days_stop == 1.0
        assert outcome.p_stop_first == 1.0
        assert outcome.p_target_first == 0.0
        assert outcome.p_neither == 0.0

    def test_the_tie_rule_is_a_tiebreak_not_a_blanket_win_for_the_stop(self):
        """The control for the test above: with the tie removed — the target
        reachable on day 1 and the stop out of reach — the target takes every
        path. Without this, the assertion above would also pass on an
        implementation that simply always credited the stop."""
        from app.scoring.first_passage import estimate_stock_first_passage
        res = estimate_stock_first_passage(
            stock_price=100.0, direction="Bullish", trend_score=50.0,
            stop_price=0.01, targets=[0.01], candles=_aapl(),
            horizon_days=10, seed=3, compute_race=True,
        )
        outcome = res.race.outcomes[0]
        assert outcome.p_target_first == 1.0
        assert outcome.p_stop_first == 0.0

    def test_no_race_when_the_simulation_was_refused(self):
        """A refusal is not a 100%-summing attribution. None, not three zeroes —
        three zeroes would read as 'every outcome is impossible'."""
        from app.scoring.first_passage import estimate_stock_first_passage
        res = estimate_stock_first_passage(
            stock_price=100.0, direction="Bullish", trend_score=50.0,
            stop_price=95.0, targets=[110.0], candles=_aapl(),
            horizon_days=0, seed=1, compute_race=True,
        )
        assert res.race is None

    def test_the_existing_first_passage_endpoint_still_gets_no_race(self):
        """compute_race defaults to False, so /stocks/first-passage's response is
        untouched by this piece."""
        from app.scoring.first_passage import estimate_stock_first_passage
        res = estimate_stock_first_passage(
            stock_price=100.0, direction="Bullish", trend_score=50.0,
            stop_price=95.0, targets=[110.0], candles=_aapl(),
            horizon_days=10, seed=1,
        )
        assert res.race is None


# ── Determinism, the cent floor, and the model caveat ─────────────────────────

class TestMisc:
    def test_identical_requests_return_identical_numbers(self):
        """A seeded Monte Carlo, so repeated presses must not show visible noise
        next to an unchanged stop."""
        assert _post().json() == _post().json()

    def test_a_different_entry_price_draws_independently(self):
        a = _post(entry_price=211.59).json()
        b = _post(entry_price=205.00).json()
        assert a["stop"]["price"] != b["stop"]["price"]

    def test_a_bullish_atr_floor_driven_below_zero_is_floored_at_a_cent(self):
        """entry 3.00 with an ATR near 2.00 puts the 2x floor at -1.00. A stop at
        or below zero is not a level — the same cent floor resolve_stock_stop
        applies, and the raw floor is still reported so the card can show why."""
        bars = [{"time": str(i), "open": 3.0, "high": 4.0, "low": 2.0,
                 "close": 3.0, "volume": 1_000_000} for i in range(60)]
        body = _post(candles=bars, entry_price=3.0).json()
        assert body["stop"]["atrFloorPrice"] < 0
        assert body["stop"]["price"] == 0.01
        assert body["stop"]["riskPerShare"] == 2.99
        # And the targets are built off the FLOORED stop, so the chain still adds up.
        for row in body["targets"]:
            assert row["arithmeticPrice"] == round(3.0 + row["rrRatio"] * 2.99, 2)

    def test_mean_reversion_strategies_carry_the_gbm_caveat(self):
        from app.routers.stock_scan import _MEAN_REVERSION_CAVEAT
        assert _post(strategy="mean_reversion_bb").json()["modelCaveat"] == _MEAN_REVERSION_CAVEAT

    def test_intraday_mean_reversion_carries_the_stronger_caveat(self):
        from app.routers.stock_scan import (
            _INTRADAY_MEAN_REVERSION_CAVEAT, _INTRADAY_STRATEGIES,
        )
        strategy = sorted(_INTRADAY_STRATEGIES)[0]
        assert _post(strategy=strategy).json()["modelCaveat"] == _INTRADAY_MEAN_REVERSION_CAVEAT

    def test_trend_following_strategies_carry_no_caveat(self):
        assert _post(strategy="breakout_base").json()["modelCaveat"] is None

    def test_an_absent_strategy_carries_no_caveat(self):
        """The arithmetic plan stands on its own without one, so `strategy` is
        optional — and an absent one must not crash the caveat rule."""
        assert _post().json()["modelCaveat"] is None

    def test_the_caveat_rule_has_one_implementation(self):
        """Both endpoints report probabilities from the SAME estimator over the
        same paths. Two copies of the rule would eventually caption one card and
        not the other for the same number."""
        from app.routers.stock_scan import _model_caveat_for, _MEAN_REVERSION_CAVEAT
        assert _model_caveat_for("mean_reversion_rsi") == _MEAN_REVERSION_CAVEAT
        assert _model_caveat_for(None) is None
        assert _model_caveat_for("") is None
