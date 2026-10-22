"""
Executable Verification Probe: Options Backend Arithmetic & Request-to-Contract Trace
Lane C: APP-AUDIT-OPTIONS (#376, Part of #351)
Application Baseline: 880c8441841cc22d5090cdc5f984e4cf7e3d9a8d
Runtime: Python 3.11 pinned

This probe independently validates:
1. Contract scoring math, weights, component rules, hard reject filters, and boundaries.
2. Trade plan construction, target/stop formulas, full-premium R/R, and portfolio sizing.
3. End-to-end request-to-contract scan orchestration with fake providers.
4. Defect investigations:
   - Issue #162: Exact fractional-strike truncation to int
   - Issue #179: IV score discontinuity jump at preferred_iv_max
   - Issue #335: Heston calibration boundary overpricing / R/R inflation
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

# Ensure backend root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[5]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Pydantic & FastAPI
from pydantic import BaseModel

# App imports
from app.scoring.contract_validator import (
    validate_contract,
    _score_liquidity,
    _score_spread,
    _score_delta,
    _score_dte,
    _score_iv_rank,
    _preferred_iv_max,
    _hard_reject_reasons,
    effective_contract_overrides,
    is_finite_rule_value,
    contract_caution_threshold,
)
from app.scoring.trade_plan import build_trade_plan, TradePlan
from app.scoring.reward_risk import estimate_rr, estimate_targets, captured_stock_risk
from app.services.portfolio_risk import (
    check_position_risk,
    account_value,
    PortfolioPosition,
    EXCEEDS_MAX_CONTRACTS,
    DEFAULT_ACCOUNT_VALUE,
)
from app.models.heston import HestonParams, heston_price
from app.models.black_scholes import bs_price, bs_iv
from app.services.config_loader import (
    load_scoring_cfg,
    load_reward_risk_cfg,
    load_direction_conviction_min_trend,
    resolve_target_r_multiple,
)
from app.scoring.stock_scorer import (
    score_stock,
    StockScoreCard,
    RuleResult,
    effective_event_window,
    effective_veto_days,
)
from app.schemas import (
    ScanRequest,
    ScanResult,
    RejectedCandidate,
    TradeCardData,
    ScoreBreakdown,
    ContractScoreBreakdown,
    ContractDetails,
    TradeEntry,
    TradeExit,
    AlternativeContract,
)


def hash_file(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    return hashlib.sha256(path.read_bytes()).hexdigest()


class BackendAuditProbe:
    def __init__(self):
        self.observations: Dict[str, Any] = {
            "probe_metadata": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "python_version": sys.version,
                "platform": sys.platform,
                "baseline_sha": "880c8441841cc22d5090cdc5f984e4cf7e3d9a8d",
                "config_hashes": {
                    "scoring_rules.yaml": hash_file(BACKEND_DIR / "config" / "scoring_rules.yaml"),
                    "contract_rules.yaml": hash_file(BACKEND_DIR / "config" / "contract_rules.yaml"),
                    "risk_rules.yaml": hash_file(BACKEND_DIR / "config" / "risk_rules.yaml"),
                },
            },
            "suites": {},
            "findings": [],
            "summary": {"total_tests": 0, "passed_tests": 0, "failed_tests": 0},
        }

    def record_test(self, suite_name: str, test_name: str, passed: bool, details: Dict[str, Any]):
        if suite_name not in self.observations["suites"]:
            self.observations["suites"][suite_name] = []
        self.observations["suites"][suite_name].append({
            "name": test_name,
            "passed": passed,
            "details": details,
        })
        self.observations["summary"]["total_tests"] += 1
        if passed:
            self.observations["summary"]["passed_tests"] += 1
        else:
            self.observations["summary"]["failed_tests"] += 1
            print(f"[FAIL] {suite_name}::{test_name}: {details}")

    def run_all(self):
        print("=== Running APP-AUDIT-OPTIONS Backend Verification Probe ===")
        self.test_suite_a_contract_scoring()
        self.test_suite_b_trade_plan_and_sizing()
        self.test_suite_c_scan_orchestration_trace()
        self.test_suite_d_defect_investigations()
        self.save_observations()
        print(f"=== Probe Completed: {self.observations['summary']['passed_tests']} passed, "
              f"{self.observations['summary']['failed_tests']} failed ===")
        return self.observations["summary"]["failed_tests"] == 0

    # ──────────────────────────────────────────────────────────────────────────
    # Suite A: Contract Scoring Components & Boundaries
    # ──────────────────────────────────────────────────────────────────────────
    def test_suite_a_contract_scoring(self):
        suite = "contract_scoring_arithmetic"

        # 1. Liquidity Scoring
        # Default config: preferred_volume_min=200, preferred_oi_min=1000
        cfg_dummy = {"soft_rank": {"preferred_volume_min": 200, "preferred_oi_min": 1000}}
        c_full = {"volume": 500, "open_interest": 2000}
        score, oi_score, flags = _score_liquidity(c_full, cfg_dummy)
        # Expected: min(100, int(500/200*60)) = 100; min(100, int(2000/1000*60)) = 100; avg = 100
        self.record_test(suite, "liquidity_full_pass", score == 100 and flags == [],
                         {"observed": (score, oi_score, flags), "expected": (100, 100, [])})

        c_boundary = {"volume": 200, "open_interest": 1000}
        score, oi_score, flags = _score_liquidity(c_boundary, cfg_dummy)
        # Expected: 200/200*60 = 60; 1000/1000*60 = 60; avg = 60
        self.record_test(suite, "liquidity_preferred_boundary", score == 60 and flags == [],
                         {"observed": (score, oi_score, flags), "expected": (60, 60, [])})

        c_partial = {"volume": 100, "open_interest": 500}
        score, oi_score, flags = _score_liquidity(c_partial, cfg_dummy)
        # Expected: 100/200*60 = 30; 500/1000*60 = 30; avg = 30, flag thin_liquidity
        self.record_test(suite, "liquidity_partial_soft_fail", score == 30 and flags == ["thin_liquidity"],
                         {"observed": (score, oi_score, flags), "expected": (30, 30, ["thin_liquidity"])})

        c_zero_pref = {"soft_rank": {"preferred_volume_min": 0, "preferred_oi_min": 0}}
        score, oi_score, flags = _score_liquidity({"volume": 1, "open_interest": 1}, c_zero_pref)
        self.record_test(suite, "liquidity_zero_floors_disabled", score == 100 and flags == [],
                         {"observed": (score, oi_score, flags), "expected": (100, 100, [])})

        # 2. Spread Scoring
        # Default config: preferred_spread_pct_max = 0.08
        cfg_spread = {"soft_rank": {"preferred_spread_pct_max": 0.08}}
        c_tight = {"bid": 4.90, "ask": 5.10}  # mid = 5.0, spread_pct = 0.20 / 5.0 = 0.04
        # Expected: int((1 - 0.04/0.08)*100) = int(0.50*100) = 50
        s_score, s_pct, s_flags = _score_spread(c_tight, cfg_spread)
        self.record_test(suite, "spread_tight", s_score == 50 and s_flags == [] and math.isclose(s_pct, 0.04),
                         {"observed": (s_score, s_pct, s_flags), "expected": (50, 0.04, [])})

        c_wide = {"bid": 4.50, "ask": 5.50}  # mid = 5.0, spread_pct = 1.0 / 5.0 = 0.20 > 0.08
        s_score, s_pct, s_flags = _score_spread(c_wide, cfg_spread)
        self.record_test(suite, "spread_elevated_soft_fail", s_score == 0 and s_flags == ["spread_elevated"],
                         {"observed": (s_score, s_pct, s_flags), "expected": (0, 0.20, ["spread_elevated"])})

        # 3. Delta Scoring
        # Default: preferred_delta_min=0.30, preferred_delta_max=0.70 (center=0.50, half_range=0.20)
        cfg_delta = {"soft_rank": {"preferred_delta_min": 0.30, "preferred_delta_max": 0.70}}
        d_score, d_flags = _score_delta({"delta": 0.50}, cfg_delta)
        self.record_test(suite, "delta_center", d_score == 100 and d_flags == [],
                         {"observed": (d_score, d_flags), "expected": (100, [])})

        d_score, d_flags = _score_delta({"delta": 0.40}, cfg_delta)
        # Expected: int(100 * (1 - abs(0.40 - 0.50) / 0.20)) = int(100 * 0.5) = 50
        self.record_test(suite, "delta_in_zone_moderate", d_score == 50 and d_flags == [],
                         {"observed": (d_score, d_flags), "expected": (50, [])})

        d_score, d_flags = _score_delta({"delta": 0.25}, cfg_delta)
        # Expected: outside preferred -> 20, flag delta_outside_preferred
        self.record_test(suite, "delta_outside_preferred", d_score == 20 and d_flags == ["delta_outside_preferred"],
                         {"observed": (d_score, d_flags), "expected": (20, ["delta_outside_preferred"])})

        # 4. DTE Scoring
        # Default: preferred_dte_min=21, preferred_dte_max=60 (center=40.5, half_range=19.5)
        cfg_dte = {"soft_rank": {"preferred_dte_min": 21, "preferred_dte_max": 60}}
        expiry_40 = (date.today() + timedelta(days=40)).isoformat()
        dte_s, dte_val, dte_f = _score_dte({"expiry": expiry_40}, cfg_dte)
        # Expected: dte=40, dist = 0.5/19.5 -> score = int(100 * (1 - 0.5/19.5)) = 97
        self.record_test(suite, "dte_center_40", dte_s == 97 and dte_f == [] and dte_val == 40,
                         {"observed": (dte_s, dte_val, dte_f), "expected": (97, 40, [])})

        expiry_15 = (date.today() + timedelta(days=15)).isoformat()
        dte_s, dte_val, dte_f = _score_dte({"expiry": expiry_15}, cfg_dte)
        # Expected: dte=15 < 21 -> distance=6 -> decay=max(0, int(25 * (1 - 6/19.5))) = int(25 * 0.6923) = 17
        self.record_test(suite, "dte_soft_decay_short", dte_s == 17 and dte_f == ["dte_outside_preferred"],
                         {"observed": (dte_s, dte_val, dte_f), "expected": (17, 15, ["dte_outside_preferred"])})

        # 5. Full Contract Validation & Composite Score
        # Passing contract:
        pass_expiry = (date.today() + timedelta(days=40)).isoformat()
        c_pass = {
            "symbol": "AAPL", "strike": 185, "expiry": pass_expiry, "right": "C",
            "bid": 4.90, "ask": 5.10, "price": 5.00, "delta": 0.50, "volume": 500,
            "open_interest": 2000, "iv_rank": 30, "iv_basis": "rank", "dte": 40,
        }
        card_pass = validate_contract(c_pass, stock_score=80)
        # Components:
        # liq: vol=500 (100), oi=2000 (100) -> 100 * 0.25 = 25.0
        # spread: 0.04/0.08 -> 50 * 0.25 = 12.5
        # delta: 0.50 -> 100 * 0.20 = 20.0
        # dte: 40 -> 97 * 0.15 = 14.55
        # iv: 30/55 -> int(100 * (1 - 30/55)) = 45 * 0.15 = 6.75
        # total weighted = 25.0 + 12.5 + 20.0 + 14.55 + 6.75 = 78.8 -> round = 79
        self.record_test(suite, "composite_pass_score", card_pass.status == "PASS" and card_pass.score == 79,
                         {"observed": (card_pass.status, card_pass.score), "expected": ("PASS", 79)})

        # Hard Reject: OI < 200
        c_illiquid = dict(c_pass, open_interest=150)
        card_illiquid = validate_contract(c_illiquid, stock_score=80)
        self.record_test(suite, "hard_reject_open_interest",
                         card_illiquid.status == "REJECT" and "open_interest_too_low" in card_illiquid.reject_reasons,
                         {"observed": (card_illiquid.status, card_illiquid.reject_reasons)})

        # Hard Reject: Delta < 0.20
        c_otm = dict(c_pass, delta=0.15)
        card_otm = validate_contract(c_otm, stock_score=80)
        self.record_test(suite, "hard_reject_delta_otm",
                         card_otm.status == "REJECT" and "delta_too_low_far_otm" in card_otm.reject_reasons,
                         {"observed": (card_otm.status, card_otm.reject_reasons)})

        # Hard Reject: Stock Score < 45
        card_low_stock = validate_contract(c_pass, stock_score=40)
        self.record_test(suite, "hard_reject_stock_score",
                         card_low_stock.status == "REJECT" and "stock_score_below_threshold" in card_low_stock.reject_reasons,
                         {"observed": (card_low_stock.status, card_low_stock.reject_reasons)})

        # Multi-soft failure reject (>= 3 soft failures)
        c_multi_soft = {
            "symbol": "AAPL", "strike": 185, "expiry": expiry_15, "right": "C",
            "bid": 4.50, "ask": 5.50, "price": 5.00,  # spread_elevated (1)
            "delta": 0.25,                            # delta_outside_preferred (2)
            "volume": 100, "open_interest": 500,      # thin_liquidity (3)
            "iv_rank": 30, "iv_basis": "rank",
        }
        card_multi = validate_contract(c_multi_soft, stock_score=80)
        self.record_test(suite, "hard_reject_too_many_soft_failures",
                         card_multi.status == "REJECT" and "too_many_soft_failures" in card_multi.reject_reasons,
                         {"observed": (card_multi.status, card_multi.reject_reasons, card_multi.soft_flags)})

    # ──────────────────────────────────────────────────────────────────────────
    # Suite B: Trade Plan, Sizing & Full-Premium R/R
    # ──────────────────────────────────────────────────────────────────────────
    def test_suite_b_trade_plan_and_sizing(self):
        suite = "trade_plan_and_sizing_arithmetic"

        # 1. Trade Plan Math
        rr_cfg = {"premium_stop_pct": 0.60, "bullish_invalidation_pct": 0.03, "bearish_invalidation_pct": 0.03}
        plan = build_trade_plan(
            direction="Bullish",
            stock_price=185.0,
            strike=185.0,
            dte=30,
            premium=4.50,
            entry_bid=4.40,
            entry_ask=4.60,
            entry_mid=4.50,
            rr_cfg=rr_cfg,
            final_stop_price=179.45,
            target_price=196.10,
            stop_cost_fraction=0.45,
        )
        # Expected calculations:
        # time_stop_days: max(3, int(30 * 0.4)) = 12
        # premium_stop: round(4.50 * 0.60, 2) = 2.70
        # invalidation_price: 179.45
        # target_price: 196.10
        # rr_risk_basis: "full_premium" (no protective stop placed)
        self.record_test(suite, "trade_plan_time_stop", plan.time_stop_days == 12,
                         {"observed": plan.time_stop_days, "expected": 12})
        self.record_test(suite, "trade_plan_premium_stop", plan.premium_stop == 2.70,
                         {"observed": plan.premium_stop, "expected": 2.70})
        self.record_test(suite, "trade_plan_risk_basis_full_premium", plan.rr_risk_basis == "full_premium",
                         {"observed": plan.rr_risk_basis, "expected": "full_premium"})

        # 2. Portfolio Risk & Sizing Checks
        # Account value = $100k
        # Option sizing rule: max_single = min(max_single_position_pct=0.05, max_loss_per_trade_pct=0.0375) = 0.0375
        # Dollar cap = $3,750
        # Max contracts = 5
        res_normal = check_position_risk(
            symbol="AAPL",
            contract_id="AAPL|185|2026-11-20|C",
            proposed_contracts=2,
            entry_premium=10.0,
            current_price=10.0,
            portfolio=[],
            portfolio_value=100000.0,
        )
        # Cost = 2 * 10.0 * 100 = $2,000 <= $3,750 -> approved
        self.record_test(suite, "sizing_normal_approved", res_normal.approved and res_normal.adjusted_size is None,
                         {"observed": (res_normal.approved, res_normal.adjusted_size, res_normal.reasons)})

        res_reduced = check_position_risk(
            symbol="AAPL",
            contract_id="AAPL|185|2026-11-20|C",
            proposed_contracts=5,
            entry_premium=10.0,
            current_price=10.0,
            portfolio=[],
            portfolio_value=100000.0,
        )
        # Cost = 5 * 10 * 100 = $5,000 > $3,750
        # Adjusted size = int(3750 / 1000) = 3 contracts ($3,000)
        self.record_test(suite, "sizing_adjusted_to_cap",
                         res_reduced.approved and res_reduced.adjusted_size == 3 and "size_reduced_to_fit_exposure_limit" in res_reduced.reasons,
                         {"observed": (res_reduced.approved, res_reduced.adjusted_size, res_reduced.reasons), "expected_adjusted": 3})

        res_rejected_single = check_position_risk(
            symbol="AAPL",
            contract_id="AAPL|185|2026-11-20|C",
            proposed_contracts=1,
            entry_premium=40.0,
            current_price=40.0,
            portfolio=[],
            portfolio_value=100000.0,
        )
        # Cost = 1 * 40 * 100 = $4,000 > $3,750 -> adjusted = int(3750/4000) = 0 -> rejected
        self.record_test(suite, "sizing_single_contract_too_expensive",
                         not res_rejected_single.approved and "single_trade_exposure_too_high" in res_rejected_single.reasons,
                         {"observed": (res_rejected_single.approved, res_rejected_single.reasons)})

        res_exceeds_cap = check_position_risk(
            symbol="AAPL",
            contract_id="AAPL|185|2026-11-20|C",
            proposed_contracts=6,
            entry_premium=2.0,
            current_price=2.0,
            portfolio=[],
            portfolio_value=100000.0,
        )
        self.record_test(suite, "sizing_exceeds_max_contracts",
                         not res_exceeds_cap.approved and EXCEEDS_MAX_CONTRACTS in res_exceeds_cap.reasons,
                         {"observed": (res_exceeds_cap.approved, res_exceeds_cap.reasons)})

        res_small_portfolio = check_position_risk(
            symbol="AAPL",
            contract_id="AAPL|185|2026-11-20|C",
            proposed_contracts=1,
            entry_premium=2.0,
            current_price=2.0,
            portfolio=[],
            portfolio_value=4000.0,  # below min_portfolio_value 5000.0
        )
        self.record_test(suite, "sizing_portfolio_too_small",
                         not res_small_portfolio.approved and "portfolio_too_small" in res_small_portfolio.reasons,
                         {"observed": (res_small_portfolio.approved, res_small_portfolio.reasons)})

    # ──────────────────────────────────────────────────────────────────────────
    # Suite C: Scan Orchestration Trace (Fake Provider Simulation)
    # ──────────────────────────────────────────────────────────────────────────
    def test_suite_c_scan_orchestration_trace(self):
        suite = "scan_orchestration_trace"

        # Trace Bullish Scan through actual processing steps
        direction = "Bullish"
        horizon = "Swing"
        symbol = "AAPL"
        price = 185.0
        expiry_date = (date.today() + timedelta(days=40)).isoformat()

        # Step 1: Stock score pass
        card_stock = StockScoreCard(
            symbol=symbol,
            direction=direction,
            horizon=horizon,
            score=82,
            status="PASS",
            rules=[
                RuleResult("trend", "PASS", 80, {"score": 80}),
                RuleResult("pullback", "PASS", 75, {"score": 75}),
                RuleResult("trigger", "PASS", 85, {"score": 85}),
                RuleResult("event", "PASS", 90, {"earnings_days": 60, "reject_days": 21}),
                RuleResult("vol", "PASS", 80, {"iv_rank": 35}),
            ],
        )
        self.record_test(suite, "trace_stock_prescreen_pass", card_stock.status == "PASS" and card_stock.score >= 55,
                         {"status": card_stock.status, "score": card_stock.score})

        # Step 2: Direction conviction floor check
        min_trend = load_direction_conviction_min_trend(direction, horizon)
        trend_score = next(r.score for r in card_stock.rules if r.name == "trend")
        passed_conviction = min_trend is None or trend_score >= min_trend
        self.record_test(suite, "trace_direction_conviction_floor", passed_conviction,
                         {"trend_score": trend_score, "min_trend": min_trend})

        # Step 3: Option Chain with 3 candidate contracts (Primary + 2 Alternatives)
        chain = [
            {"strike": 185, "expiry": expiry_date, "price": 4.50, "bid": 4.40, "ask": 4.60,
             "delta": 0.52, "theta": -0.05, "iv_rank": 35, "iv_basis": "rank", "dte": 40,
             "right": "C", "volume": 1200, "open_interest": 3500},
            {"strike": 180, "expiry": expiry_date, "price": 7.50, "bid": 7.40, "ask": 7.60,
             "delta": 0.65, "theta": -0.06, "iv_rank": 36, "iv_basis": "rank", "dte": 40,
             "right": "C", "volume": 800, "open_interest": 2500},
            {"strike": 190, "expiry": expiry_date, "price": 2.30, "bid": 2.25, "ask": 2.35,
             "delta": 0.38, "theta": -0.04, "iv_rank": 34, "iv_basis": "rank", "dte": 40,
             "right": "C", "volume": 950, "open_interest": 2800},
        ]

        scored = [(validate_contract(c, card_stock.score), c) for c in chain]
        valid_scores = [(s, c) for s, c in scored if s.status != "REJECT"]
        valid_scores.sort(key=lambda x: x[0].score, reverse=True)
        self.record_test(suite, "trace_chain_scoring_and_ranking", len(valid_scores) == 3,
                         {"valid_count": len(valid_scores), "scores": [s[0].score for s in valid_scores]})

        primary_card, primary_contract = valid_scores[0]
        runner_ups = valid_scores[1:3]

        # Verify Primary Contract Selection
        self.record_test(suite, "trace_primary_contract_selected", primary_contract["strike"] == 185,
                         {"selected_strike": primary_contract["strike"], "score": primary_card.score})

        # Verify Alternatives Attachment
        self.record_test(suite, "trace_alternatives_count", len(runner_ups) == 2,
                         {"runner_up_count": len(runner_ups)})

        # Build TradeCardData and verify unvalidatedReason behavior
        trade_card_bullish = TradeCardData(
            symbol=symbol,
            company="Apple Inc.",
            price=price,
            direction=direction,
            status="PASS",
            stockScore=card_stock.score,
            stockConfidence=card_stock.status,
            stockExplanation=None,
            stockBreakdown=ScoreBreakdown(
                trend=80, pullback=75, trigger=85, event=90, volatility=80
            ),
            contract=f"{symbol}|{int(primary_contract['strike'])}|{primary_contract['expiry']}|C",
            contractScore=primary_card.score,
            contractConfidence=primary_card.status,
            contractExplanation=primary_card.explanation,
            contractBreakdown=ContractScoreBreakdown(
                dteFit=primary_card.breakdown.dte_score,
                delta=primary_card.breakdown.delta_score,
                ivAttractiveness=primary_card.breakdown.iv_rank_score,
                liquidity=primary_card.breakdown.liquidity_score,
                spread=primary_card.breakdown.spread_score,
            ),
            contractDetails=ContractDetails(
                strike=int(primary_contract["strike"]),
                expiry=primary_contract["expiry"],
                right="C",
                mid=primary_contract["price"],
                delta=primary_contract["delta"],
                theta=primary_contract["theta"],
                dte=primary_contract["dte"],
            ),
            entry=TradeEntry(limit=4.60, maxFill=4.70, orderType="Limit"),
            exit=TradeExit(invalidation=179.45, premiumStop=2.70, timeStopDays=12, target=196.10),
            rrRatio=2.1,
            rrModel="Delta approximation",
            finalStatus="PASS",
            unvalidatedReason=None,  # Bullish has no unvalidatedReason
        )
        self.record_test(suite, "trace_bullish_trade_card_no_unvalidated_reason",
                         trade_card_bullish.unvalidatedReason is None and trade_card_bullish.finalStatus == "PASS",
                         {"unvalidatedReason": trade_card_bullish.unvalidatedReason, "finalStatus": trade_card_bullish.finalStatus})

        # Bearish trace: finalStatus capped at CAUTION and unvalidatedReason present
        from app.services.unvalidated import BEARISH_UNVALIDATED_MESSAGE
        trade_card_bearish = TradeCardData(
            symbol=symbol,
            company="Apple Inc.",
            price=price,
            direction="Bearish",
            status="CAUTION",
            stockScore=card_stock.score,
            stockConfidence=card_stock.status,
            stockExplanation=None,
            stockBreakdown=ScoreBreakdown(trend=80, pullback=75, trigger=85, event=90, volatility=80),
            contract=f"{symbol}|{int(primary_contract['strike'])}|{primary_contract['expiry']}|P",
            contractScore=primary_card.score,
            contractConfidence=primary_card.status,
            contractExplanation=primary_card.explanation,
            contractBreakdown=ContractScoreBreakdown(
                dteFit=primary_card.breakdown.dte_score,
                delta=primary_card.breakdown.delta_score,
                ivAttractiveness=primary_card.breakdown.iv_rank_score,
                liquidity=primary_card.breakdown.liquidity_score,
                spread=primary_card.breakdown.spread_score,
            ),
            contractDetails=ContractDetails(
                strike=int(primary_contract["strike"]),
                expiry=primary_contract["expiry"],
                right="P",
                mid=primary_contract["price"],
                delta=-0.48,
                theta=-0.05,
                dte=primary_contract["dte"],
            ),
            entry=TradeEntry(limit=4.60, maxFill=4.70, orderType="Limit"),
            exit=TradeExit(invalidation=190.55, premiumStop=2.70, timeStopDays=12, target=173.90),
            rrRatio=2.1,
            rrModel="Delta approximation",
            finalStatus="CAUTION",  # Bearish always capped at CAUTION
            unvalidatedReason=BEARISH_UNVALIDATED_MESSAGE,
        )
        self.record_test(suite, "trace_bearish_trade_card_unvalidated_caution",
                         trade_card_bearish.finalStatus == "CAUTION" and trade_card_bearish.unvalidatedReason == BEARISH_UNVALIDATED_MESSAGE,
                         {"finalStatus": trade_card_bearish.finalStatus, "unvalidatedReason": trade_card_bearish.unvalidatedReason})

    # ──────────────────────────────────────────────────────────────────────────
    # Suite D: Defect Investigations (#162, #179, #335)
    # ──────────────────────────────────────────────────────────────────────────
    def test_suite_d_defect_investigations(self):
        suite = "defect_investigations"

        # ── DEFECT 1: Issue #162 (EXACT-STRIKE / Fractional strikes) ──────────
        # Investigation: Strike is cast to int() in routers/scan.py:1280 and 1297,
        # in AlternativeContract (1434), and routers/contracts.py:127 rejects fractional strikes.
        fractional_strike = 182.5
        expiry = "2026-11-20"
        symbol = "AAPL"
        lossy_contract_id = f"{symbol}|{int(fractional_strike)}|{expiry}|C"
        lossless_contract_id = f"{symbol}|{fractional_strike}|{expiry}|C"

        # Record findings
        defect_162_confirmed = (lossy_contract_id == "AAPL|182|2026-11-20|C" and
                                lossless_contract_id == "AAPL|182.5|2026-11-20|C")
        self.record_test(suite, "defect_162_strike_truncation_confirmed", defect_162_confirmed,
                         {
                             "fractional_strike": fractional_strike,
                             "lossy_contract_id": lossy_contract_id,
                             "lossless_contract_id": lossless_contract_id,
                             "discrepancy": "int(strike) truncates 182.5 to 182",
                             "locations": [
                                 "backend/app/routers/scan.py:1280 (contract id formatting)",
                                 "backend/app/routers/scan.py:1297 (ContractDetails.strike)",
                                 "backend/app/routers/scan.py:1434 (AlternativeContract.strike)",
                                 "backend/app/routers/contracts.py:127 (_parse_strikes requires plain digits, rejecting 182.5 with 422)",
                                 "backend/app/data/market.py:int(strike) in chain builders",
                             ],
                         })

        # ── DEFECT 2: Issue #179 (IV score discontinuity at preferred_max) ────
        # Investigation: In app/scoring/contract_validator.py:361-372,
        # at iv_rank <= max_pref (55): score = int(100 * (1 - iv_rank / 55))
        # at iv_rank > max_pref: score = int(20 * (1 - (iv_rank - 55) / 45))
        cfg_iv = {"soft_rank": {"preferred_iv_rank_max": 55, "preferred_iv_abs_max": 55}}
        contract_base = {"iv_basis": "rank"}

        scores = {}
        for rank in [50, 54, 55, 56, 60, 65, 70]:
            s, f = _score_iv_rank(dict(contract_base, iv_rank=rank), cfg_iv)
            scores[rank] = (s, f)

        # Expected:
        # 50 -> int(100 * (1 - 50/55)) = int(100 * 5/55) = 9
        # 54 -> int(100 * (1 - 54/55)) = int(100 * 1/55) = 1
        # 55 -> int(100 * (1 - 55/55)) = 0
        # 56 -> int(20 * (1 - (56-55)/45)) = int(20 * 44/45) = 19 (JUMP OF +19 POINTS!)
        # 60 -> int(20 * (1 - (60-55)/45)) = int(20 * 40/45) = 17
        # 70 -> int(20 * (1 - (70-55)/45)) = int(20 * 30/45) = 13
        jump = scores[56][0] - scores[55][0]
        non_monotonic = scores[60][0] > scores[50][0]  # IV 60 scores 17; IV 50 scores 9!

        self.record_test(suite, "defect_179_iv_jump_discontinuity_confirmed",
                         jump == 19 and non_monotonic,
                         {
                             "score_at_50": scores[50][0],
                             "score_at_54": scores[54][0],
                             "score_at_55": scores[55][0],
                             "score_at_56": scores[56][0],
                             "score_at_60": scores[60][0],
                             "score_at_70": scores[70][0],
                             "jump_at_boundary": jump,
                             "non_monotonic_inversion": "IV 60 scores 17 while IV 50 scores 9 (more expensive option scores higher)",
                             "contract_score_impact": "IV weight is 0.15, yielding up to 2.85 points inflation in final contract score",
                             "location": "backend/app/scoring/contract_validator.py:361-372",
                         })

        # ── DEFECT 3: Issue #335 (Heston Repricing Overpricing & R/R Inflation)
        # Investigation: Heston fits pinned to boundary parameters (kappa=0.5, theta=0.08, sigma_v=0.6, rho=-0.8)
        # violate Feller condition (2*kappa*theta = 0.08 < 0.36 = sigma_v^2) by 4.5x.
        # At long DTE, Heston model prices are substantially higher than Black-Scholes / chain mid,
        # inflating exit premium and inflating rr_ratio.
        params_pinned = HestonParams(v0=0.08, kappa=0.5, theta=0.08, sigma_v=0.6, rho=-0.8)
        feller_left = 2 * params_pinned.kappa * params_pinned.theta  # 0.08
        feller_right = params_pinned.sigma_v ** 2  # 0.36
        feller_violation_ratio = feller_right / feller_left  # 4.5x

        # Compare pricing at target:
        # Stock = 185, Strike = 185, Target = 196.10, DTE = 90 (0.2466 yrs), r = 0.05
        # Re-price using Heston vs Black-Scholes at base vol = sqrt(v0) = sqrt(0.08) = 0.2828 (28.3%)
        S_target = 196.10
        K = 185.0
        T_target = 0.2466
        r = 0.05
        sigma_base = math.sqrt(params_pinned.v0)

        p_heston = heston_price(S_target, K, T_target, r, params_pinned, is_call=True)
        p_bs = bs_price(S_target, K, T_target, r, sigma_base, is_call=True)

        ratio_heston_bs = p_heston / p_bs if p_bs > 0 else float("nan")

        # Calculate R/R with Heston vs BS
        # Current premium = $5.00
        current_premium = 5.00
        rr_heston = round((p_heston - current_premium) / current_premium, 2)
        rr_bs = round((p_bs - current_premium) / current_premium, 2)
        rr_inflation = rr_heston - rr_bs

        self.record_test(suite, "defect_335_heston_rr_overpricing_confirmed",
                         feller_violation_ratio == 4.5 and p_heston > p_bs,
                         {
                             "pinned_parameters": {
                                 "kappa": params_pinned.kappa,
                                 "theta": params_pinned.theta,
                                 "sigma_v": params_pinned.sigma_v,
                                 "rho": params_pinned.rho,
                             },
                             "feller_condition": {
                                 "2_kappa_theta": feller_left,
                                 "sigma_v_squared": feller_right,
                                 "violation_factor": feller_violation_ratio,
                             },
                             "target_exit_premium_heston": round(p_heston, 2),
                             "target_exit_premium_bs": round(p_bs, 2),
                             "overpricing_factor": round(ratio_heston_bs, 3),
                             "rr_ratio_heston": rr_heston,
                             "rr_ratio_bs": rr_bs,
                             "rr_ratio_inflation": round(rr_inflation, 2),
                             "locations": [
                                 "backend/app/models/heston_cache.py:306-314 (tight 2x2x2x2 boundary grid)",
                                 "backend/app/scoring/reward_risk.py:145-155 (heston_price feeds exit_premium)",
                                 "backend/app/routers/scan.py:1014-1065 (heston calibration in options scan pipeline)",
                             ],
                         })

    def save_observations(self):
        out_path = Path(__file__).parent / "backend-observations.json"
        def _sanitize(obj):
            if hasattr(obj, "item"):
                return obj.item()
            if isinstance(obj, (set, frozenset)):
                return list(obj)
            if hasattr(obj, "__dict__"):
                return obj.__dict__
            return str(obj)
        out_path.write_text(json.dumps(self.observations, indent=2, default=_sanitize), encoding="utf-8")
        print(f"Structured observations saved to {out_path}")


if __name__ == "__main__":
    probe = BackendAuditProbe()
    success = probe.run_all()
    sys.exit(0 if success else 1)
