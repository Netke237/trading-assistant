# backend/tests/test_chart_alerts_notification_text.py
"""Coverage for the plain-language notification redesign: _condition_label()
and the checklist it builds in alert_evaluator.py, and the checklist-driven
branch of chart_alerts.py's _build_notification_text() (including the
composite-rule checklist path).
"""
from __future__ import annotations

import re
from datetime import datetime

from app.services.alert_evaluator import (
    PriceCondition, IndicatorCondition, StructureCondition, RegimeCondition,
    ConditionGroup, AlertRuleInput, evaluate_rules, _condition_label,
)
from app.routers.chart_alerts import (
    _build_notification_text, _interval_label, _composite_checklist,
    _composite_need_suffix,
)

# Telegram's HTML parse_mode only recognizes this tag allowlist -- anything else
# (including <br> or any block tag) makes the Bot API reject the whole message
# with a 400 that dispatch.py's error handling silently swallows into a log
# line. See https://core.telegram.org/bots/api#html-style.
_TELEGRAM_ALLOWED_TAGS = {
    'b', 'strong', 'i', 'em', 'u', 'ins', 's', 'strike', 'del',
    'span', 'a', 'code', 'pre', 'blockquote', 'tg-spoiler', 'tg-emoji',
}


def _assert_telegram_safe_html(html: str) -> None:
    for tag in re.findall(r'<\s*/?\s*([a-zA-Z0-9-]+)', html):
        assert tag.lower() in _TELEGRAM_ALLOWED_TAGS, (
            f'<{tag}> is not in Telegram\'s HTML parse_mode allowlist -- '
            f'sending this will make the Bot API reject the whole message'
        )


class TestConditionLabel:
    def test_price_includes_live_value_when_available(self):
        c = PriceCondition(kind='price', operator='>', value=119)
        assert _condition_label(c, {'close': 128.68}) == 'Price above 119 (was 128.68)'

    def test_price_omits_value_when_not_available(self):
        c = PriceCondition(kind='price', operator='>', value=119)
        assert _condition_label(c) == 'Price above 119'

    def test_indicator_includes_live_reading(self):
        c = IndicatorCondition(kind='indicator', indicator='RSI(14)', operator='>', value=70)
        assert _condition_label(c, {'RSI(14)': 62.4}) == 'RSI(14) above 70 (was 62.40)'

    def test_regime_distinguishes_model_and_conviction(self):
        omm = RegimeCondition(kind='regime', model='OMM', state='Bull')
        hmm = RegimeCondition(kind='regime', model='HMM', state='Bull')
        assert _condition_label(omm) == 'Trend regime: Bull'
        # Different model must not render identically to the OMM condition --
        # that would recreate the exact "two conditions look like duplicates"
        # ambiguity that motivated this whole redesign.
        assert _condition_label(hmm) == 'Trend regime: Bull (HMM model)'
        assert _condition_label(omm) != _condition_label(hmm)

    def test_regime_includes_min_conviction(self):
        c = RegimeCondition(kind='regime', model='OMM', state='Bull', min_conviction=60)
        assert _condition_label(c) == 'Trend regime: Bull, conviction ≥60%'

    def test_regime_any_state_is_readable(self):
        c = RegimeCondition(kind='regime', model='OMM', state='any')
        assert _condition_label(c) == 'Trend regime: any state'

    def test_structure_distinguishes_direction(self):
        bull = StructureCondition(kind='structure', signal_kind='BOS', direction='Bullish')
        bear = StructureCondition(kind='structure', signal_kind='BOS', direction='Bearish')
        assert _condition_label(bull) != _condition_label(bear)
        assert 'Bullish' in _condition_label(bull)
        assert 'Bearish' in _condition_label(bear)

    def test_structure_unmapped_signal_kind_still_readable(self):
        c = StructureCondition(kind='structure', signal_kind='OrderBlock')
        label = _condition_label(c)
        assert 'OrderBlock' in label
        assert label != 'OrderBlock detected'  # not the old bare fallback

    def test_regime_null_model_and_state_do_not_leak_literal_none(self):
        # _deserialize_rule()'s c.get('model', 'OMM') only applies the default
        # when the key is ABSENT, not when it's an explicit JSON null -- a raw
        # POST /rules call can send {"model": null, "state": null} and it
        # reaches here as None, not the dataclass default. Must not render the
        # literal word "None" into user-facing notification text.
        c = RegimeCondition(kind='regime', model=None, state=None)
        label = _condition_label(c)
        assert 'None' not in label
        assert label == 'Trend regime: any state'

    def test_structure_null_signal_kind_does_not_leak_literal_none(self):
        c = StructureCondition(kind='structure', signal_kind=None)
        label = _condition_label(c)
        assert 'None' not in label

    def test_price_null_operator_or_value_does_not_leak_literal_none(self):
        # Same reachability as the regime/structure guards: ConditionGroupIn.
        # conditions is an untyped list with no per-item schema, so a raw
        # POST /rules call can send operator/value as null.
        assert 'None' not in _condition_label(PriceCondition(kind='price', operator=None, value=119))
        assert 'None' not in _condition_label(PriceCondition(kind='price', operator='>', value=None))

    def test_indicator_null_fields_do_not_leak_literal_none(self):
        assert 'None' not in _condition_label(
            IndicatorCondition(kind='indicator', indicator=None, operator='>', value=70)
        )
        assert 'None' not in _condition_label(
            IndicatorCondition(kind='indicator', indicator='RSI(14)', operator=None, value=70)
        )


def _make_rule(conditions, logic='N_OF_M', threshold=None):
    return AlertRuleInput(
        id='rule-1', name='Test rule', symbol='DG', interval='1D', enabled=True,
        group=ConditionGroup(logic=logic, conditions=conditions, n_of_m_threshold=threshold),
        cooldown_minutes=0, expiry_date=None,
        created_at='2024-01-01T00:00:00Z', last_triggered_at=None,
    )


class TestEvaluateRulesChecklist:
    def test_checklist_pairs_correct_label_with_correct_match_result(self):
        rule = _make_rule([
            PriceCondition(kind='price', operator='>', value=119),
            StructureCondition(kind='structure', signal_kind='BOS'),
        ])
        candle = {'time': 't', 'open': 100, 'high': 130, 'low': 99, 'close': 128.68, 'volume': 1}
        results = evaluate_rules([rule], candle, [candle], {}, [], datetime.now())
        assert len(results) == 1
        checklist = results[0]['checklist']
        assert len(checklist) == 2
        assert checklist[0]['label'].startswith('Price above 119')
        assert checklist[0]['met'] is True
        assert checklist[1]['label'].startswith('Breakout structure')
        assert checklist[1]['met'] is False


class TestBuildNotificationTextChecklistBranch:
    def _entry(self, interval='1D', checklist=None, close=128.68):
        return {
            'symbol': 'DG', 'interval': interval, 'rule_id': 'rule-1',
            'triggered_at': '2026-07-30T16:46:32+00:00',
            'candle': {'close': close},
            'trigger_values': {}, 'reason': 'ignored in checklist branch',
            'checklist': checklist if checklist is not None else [
                {'label': 'Price above 119', 'met': True},
                {'label': 'Breakout structure (BOS)', 'met': False},
            ],
        }

    def test_falls_back_to_legacy_format_without_checklist(self):
        entry = self._entry(checklist=[])
        entry.pop('checklist')
        _subject, plain, _html = _build_notification_text(entry, 'DG Pre breakout')
        assert 'Symbol:' in plain and 'Interval:' in plain and 'Trigger:' in plain

    def test_intraday_intervals_render_as_plain_labels_not_raw_codes(self):
        # Regression test: _INTERVAL_LABELS previously keyed on '1H'/'4H' (never
        # produced by the app) instead of the real lowercase '1h'/'4h' values
        # from frontend Interval type, so these silently fell through to the
        # raw-code fallback ("1h chart") instead of "Hourly chart".
        assert _interval_label('1h') == 'Hourly chart'
        assert _interval_label('4h') == '4-hour chart'
        assert _interval_label('1D') == 'Daily chart'
        assert _interval_label('1min') == '1-minute chart'
        for interval in ('1min', '5min', '15min', '1h', '4h', '1D', '1W'):
            _subject, plain, _html = _build_notification_text(self._entry(interval=interval), 'R')
            assert 'chart' in plain

    def test_price_line_uses_candle_close(self):
        _subject, plain, _html = _build_notification_text(self._entry(close=128.68), 'DG Pre breakout')
        assert 'Price at trigger: $128.68' in plain

    def test_conditions_met_count_and_checkmarks(self):
        _subject, plain, _html = _build_notification_text(self._entry(), 'DG Pre breakout')
        assert 'Conditions met: 1 of 2' in plain
        assert '✓ Price above 119' in plain
        assert '✗ Breakout structure (BOS)' in plain

    def test_html_body_is_telegram_safe(self):
        # Regression test for a real shipped bug: the checklist branch's html
        # once used <br> for line breaks, which Telegram's HTML parse_mode
        # rejects outright -- every alert using this branch silently failed to
        # send over Telegram while looking fine in the email/plain body.
        _subject, _plain, html = _build_notification_text(self._entry(), 'DG Pre breakout')
        _assert_telegram_safe_html(html)

    def test_rule_name_with_angle_bracket_is_escaped_not_parsed_as_a_tag(self):
        # AlertRuleCreate.name has no format constraint, so a rule named e.g.
        # "RSI < 30 Reversal" would otherwise inject an unclosed '<' into the
        # Telegram HTML body and get the whole message rejected -- the same
        # silent-failure mode as the <br> bug, via user text instead of a
        # hardcoded tag. Also covers a checklist label containing '&'.
        entry = self._entry(checklist=[
            {'label': 'Price above 119 & rising', 'met': True},
        ])
        _subject, _plain, html = _build_notification_text(entry, 'RSI < 30 Reversal')
        assert '<b>RSI &lt; 30 Reversal</b>' in html
        assert '&amp; rising' in html
        _assert_telegram_safe_html(html)

    def test_legacy_fallback_html_is_also_escaped(self):
        entry = self._entry(checklist=[])
        entry.pop('checklist')
        entry['reason'] = 'Price < 100 & falling'
        _subject, _plain, html = _build_notification_text(entry, 'RSI < 30 Reversal')
        assert '&lt;' in html
        assert '&amp;' in html
        _assert_telegram_safe_html(html)

    def test_interval_value_is_escaped_in_checklist_branch(self):
        # _interval_label() falls back to f'{interval} chart' verbatim for any
        # value outside its known set -- and `interval` is unconstrained free
        # text at the API boundary (AlertRuleCreate.interval: str, no enum). A
        # crafted interval string reaching that fallback must not inject raw
        # markup into the html body; this was missed by the first escaping pass
        # (which covered rule_label/sym/reason/checklist labels but not the
        # value flowing through _interval_label()).
        entry = self._entry(interval='<script>x</script>')
        _subject, _plain, html = _build_notification_text(entry, 'R')
        assert '<script>' not in html
        _assert_telegram_safe_html(html)

    def test_n_of_m_without_stored_threshold_shows_only_needs_one(self):
        # Pins _build_notification_text()'s own rule_threshold=None fallback in
        # isolation from _deserialize_rule() (which, as of the N_OF_M threshold
        # fix, does populate a real threshold when one is stored -- see
        # test_n_of_m_threshold_persistence.py). This test still covers the
        # genuinely-legacy case: a rule saved before that fix has no threshold
        # in its stored rule_json at all, so _deserialize_rule() still passes
        # through None here, and this text must keep matching that reality.
        entry = self._entry(checklist=[
            {'label': 'A', 'met': True}, {'label': 'B', 'met': False}, {'label': 'C', 'met': False},
        ])
        _subject, plain, _html = _build_notification_text(
            entry, 'R', rule_logic='N_OF_M', rule_threshold=None,
        )
        assert '(only needs 1 to fire)' in plain

    def test_and_logic_shows_all_required(self):
        _subject, plain, _html = _build_notification_text(
            self._entry(), 'R', rule_logic='AND', rule_threshold=None,
        )
        assert '(all required)' in plain


class TestCompositeChecklist:
    def test_primary_always_met_confirmations_matched_by_name(self):
        td = {
            'primary': {'model': 'OMM', 'to_state': 'Bull'},
            'confirmations': [
                {'signal_kind': 'BOS', 'direction': 'Bullish'},
                {'signal_kind': 'FVG'},
            ],
            'strategy_confirmations': ['mean_reversion_vwap'],
        }
        detail = {'structure_matched': ['BOS'], 'strategy_matched': []}
        rows = _composite_checklist(td, detail)
        assert rows[0]['met'] is True
        assert rows[0]['label'].startswith('Trend regime: Bull')
        bos_row = next(r for r in rows if 'BOS' in r['label'])
        fvg_row = next(r for r in rows if 'FVG' in r['label'])
        strat_row = next(r for r in rows if 'mean_reversion_vwap' in r['label'])
        assert bos_row['met'] is True
        assert fvg_row['met'] is False
        assert strat_row['met'] is False

    def test_primary_any_state_renders_as_any_state(self):
        td = {'primary': {'model': 'OMM', 'to_state': None}, 'confirmations': []}
        rows = _composite_checklist(td, {'structure_matched': [], 'strategy_matched': []})
        assert rows[0]['label'] == 'Trend regime: any state'

    def test_duplicate_signal_kind_with_directions_is_flagged_not_silently_wrong(self):
        # Two confirmations share signal_kind='BOS' but differ by direction.
        # describe_match() only returns matched signal_kind NAMES, so it can't
        # tell which directional variant actually fired -- both rows would
        # otherwise render met=True even if only the bullish one fired. The
        # checklist must not claim more certainty than the underlying data has.
        td = {
            'primary': {'model': 'OMM', 'to_state': 'Bull'},
            'confirmations': [
                {'signal_kind': 'BOS', 'direction': 'Bullish'},
                {'signal_kind': 'BOS', 'direction': 'Bearish'},
            ],
            'strategy_confirmations': [],
        }
        detail = {'structure_matched': ['BOS'], 'strategy_matched': []}
        rows = _composite_checklist(td, detail)
        bos_rows = [r for r in rows if 'BOS' in r['label']]
        assert len(bos_rows) == 2
        for r in bos_rows:
            assert r['met'] is True  # can't disprove either, per the matched-name-only data
            assert 'direction not confirmed' in r['label']

    def test_single_confirmation_per_kind_is_not_flagged(self):
        td = {
            'primary': {'model': 'OMM', 'to_state': 'Bull'},
            'confirmations': [{'signal_kind': 'BOS', 'direction': 'Bullish'}],
            'strategy_confirmations': [],
        }
        detail = {'structure_matched': ['BOS'], 'strategy_matched': []}
        rows = _composite_checklist(td, detail)
        bos_row = next(r for r in rows if 'BOS' in r['label'])
        assert 'direction not confirmed' not in bos_row['label']

    def test_exact_duplicate_confirmation_same_direction_is_not_flagged(self):
        # Two BOS/Bullish confirmations are redundant, not ambiguous -- there's
        # no second directional variant to confuse them with, so the caveat
        # would be misleading noise here, not a real warning.
        td = {
            'primary': {'model': 'OMM', 'to_state': 'Bull'},
            'confirmations': [
                {'signal_kind': 'BOS', 'direction': 'Bullish'},
                {'signal_kind': 'BOS', 'direction': 'Bullish'},
            ],
            'strategy_confirmations': [],
        }
        detail = {'structure_matched': ['BOS'], 'strategy_matched': []}
        rows = _composite_checklist(td, detail)
        bos_rows = [r for r in rows if 'BOS' in r['label']]
        assert len(bos_rows) == 2
        for r in bos_rows:
            assert 'direction not confirmed' not in r['label']


class TestCompositeNeedSuffix:
    def test_blank_when_all_confirmations_required(self):
        td = {'confirmations': [{'signal_kind': 'BOS'}, {'signal_kind': 'FVG'}],
              'min_confirmations': 2}
        assert _composite_need_suffix(td) == ''

    def test_notes_structure_threshold_below_total(self):
        # Regression test: composite rules previously always showed a blank
        # suffix regardless of threshold, silently hiding cases like this one
        # (1 of 3 required) that standard N_OF_M rules do surface.
        td = {'confirmations': [{'signal_kind': 'BOS'}, {'signal_kind': 'FVG'}, {'signal_kind': 'CHoCH'}],
              'min_confirmations': 1}
        assert _composite_need_suffix(td) == ' (only needs 1 of 3 structure signals)'

    def test_notes_strategy_threshold_below_total(self):
        td = {'strategy_confirmations': ['mean_reversion_vwap', 'mean_reversion_rsi'],
              'min_strategy_confirmations': 1}
        assert _composite_need_suffix(td) == ' (only needs 1 of 2 strategy signals)'

    def test_notes_both_when_both_below_total(self):
        td = {
            'confirmations': [{'signal_kind': 'BOS'}, {'signal_kind': 'FVG'}],
            'min_confirmations': 1,
            'strategy_confirmations': ['mean_reversion_vwap', 'mean_reversion_rsi'],
            'min_strategy_confirmations': 1,
        }
        suffix = _composite_need_suffix(td)
        assert 'only needs 1 of 2 structure signals' in suffix
        assert 'only needs 1 of 2 strategy signals' in suffix

    def test_blank_when_no_confirmations_configured(self):
        assert _composite_need_suffix({}) == ''


import pytest
from httpx import AsyncClient, ASGITransport


async def _make_app():
    from fastapi import FastAPI
    from app.database import Base, get_db
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.models.alert import AlertRuleModel, AlertHistoryModel  # noqa: F401

    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_db():
        async with Session() as session:
            yield session

    from app.routers.chart_alerts import router as chart_alerts_router

    app = FastAPI()
    app.include_router(chart_alerts_router)
    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.mark.asyncio
async def test_post_history_with_checklist_uses_plain_language_layout(monkeypatch):
    """Proves the wiring all the way from POST /alerts/history's checklist
    field through to the dispatched notification text -- this is the endpoint
    chartAlertStore.ts's pushHistoryToAPI() calls when a chart tab evaluates
    rules locally via chartAlertEngine.ts. Without this, that path silently
    kept rendering the old Symbol:/Interval:/Trigger:/Values: layout forever,
    since _build_notification_text() only takes the plain-language branch when
    entry['checklist'] is present.
    """
    import app.routers.chart_alerts as chart_alerts_module

    captured = []
    monkeypatch.setattr(chart_alerts_module, '_dispatch', lambda channel, **kw: captured.append((channel, kw)))
    monkeypatch.setattr(
        chart_alerts_module, '_load_notification_config',
        lambda: {'telegram': {'enabled': True, 'bot_token': 'x', 'chat_id': 'y'}},
    )

    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        rule_resp = await client.post('/alerts/rules', json={
            'name': 'Client-side rule', 'symbol': 'AAPL', 'interval': '15min', 'enabled': True,
            'group': {'logic': 'AND', 'conditions': [{'kind': 'price', 'operator': '>', 'value': 100}]},
            'cooldown_minutes': 60, 'expiry_date': None,
        })
        rule_id = rule_resp.json()['id']

        hist_resp = await client.post('/alerts/history', json={
            'rule_id': rule_id, 'symbol': 'AAPL', 'interval': '15min',
            'triggered_at': '2026-07-30T12:00:00', 'candle': {'close': 190},
            'trigger_values': {'close': 190}, 'reason': 'Price > 100',
            'checklist': [{'label': 'Price above 100 (was 190.00)', 'met': True}],
        })
        assert hist_resp.status_code == 201

    assert len(captured) == 1
    _channel, kwargs = captured[0]
    assert 'Conditions met: 1 of 1' in kwargs['text']
    assert 'Price above 100 (was 190.00)' in kwargs['text']
    assert 'Trigger:' not in kwargs['text']
