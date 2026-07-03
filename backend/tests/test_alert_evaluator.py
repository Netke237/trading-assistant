# backend/tests/test_alert_evaluator.py
from __future__ import annotations
from datetime import datetime, timedelta
from app.services.alert_evaluator import (
    AlertRuleInput, PriceCondition, IndicatorCondition, StructureCondition,
    RegimeCondition, ConditionGroup, evaluate_rules, make_history_id,
    build_regime_snapshot,
)


def make_rule(name='Test', symbol='AAPL', interval='15min', conditions=None, logic='AND',
              enabled=True, cooldown_minutes=0, expiry_date=None, last_triggered_at=None):
    return AlertRuleInput(
        id='rule-1', name=name, symbol=symbol, interval=interval, enabled=enabled,
        group=ConditionGroup(logic=logic, conditions=conditions or []),
        cooldown_minutes=cooldown_minutes, expiry_date=expiry_date,
        created_at='2024-01-01T00:00:00Z', last_triggered_at=last_triggered_at,
    )


def make_candle(time='2024-01-02T09:30', o=100, h=105, l=99, c=103, v=1000):
    return {'time': time, 'open': o, 'high': h, 'low': l, 'close': c, 'volume': v}


class TestPriceCondition:
    def test_price_above_triggers(self):
        rule = make_rule(conditions=[PriceCondition(kind='price', operator='>', value=102)])
        candle = make_candle(c=103)
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now())
        assert len(results) == 1
        assert results[0]['trigger_values']['close'] == 103

    def test_price_below_triggers(self):
        rule = make_rule(conditions=[PriceCondition(kind='price', operator='<', value=104)])
        candle = make_candle(c=103)
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now())
        assert len(results) == 1

    def test_price_above_not_triggered(self):
        rule = make_rule(conditions=[PriceCondition(kind='price', operator='>', value=105)])
        candle = make_candle(c=103)
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now())
        assert len(results) == 0


class TestCrossesConditions:
    def test_crosses_above_triggers_only_on_crossing_candle(self):
        condition = IndicatorCondition(kind='indicator', indicator='RSI', operator='crosses_above', value=30)
        rule = make_rule(conditions=[condition])
        indicators = {'RSI': [
            {'time': '2024-01-02T09:00', 'value': 28},
            {'time': '2024-01-02T09:15', 'value': 28},
            {'time': '2024-01-02T09:30', 'value': 32},
        ]}
        candle1 = make_candle(time='2024-01-02T09:15')
        results1 = evaluate_rules([rule], candle1, [candle1], indicators, [], datetime.now())
        assert len(results1) == 0
        candle2 = make_candle(time='2024-01-02T09:30')
        results2 = evaluate_rules([rule], candle2, [candle2], indicators, [], datetime.now())
        assert len(results2) == 1

    def test_crosses_below_triggers(self):
        condition = IndicatorCondition(kind='indicator', indicator='RSI', operator='crosses_below', value=70)
        rule = make_rule(conditions=[condition])
        indicators = {'RSI': [
            {'time': '2024-01-02T09:15', 'value': 72},
            {'time': '2024-01-02T09:30', 'value': 68},
        ]}
        candle = make_candle(time='2024-01-02T09:30')
        results = evaluate_rules([rule], candle, [candle], indicators, [], datetime.now())
        assert len(results) == 1


class TestCooldown:
    def test_cooldown_blocks_retrigger(self):
        rule = make_rule(
            conditions=[PriceCondition(kind='price', operator='>', value=102)],
            cooldown_minutes=30,
            last_triggered_at=(datetime.now() - timedelta(minutes=10)).isoformat(),
        )
        candle = make_candle(c=103)
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now())
        assert len(results) == 0

    def test_cooldown_passed_allows_trigger(self):
        rule = make_rule(
            conditions=[PriceCondition(kind='price', operator='>', value=102)],
            cooldown_minutes=30,
            last_triggered_at=(datetime.now() - timedelta(minutes=40)).isoformat(),
        )
        candle = make_candle(c=103)
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now())
        assert len(results) == 1


class TestExpiry:
    def test_expired_rule_skipped(self):
        yesterday = (datetime.now() - timedelta(days=1)).date().isoformat()
        rule = make_rule(
            conditions=[PriceCondition(kind='price', operator='>', value=102)],
            expiry_date=yesterday,
        )
        candle = make_candle(c=103)
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now())
        assert len(results) == 0


class TestStructureCondition:
    def test_structure_condition_matches_signal(self):
        condition = StructureCondition(kind='structure', signal_kind='FVG', direction='bullish')
        rule = make_rule(conditions=[condition])
        candle = make_candle(time='2024-01-02T09:30')
        signals = [{'kind': 'FVG', 'direction': 'bullish', 'time_start': '2024-01-02T09:30',
                    'time_end': None, 'price_high': 105, 'price_low': 103,
                    'mitigated': False, 'confidence': 80, 'mtf_aligned': False}]
        results = evaluate_rules([rule], candle, [candle], {}, signals, datetime.now())
        assert len(results) == 1

    def test_structure_condition_no_match_wrong_kind(self):
        condition = StructureCondition(kind='structure', signal_kind='BOS', direction='bullish')
        rule = make_rule(conditions=[condition])
        candle = make_candle(time='2024-01-02T09:30')
        signals = [{'kind': 'FVG', 'direction': 'bullish', 'time_start': '2024-01-02T09:30'}]
        results = evaluate_rules([rule], candle, [candle], {}, signals, datetime.now())
        assert len(results) == 0


class TestLogic:
    def test_and_logic_all_must_pass(self):
        conditions = [
            PriceCondition(kind='price', operator='>', value=102),
            PriceCondition(kind='price', operator='<', value=110),
        ]
        candle = make_candle(c=105)
        rule = make_rule(conditions=conditions, logic='AND')
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now())
        assert len(results) == 1
        candle2 = make_candle(c=115)
        rule2 = make_rule(conditions=conditions, logic='AND')
        results2 = evaluate_rules([rule2], candle2, [candle2], {}, [], datetime.now())
        assert len(results2) == 0

    def test_or_logic_one_sufficient(self):
        conditions = [
            PriceCondition(kind='price', operator='>', value=102),
            PriceCondition(kind='price', operator='<', value=100),
        ]
        candle = make_candle(c=105)
        rule = make_rule(conditions=conditions, logic='OR')
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now())
        assert len(results) == 1


def test_enabled_flag_respected():
    rule = make_rule(conditions=[PriceCondition(kind='price', operator='>', value=102)], enabled=False)
    candle = make_candle(c=103)
    results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now())
    assert len(results) == 0


def test_make_history_id_generates_unique():
    id1 = make_history_id()
    id2 = make_history_id()
    assert id1 != id2
    assert len(id1) > 5


class TestRegimeCondition:
    def test_regime_condition_omm_state_match(self):
        condition = RegimeCondition(kind='regime', model='OMM', state='Bull')
        rule = make_rule(conditions=[condition])
        candle = make_candle()
        regime_by_model = {'OMM': {'state': 'Bull', 'conviction': 60}}
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now(), regime_by_model)
        assert len(results) == 1

    def test_regime_condition_wrong_state_no_match(self):
        condition = RegimeCondition(kind='regime', model='OMM', state='Bear')
        rule = make_rule(conditions=[condition])
        candle = make_candle()
        regime_by_model = {'OMM': {'state': 'Bull', 'conviction': 60}}
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now(), regime_by_model)
        assert len(results) == 0

    def test_regime_condition_model_selects_correct_snapshot(self):
        """model='HMM' selected but only OMM data available → condition not met,
        even though state/conviction would match if OMM data were used instead."""
        condition = RegimeCondition(kind='regime', model='HMM', state='Bull')
        rule = make_rule(conditions=[condition])
        candle = make_candle()
        regime_by_model = {'OMM': {'state': 'Bull', 'conviction': 90}}
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now(), regime_by_model)
        assert len(results) == 0

    def test_regime_condition_hmm_state_match(self):
        condition = RegimeCondition(kind='regime', model='HMM', state='Trending')
        rule = make_rule(conditions=[condition])
        candle = make_candle()
        regime_by_model = {'HMM': {'state': 'Trending', 'conviction': 82.0}}
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now(), regime_by_model)
        assert len(results) == 1

    def test_regime_condition_min_conviction_gate(self):
        condition = RegimeCondition(kind='regime', model='OMM', state='any', min_conviction=70)
        rule = make_rule(conditions=[condition])
        candle = make_candle()
        regime_by_model = {'OMM': {'state': 'Bull', 'conviction': 50}}
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now(), regime_by_model)
        assert len(results) == 0

    def test_regime_condition_no_regime_data_no_match(self):
        condition = RegimeCondition(kind='regime', model='OMM', state='Bull')
        rule = make_rule(conditions=[condition])
        candle = make_candle()
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now(), None)
        assert len(results) == 0

    def test_regime_condition_any_model_matches_whatever_is_available(self):
        condition = RegimeCondition(kind='regime', model='any', state='Trending')
        rule = make_rule(conditions=[condition])
        candle = make_candle()
        regime_by_model = {'HMM': {'state': 'Trending', 'conviction': 82.0}}
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now(), regime_by_model)
        assert len(results) == 1

    def test_regime_condition_bear_state_flips_conviction_sign(self):
        """OMM conviction is Bullish-framed (negative here means 'strongly favors Bear').
        A Bear-state condition must flip the sign so min_conviction=70 is satisfied by
        a regime that strongly favors Bear, not rejected by it."""
        condition = RegimeCondition(kind='regime', model='OMM', state='Bear', min_conviction=70)
        rule = make_rule(conditions=[condition])
        candle = make_candle()
        regime_by_model = {'OMM': {'state': 'Bear', 'conviction': -85}}
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now(), regime_by_model)
        assert len(results) == 1

    def test_regime_condition_bear_state_weak_bear_conviction_not_met(self):
        """Same flip, but the regime only weakly favors Bear — must not meet a 70 threshold."""
        condition = RegimeCondition(kind='regime', model='OMM', state='Bear', min_conviction=70)
        rule = make_rule(conditions=[condition])
        candle = make_candle()
        regime_by_model = {'OMM': {'state': 'Bear', 'conviction': -20}}
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now(), regime_by_model)
        assert len(results) == 0


class TestBuildRegimeSnapshot:
    def test_insufficient_bars_returns_empty_dict(self):
        candles = [{'close': 100.0 + i} for i in range(10)]
        assert build_regime_snapshot(candles) == {}

    def test_omm_populated_when_enough_bars(self):
        # Clear uptrend, 150 bars — enough for compute_omm's min_obs=100 requirement.
        candles = [{'close': 100.0 + i * 0.5} for i in range(150)]
        snapshot = build_regime_snapshot(candles)
        assert 'OMM' in snapshot
        assert snapshot['OMM']['state'] in ('Bull', 'Bear', 'Choppy')

    def test_hmm_absent_below_minimum_bars(self):
        # 50 bars is below both OMM's (100) and HMM's (200) minimums — 'HMM' must be absent
        # regardless of whether hmmlearn is installed in this environment.
        candles = [{'close': 100.0 + i} for i in range(50)]
        snapshot = build_regime_snapshot(candles)
        assert 'HMM' not in snapshot
