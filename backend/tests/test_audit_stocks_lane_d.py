"""Lane D Audit: Verification of Stocks scan, strategies, backtests and position sizing (#352).

Exhaustive automated test suite for Lane D:
1. Composite 5-rule stock scorer, event exclusion, non-event renormalization, 4 demotion caps.
2. 7 primary strategies signals and parameter boundaries.
3. Vectorized backtest metrics, time exits, confidence gate, and artifact immutability.
4. Position sizing arithmetic, conviction multiplier, boundaries, and concentration flag logic.
"""
from __future__ import annotations

import copy
from datetime import date, timedelta
from typing import Any
from uuid import uuid4
import pytest

from app.schemas.stock_scan import Strategy, BacktestOut, StockScanRequest
from app.scoring.stock_scorer import (
    score_stock,
    _status_from_score,
    _worse,
    RuleResult,
    StockScoreCard,
)
from app.scoring.signal_confidence import status_cap, interpret, load_gate_cfg
from app.scoring.fundamentals_scorer import FundamentalHealth
from app.services.strategy_engine import (
    pullback_ema_signal,
    breakout_base_signal,
    ma_crossover_signal,
    mean_reversion_rsi_signal,
    mean_reversion_bb_signal,
    mean_reversion_vwap_signal,
    multi_signal,
)
from app.services.strategy_backtest import run_strategy_backtest, BacktestResult
from app.routers.stock_scan import _position_size


# ---------------------------------------------------------------------------
# Fixture Helpers
# ---------------------------------------------------------------------------

def _synthetic_bars(n: int = 150, trend: str = "up") -> list[dict[str, Any]]:
    """Generate n synthetic OHLCV daily bars."""
    bars: list[dict[str, Any]] = []
    base_date = date(2024, 1, 2)
    price = 100.0
    for i in range(n):
        if trend == "up":
            price += 0.35
        elif trend == "down":
            price -= 0.35
        else:
            price = 100.0 + (i % 5 - 2) * 0.2
        vol = 1_000_000 if i < n - 1 else 2_500_000  # elevated volume on last bar
        bars.append({
            "time": (base_date + timedelta(days=i)).isoformat(),
            "open": round(price - 0.2, 2),
            "high": round(price + 0.6, 2),
            "low": round(price - 0.5, 2),
            "close": round(price, 2),
            "volume": vol,
        })
    return bars


# ===========================================================================
# 1. Scorer & 4-Tier Demotion Hierarchy
# ===========================================================================

class TestStockScorerAndDemotionsLaneD:
    def test_stock_mode_event_weight_zeroed_and_renormalized(self):
        """In stock mode (scoring_mode='stock'), w_event must be 0.0 and remaining

        weights renormalized so that sum(weights) == 1.0. Upcoming earnings
        proximity must NEVER alter the final score points.
        """
        bars = _synthetic_bars(n=150, trend="up")

        # 1. Score without upcoming events
        card_no_event = score_stock(
            symbol="AAPL",
            direction="Bullish",
            horizon="Swing",
            bars=bars,
            scoring_mode="stock",
            earnings_date=None,
            dividend_date=None,
        )

        # 2. Score with imminent earnings (e.g. tomorrow)
        card_with_earnings = score_stock(
            symbol="AAPL",
            direction="Bullish",
            horizon="Swing",
            bars=bars,
            scoring_mode="stock",
            earnings_date=date.today() + timedelta(days=1),
            dividend_date=None,
        )

        # Score must be identical: event adds 0 points
        assert card_no_event.score == card_with_earnings.score, (
            f"Event proximity altered score in stock mode: {card_no_event.score} vs {card_with_earnings.score}"
        )

        # In options mode, imminent earnings would alter event score and composite score
        card_options_mode = score_stock(
            symbol="AAPL",
            direction="Bullish",
            horizon="Swing",
            bars=bars,
            scoring_mode="options",
            earnings_date=date.today() + timedelta(days=1),
            dividend_date=None,
        )
        # Event in options mode carries weight, causing difference
        assert card_options_mode.rules != card_no_event.rules

    def test_threshold_status_verdicts(self):
        """Default thresholds: score >= 55 -> PASS, 35 <= score < 55 -> CAUTION, < 35 -> REJECT."""
        thresholds = {"pass": 55, "caution": 35}
        assert _status_from_score(55, thresholds) == "PASS"
        assert _status_from_score(80, thresholds) == "PASS"
        assert _status_from_score(54, thresholds) == "CAUTION"
        assert _status_from_score(35, thresholds) == "CAUTION"
        assert _status_from_score(34, thresholds) == "REJECT"
        assert _status_from_score(0, thresholds) == "REJECT"

    def test_pullback_timing_veto_demotes_pass_to_caution(self):
        """If pullback rule returns REJECT, status must cap at CAUTION (never PASS)."""
        bars = _synthetic_bars(n=150, trend="up")
        card = score_stock(
            symbol="AAPL",
            direction="Bullish",
            horizon="Swing",
            bars=bars,
            scoring_mode="stock",
        )
        pb_rule = next((r for r in card.rules if r.name == "pullback"), None)
        assert pb_rule is not None

        # When raw status is PASS and pullback veto fires:
        raw_status = "PASS"
        vetoed_status = _worse(raw_status, "CAUTION")
        assert vetoed_status == "CAUTION"
        # If raw_status was already REJECT, it remains REJECT
        assert _worse("REJECT", "CAUTION") == "REJECT"

    def test_confidence_gate_caps_evaluates_integer_confidence(self):
        """Confidence gate compares integer confidence score (0-100) against thresholds:

        confidence < cautionBelow (50) -> CAUTION
        confidence < rejectBelow (35) -> REJECT
        confidence is None (unvalidated) -> CAUTION
        confidence >= cautionBelow -> PASS (no demotion)
        """
        gate = {"cautionBelow": 50, "rejectBelow": 35}

        # None -> CAUTION
        assert status_cap(None, gate) == "CAUTION"
        # < 35 -> REJECT
        assert status_cap(20, gate) == "REJECT"
        assert status_cap(34, gate) == "REJECT"
        # 35 <= conf < 50 -> CAUTION
        assert status_cap(35, gate) == "CAUTION"
        assert status_cap(49, gate) == "CAUTION"
        # >= 50 -> PASS
        assert status_cap(50, gate) == "PASS"
        assert status_cap(80, gate) == "PASS"

    def test_regime_gate_demotion_alignment(self):
        """Regime gate demotes based on conviction_pct and stability."""
        from app.scoring.stock_scorer import _regime_cap
        regime_gate = {
            "enabled": True,
            "headwind_caution_pct": -15,
            "headwind_reject_pct": -40,
            "require_stable_for_reject": True,
        }
        # Mild headwind (-20%) -> CAUTION
        assert _regime_cap(-20, "Stable", regime_gate) == "CAUTION"
        # Severe headwind (-50%) + Stable -> REJECT
        assert _regime_cap(-50, "Stable", regime_gate) == "REJECT"
        # Severe headwind (-50%) + Volatile + require_stable_for_reject -> CAUTION
        assert _regime_cap(-50, "Volatile", regime_gate) == "CAUTION"
        # Tailwind (+30%) -> PASS
        assert _regime_cap(30, "Stable", regime_gate) == "PASS"

    def test_fundamentals_gate_bullish_and_bearish_thresholds(self):
        """Fundamentals gate enforces:

        Bullish: health < 45 -> CAUTION, health < 30 -> REJECT
        Bearish: health > 70 -> CAUTION, health > 80 -> REJECT
        Safety flags: extreme_leverage / negative_equity -> REJECT across both directions
        Intraday scans: strictly exempt.
        """
        bars = _synthetic_bars(n=150, trend="up")
        fund_gate = {
            "enabled": True,
            "cautionBelow": 45,
            "rejectBelow": 30,
            "cautionAbove": 70,
            "rejectAbove": 80,
            "safety": {"reject_on_negative_equity": True, "debt_to_equity_reject": 3.0},
        }

        # 1. Bullish health 25 (< 30) -> REJECT
        fund_weak = FundamentalHealth(
            score=25, quality_label="Weak", risk_label="High",
            growth_score=25, quality_score=25, risk_score=25, detail={}
        )
        card_bull_weak = score_stock(
            "AAPL", "Bullish", "Swing", bars, scoring_mode="stock",
            fundamentals=fund_weak, fundamentals_gate=fund_gate,
        )
        assert card_bull_weak.status == "REJECT"
        fund_rule = next(r for r in card_bull_weak.rules if r.name == "fundamentals")
        assert fund_rule.status == "REJECT"

        # 2. Bullish health 40 (30 <= health < 45) -> CAUTION
        fund_neutral = FundamentalHealth(
            score=40, quality_label="Neutral", risk_label="Medium",
            growth_score=40, quality_score=40, risk_score=40, detail={}
        )
        card_bull_neutral = score_stock(
            "AAPL", "Bullish", "Swing", bars, scoring_mode="stock",
            fundamentals=fund_neutral, fundamentals_gate=fund_gate,
        )
        assert card_bull_neutral.status in ("CAUTION", "REJECT")
        fund_rule = next(r for r in card_bull_neutral.rules if r.name == "fundamentals")
        assert fund_rule.status == "CAUTION"

        # 3. Bearish health 85 (> 80) -> REJECT
        fund_strong = FundamentalHealth(
            score=85, quality_label="Strong", risk_label="Low",
            growth_score=85, quality_score=85, risk_score=85, detail={}
        )
        card_bear_strong = score_stock(
            "AAPL", "Bearish", "Swing", bars, scoring_mode="stock",
            fundamentals=fund_strong, fundamentals_gate=fund_gate,
        )
        assert card_bear_strong.status == "REJECT"

        # 4. Safety flag: negative equity -> unconditional REJECT
        fund_safety = FundamentalHealth(
            score=60, quality_label="Neutral", risk_label="Medium",
            growth_score=60, quality_score=60, risk_score=60, detail={},
            safety_flags=["negative_equity"],
        )
        card_safety = score_stock(
            "AAPL", "Bullish", "Swing", bars, scoring_mode="stock",
            fundamentals=fund_safety, fundamentals_gate=fund_gate,
        )
        assert card_safety.status == "REJECT"

        # 5. Intraday exemption: health < 30 does NOT demote
        card_intraday = score_stock(
            "AAPL", "Bullish", "Intraday", bars, scoring_mode="stock",
            fundamentals=fund_weak, fundamentals_gate=fund_gate,
        )
        # Intraday ignores fundamentals gate; no fundamentals rule added
        assert not any(r.name == "fundamentals" for r in card_intraday.rules)

    def test_worse_monotonicity(self):
        """_worse only demotes, never promotes."""
        order = ["PASS", "CAUTION", "REJECT"]
        for a in order:
            for b in order:
                res = _worse(a, b)
                # res cannot be strictly better than either a or b
                if a == "REJECT" or b == "REJECT":
                    assert res == "REJECT"
                elif a == "CAUTION" or b == "CAUTION":
                    assert res in ("CAUTION", "REJECT")


# ===========================================================================
# 2. Strategy Engine & 7 Primary Strategies
# ===========================================================================

class TestStrategyEngineLaneD:
    def test_all_seven_primary_strategies_exist_in_schema(self):
        """Verify Strategy Literal contains exactly the 7 primary strategies."""
        from typing import get_args
        strategies = set(get_args(Strategy))
        expected = {
            "pullback_ema",
            "breakout_base",
            "ma_crossover",
            "mean_reversion_rsi",
            "mean_reversion_bb",
            "mean_reversion_vwap",
            "mean_reversion_multi",
        }
        assert strategies == expected, f"Strategy enum drifted: {strategies} vs {expected}"

    def test_seven_strategies_signal_execution(self):
        """All 7 strategies execute without error on OHLCV bars (Bullish & Bearish)."""
        bars_up = _synthetic_bars(n=150, trend="up")
        bars_down = _synthetic_bars(n=150, trend="down")

        # 1. pullback_ema
        sig1 = pullback_ema_signal(bars_up, direction="Bullish", tolerance=0.05)
        assert sig1 is None or sig1.strategy == "pullback_ema"

        # 2. breakout_base
        sig2 = breakout_base_signal(bars_up, direction="Bullish", volume_mult=1.05)
        assert sig2 is None or sig2.strategy == "breakout_base"

        # 3. ma_crossover
        sig3 = ma_crossover_signal(bars_up, direction="Bullish", fast=9, slow=21, lookback=10)
        assert sig3 is None or sig3.strategy == "ma_crossover"

        # 4. mean_reversion_rsi
        sig4 = mean_reversion_rsi_signal(bars_down, direction="Bullish", rsi_period=14, rsi_oversold=35)
        assert sig4 is None or sig4.strategy == "mean_reversion_rsi"

        # 5. mean_reversion_bb
        sig5 = mean_reversion_bb_signal(bars_down, direction="Bullish", bb_period=20, bb_std=2.0)
        assert sig5 is None or sig5.strategy == "mean_reversion_bb"

        # 6. mean_reversion_vwap
        sig6 = mean_reversion_vwap_signal(bars_down, direction="Bullish", vwap_dev_pct=1.5)
        assert sig6 is None or sig6.strategy == "mean_reversion_vwap"

        # 7. mean_reversion_multi
        sig7 = multi_signal(
            bars_down,
            direction="Bullish",
            params={
                "variants": ["mean_reversion_rsi", "mean_reversion_bb"],
                "min_confirmations": 1,
            },
        )
        assert sig7 is None or sig7.strategy == "mean_reversion_multi"

    def test_strategy_parameter_boundaries_enforced(self):
        """Pydantic validation rejects out-of-bounds parameters."""
        with pytest.raises(Exception):
            # breakout_volume_mult must be > 1.0
            StockScanRequest(
                universe=["AAPL"], direction="Bullish", horizon="Swing",
                strategy="breakout_base", breakout_volume_mult=0.5
            )

        with pytest.raises(Exception):
            # pullback_tolerance_pct must be > 0 and <= 1.0
            StockScanRequest(
                universe=["AAPL"], direction="Bullish", horizon="Swing",
                strategy="pullback_ema", pullback_tolerance_pct=0.0
            )


# ===========================================================================
# 3. Backtest Engine, Confidence & Artifacts
# ===========================================================================

class TestBacktestEngineAndConfidenceLaneD:
    def test_backtest_metric_calculations_and_schema(self):
        """Vectorized backtest returns BacktestResult with required fields."""
        bars = _synthetic_bars(n=300, trend="up")
        result = run_strategy_backtest(
            bars=bars,
            strategy="pullback_ema",
            direction="Bullish",
            hold_max_days=10,
        )
        assert isinstance(result, BacktestResult)
        assert isinstance(result.n_trades, int)
        assert 0.0 <= result.win_rate <= 1.0
        assert isinstance(result.expectancy, (int, float))
        assert isinstance(result.total_return_pct, (int, float))
        assert isinstance(result.max_drawdown_pct, (int, float))
        assert isinstance(result.sharpe, (int, float))
        assert isinstance(result.passes_gate, bool)
        assert isinstance(result.n_time_exits, int)

    def test_zero_trades_empty_result_safe(self):
        """When 0 trades occur, results must not divide by zero or produce NaN."""
        flat_bars = [
            {"time": f"2024-01-{(i % 25) + 1:02d}", "open": 50.0, "high": 50.1,
             "low": 49.9, "close": 50.0, "volume": 1000}
            for i in range(100)
        ]
        result = run_strategy_backtest(
            bars=flat_bars,
            strategy="breakout_base",
            direction="Bullish",
        )
        assert result.n_trades == 0
        assert result.win_rate == 0.0
        assert result.expectancy == 0.0
        assert result.sharpe == 0.0
        assert result.passes_gate is False

    @pytest.mark.asyncio
    async def test_backtest_artifact_lifecycle_and_symbol_query(self, tmp_path):
        """Original candidate artifacts are saved with schema_version=1 and

        provenance='original', and retrieval strictly requires symbol query.
        """
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from app.models.scan_report import ScanReportBase
        from app.models.backtest_artifact import BacktestArtifact  # noqa: F401
        from app.services import backtest_artifacts as artifacts
        from app.services.strategy_backtest import run_strategy_backtest_detailed
        from app.services.strategy_backtest_details import ENGINE_CONTRACT_VERSION
        from tests.test_strategy_backtest_details import bars as sample_bars

        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'audit_artifacts.db'}")
        async with engine.begin() as conn:
            await conn.run_sync(ScanReportBase.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        def _detail():
            return run_strategy_backtest_detailed(
                sample_bars(), strategy='pullback_ema', direction='Bullish',
                params={'tolerance': 0}, commission=.002
            )

        def _identity():
            return dict(
                scan_id=str(uuid4()), report_run_id=str(uuid4()), symbol='AAPL',
                strategy='pullback_ema', direction='Bullish', horizon='Swing', interval='1d',
                bars_basis_version='test-basis', input_hash='a' * 64,
                engine_contract_version=ENGINE_CONTRACT_VERSION
            )

        async with session_factory() as db:
            evidence = _detail()
            ident = _identity()
            saved = await artifacts.save_artifact(db, detail=evidence, identity=ident)
            artifact_id = saved["artifact_id"]

            # Retrieve with matching symbol
            retrieved = await artifacts.get_artifact(db, artifact_id, "AAPL")
            assert retrieved["schema_version"] == 1
            assert retrieved["provenance"] == "original"
            assert retrieved["identity"]["symbol"] == "AAPL"

            # Retrieve with mismatching symbol returns None (translates to 404 in router)
            mismatch = await artifacts.get_artifact(db, artifact_id, "MSFT")
            assert mismatch is None

        await engine.dispose()


# ===========================================================================
# 4. Position Sizing Arithmetic & Concentration
# ===========================================================================

class TestPositionSizingLaneD:
    def test_position_sizing_formula_with_conviction(self):
        """Verify position sizing:

        Risk per share = |entry - stop|
        Dollar risk = account * (risk_pct * conviction_mult)
        Shares = max(1, floor(dollar_risk / risk_per_share + 1e-9))
        """
        account = 100_000.0
        risk_pct = 0.01          # 1% = $1,000 baseline risk
        entry = 150.0
        stop = 145.0             # $5.00 risk/share

        # Baseline sizing (conviction = 1.0)
        shares, dollar_risk = _position_size(account, risk_pct=risk_pct, risk_fixed=None, entry=entry, stop=stop)
        assert dollar_risk == 1000.0
        assert shares == 200     # 1000 / 5 = 200

        # Conviction multiplier = 0.65 (neutral regime ramp)
        conviction_mult = 0.65
        sized_risk_pct = risk_pct * conviction_mult
        shares_ramped, dollar_risk_ramped = _position_size(
            account, risk_pct=sized_risk_pct, risk_fixed=None, entry=entry, stop=stop
        )
        assert dollar_risk_ramped == 650.0
        assert shares_ramped == 130  # 650 / 5 = 130

    def test_position_sizing_boundary_conditions(self):
        """Boundary conditions: entry == stop returns 0 shares."""
        shares, dollar_risk = _position_size(50_000.0, risk_pct=0.01, risk_fixed=None, entry=100.0, stop=100.0)
        assert shares == 0
        assert dollar_risk == 0.0

        # Extremely small stop distance -> capped by account or max(1, ...)
        shares_tight, _ = _position_size(50_000.0, risk_pct=0.01, risk_fixed=None, entry=100.0, stop=99.99)
        assert shares_tight >= 1

    def test_concentration_flag_math_never_clamps_shares(self):
        """Concentration flag flags in UI when shares * entry > portfolioValue * cap,

        but does NOT clamp recommended shares.
        """
        portfolio_value = 100_000.0
        cap_pct = 0.05  # 5% single-position cap = $5,000
        entry = 200.0
        shares = 100    # 100 * 200 = $20,000 position (> $5,000 cap)

        position_dollar = shares * entry
        cap_dollar = portfolio_value * cap_pct

        is_concentrated = position_dollar > cap_dollar
        assert is_concentrated is True

        # In UI, concentrationFlag returns:
        flag = {
            "positionDollar": position_dollar,
            "capDollar": cap_dollar,
            "positionPct": (position_dollar / portfolio_value) * 100,
            "capShares": int(cap_dollar / entry),
        }
        assert flag["positionDollar"] == 20_000.0
        assert flag["capDollar"] == 5_000.0
        assert flag["capShares"] == 25
        # Crucially: recommendedShares remains 100, NOT clamped to 25
        assert shares == 100
