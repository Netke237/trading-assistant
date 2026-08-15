# backend/tests/test_strategy_watch_evaluator.py
from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.strategy_watch_evaluator import WatchEvent, evaluate_all

# Telegram's HTML parse_mode only recognizes this tag allowlist -- anything else
# (h3/p/ul/li included) makes the Bot API reject the whole message with a 400
# that dispatch.py's error handling silently swallows into a log line.
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


def _bars(close: float, n: int = 260) -> list[dict]:
    return [{"time": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}",
             "open": close, "high": close + 1, "low": close - 1,
             "close": close, "volume": 1_000_000} for i in range(n)]


def _signal(direction="Bullish", entry=100.0, stop=95.0, target=110.0):
    sig = MagicMock()
    sig.strategy = "pullback_ema"
    sig.direction = direction
    sig.entry_price = entry
    sig.stop_price = stop
    sig.target_price = target
    sig.rr_ratio = 2.0
    return sig


def _watch(phase="idle", **state):
    base = {"phase": phase, "direction": None, "entry_price": None,
            "stop_price": None, "target_price": None, "last_event": None,
            "last_event_at": None}
    base.update(state)
    return {"id": "wch_1", "symbol": "AAPL", "strategy_key": "pullback_ema",
            "params_override": {}, "enabled": True, "last_state": base}


@pytest.mark.asyncio
async def test_idle_with_signal_emits_entry_and_arms():
    store = MagicMock()
    store.list_watches.return_value = [_watch("idle")]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: _signal()}):
        events = await evaluate_all()
    assert len(events) == 1
    assert events[0].event_type == "entry"
    store.update_state.assert_called_once()
    assert store.update_state.call_args[0][1]["phase"] == "armed"


@pytest.mark.asyncio
async def test_armed_below_stop_emits_exit_stop_and_resets():
    store = MagicMock()
    store.list_watches.return_value = [_watch("armed", direction="Bullish",
                                              entry_price=100.0, stop_price=95.0,
                                              target_price=110.0)]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(94.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: None}):
        events = await evaluate_all()
    assert events[0].event_type == "exit_stop"
    assert store.update_state.call_args[0][1]["phase"] == "idle"


@pytest.mark.asyncio
async def test_armed_above_target_emits_exit_target():
    store = MagicMock()
    store.list_watches.return_value = [_watch("armed", direction="Bullish",
                                              entry_price=100.0, stop_price=95.0,
                                              target_price=110.0)]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(111.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: None}):
        events = await evaluate_all()
    assert events[0].event_type == "exit_target"


@pytest.mark.asyncio
async def test_armed_holding_emits_nothing():
    store = MagicMock()
    store.list_watches.return_value = [_watch("armed", direction="Bullish",
                                              entry_price=100.0, stop_price=95.0,
                                              target_price=110.0)]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(102.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, direction, **k: _signal(direction) if direction == "Bullish" else None}):
        events = await evaluate_all()
    assert events == []
    store.update_state.assert_not_called()


@pytest.mark.asyncio
async def test_armed_opposite_direction_signal_fires_reversal():
    """The only way a reversal can be genuine: the OPPOSITE direction's signal
    fires while armed (not stop/target hit). Before this fix, the evaluator
    only ever computed the signal for the watch's own fixed direction, so
    signal.direction could never disagree with state['direction'] and this
    branch was dead code."""
    store = MagicMock()
    store.list_watches.return_value = [_watch("armed", direction="Bullish",
                                              entry_price=100.0, stop_price=95.0,
                                              target_price=110.0)]

    def fake_signal(bars, direction, **k):
        # Bullish primary signal: nothing new (price is holding, not re-triggering).
        # Bearish (opposite) signal: fires -- this is the reversal.
        if direction == "Bearish":
            return _signal(direction="Bearish", entry=102.0, stop=108.0, target=90.0)
        return None

    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(102.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": fake_signal}):
        events = await evaluate_all()

    assert len(events) == 1
    assert events[0].event_type == "reversal"
    assert events[0].direction == "Bearish"
    updated_state = store.update_state.call_args[0][1]
    assert updated_state["phase"] == "armed"
    assert updated_state["direction"] == "Bearish"


@pytest.mark.asyncio
async def test_armed_no_opposite_signal_emits_nothing():
    """Holding steady (no stop/target hit, no opposite-direction signal) must
    still emit nothing -- confirms the new opposite-direction check doesn't
    fire spuriously when there's genuinely no reversal."""
    store = MagicMock()
    store.list_watches.return_value = [_watch("armed", direction="Bullish",
                                              entry_price=100.0, stop_price=95.0,
                                              target_price=110.0)]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(102.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, direction, **k: None}):
        events = await evaluate_all()
    assert events == []
    store.update_state.assert_not_called()


@pytest.mark.asyncio
async def test_stop_hit_takes_priority_over_opposite_direction_signal():
    """If the stop is hit AND the opposite direction would also signal, the
    exit_stop transition must win -- reversal is only checked as the final
    elif, after both stop_hit and target_hit."""
    store = MagicMock()
    store.list_watches.return_value = [_watch("armed", direction="Bullish",
                                              entry_price=100.0, stop_price=95.0,
                                              target_price=110.0)]

    def fake_signal(bars, direction, **k):
        return _signal(direction="Bearish") if direction == "Bearish" else None

    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(94.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": fake_signal}):
        events = await evaluate_all()
    assert events[0].event_type == "exit_stop"


@pytest.mark.asyncio
async def test_get_bars_failure_skips_symbol():
    store = MagicMock()
    store.list_watches.return_value = [_watch("idle")]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, side_effect=RuntimeError("db down")), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: _signal()}):
        events = await evaluate_all()
    assert events == []
    store.update_state.assert_not_called()


@pytest.mark.asyncio
async def test_disabled_watch_skipped():
    store = MagicMock()
    w = _watch("idle")
    w["enabled"] = False
    store.list_watches.return_value = [w]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)) as gb, \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: _signal()}):
        events = await evaluate_all()
    assert events == []
    gb.assert_not_called()


from unittest.mock import patch as _patch

from app.services.strategy_watch_evaluator import evaluate_and_notify, _format_event


def test_format_event_builds_subject_and_bodies():
    ev = WatchEvent(
        watch_id="wch_1", symbol="AAPL", strategy_key="pullback_ema",
        event_type="entry", direction="Bullish", entry=100.0, stop=95.0,
        target=110.0, rr_ratio=2.0, close=100.0,
        reason="AAPL: pullback_ema buy setup — entry 100.0, stop 95.0, target 110.0 (R:R 2.0)",
    )
    subject, plain, html = _format_event(ev)
    assert "AAPL" in subject and "Long setup" in subject
    assert "100.0" in plain
    assert "<" in html  # html body has markup


def test_format_event_html_is_telegram_safe():
    # Regression test for a real shipped bug: this html body used <h3>/<p>/
    # <ul>/<li>, none of which Telegram's HTML parse_mode supports -- every
    # strategy-watch Telegram alert (entry/exit/reversal) silently failed to
    # send while the email version looked fine.
    ev = WatchEvent(
        watch_id="wch_1", symbol="AAPL", strategy_key="pullback_ema",
        event_type="entry", direction="Bullish", entry=100.0, stop=95.0,
        target=110.0, rr_ratio=2.0, close=100.0,
        reason="AAPL: Pullback EMA long setup — entry 100.0, stop 95.0, target 110.0 (reward-to-risk 2.0)",
    )
    _subject, _plain, html = _format_event(ev)
    _assert_telegram_safe_html(html)


def test_format_event_html_is_telegram_safe_for_exit_events():
    # exit_stop/exit_target events (a real path in evaluate_all()) always set
    # entry=None, rr_ratio=None -- the two conditional html fragments in
    # _format_event are omitted entirely rather than rendered empty. The
    # "everything present" entry-event case above doesn't exercise this at
    # all; confirm the omitted-fragment path is still well-formed and safe.
    ev = WatchEvent(
        watch_id="wch_1", symbol="AAPL", strategy_key="pullback_ema",
        event_type="exit_stop", direction="Bullish", entry=None, stop=95.0,
        target=None, rr_ratio=None, close=94.5,
        reason="AAPL: Pullback EMA stop hit at 94.5 (stop 95.0)",
    )
    _subject, plain, html = _format_event(ev)
    assert "Entry" not in plain and "Entry" not in html
    assert "Reward-to-risk" not in plain and "Reward-to-risk" not in html
    _assert_telegram_safe_html(html)


def test_format_event_uses_plain_strategy_label_and_reward_risk_wording():
    # Regression test for the plain-language rename: raw snake_case strategy
    # keys (and the old "R:R"/"Reward:Risk" jargon) must not leak into the
    # subject or bullet list -- both should show the human-readable label
    # everywhere, not just in the subject line.
    ev = WatchEvent(
        watch_id="wch_1", symbol="AAPL", strategy_key="pullback_ema",
        event_type="entry", direction="Bullish", entry=182.5, stop=178.0,
        target=191.0, rr_ratio=1.9, close=182.75,
        reason="AAPL: Pullback EMA long setup — entry 182.5, stop 178.0, "
               "target 191.0 (reward-to-risk 1.9)",
    )
    subject, plain, html = _format_event(ev)
    for text in (subject, plain, html):
        assert "pullback_ema" not in text
        assert "Pullback EMA" in text
        assert "R:R" not in text
    assert "Reward-to-risk ratio: 1.9" in plain
    assert "Reward-to-risk ratio: 1.9" in html


def _composite_watch(**overrides):
    base = {"id": "wch_comp_1", "symbol": "AAPL", "watch_type": "composite",
            "strategy_key": "composite", "direction": "Bullish", "enabled": True,
            "trigger_def": {"primary": {"model": "OMM", "to_state": "bull_trend"}}}
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_composite_watch_describe_match_failure_still_fires_with_fallback_reason():
    """describe_match/format_composite_reason failing must not suppress an
    already-confirmed composite alert — it should fall back to a generic
    reason string and still append the WatchEvent."""
    store = MagicMock()
    store.list_watches.return_value = [_composite_watch()]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)), \
         patch("app.services.composite_trigger_evaluator.evaluate_scheduled",
               return_value=True), \
         patch("app.services.composite_trigger_evaluator.describe_match",
               side_effect=RuntimeError("boom")):
        events = await evaluate_all()
    assert len(events) == 1
    assert events[0].watch_id == "wch_comp_1"
    assert events[0].strategy_key == "composite"
    assert events[0].reason  # some reason string, not empty
    assert "AAPL" in events[0].reason


@pytest.mark.asyncio
async def test_composite_watch_fetches_intraday_for_vwap_confirmation_even_when_model_not_hmm_intraday():
    """A composite watch whose primary.model is NOT 'HMM_intraday' but whose
    strategy_confirmations include 'mean_reversion_vwap' must still fetch intraday
    bars — otherwise the scheduled path can never confirm VWAP (it always gets
    bars_intraday=[]), while the WS path potentially can, breaking parity between
    the two paths."""
    store = MagicMock()
    watch = _composite_watch(trigger_def={
        "primary": {"model": "any"},
        "strategy_confirmations": ["mean_reversion_vwap"],
        "min_strategy_confirmations": 1,
    })
    store.list_watches.return_value = [watch]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)), \
         patch("app.data.market.fetch_intraday_candles",
               return_value=_bars(100.0, n=120)) as fetch_intraday, \
         patch("app.services.composite_trigger_evaluator.evaluate_scheduled",
               return_value=True), \
         patch("app.services.composite_trigger_evaluator.describe_match",
               return_value={"structure_matched": [], "strategy_matched": []}):
        await evaluate_all()
    fetch_intraday.assert_called_once()


@pytest.mark.asyncio
async def test_evaluate_and_notify_dispatches_per_event():
    ev = WatchEvent(
        watch_id="wch_1", symbol="AAPL", strategy_key="pullback_ema",
        event_type="entry", direction="Bullish", entry=100.0, stop=95.0,
        target=110.0, rr_ratio=2.0, close=100.0, reason="x",
    )
    with _patch("app.services.strategy_watch_evaluator.evaluate_all",
                new_callable=AsyncMock, return_value=[ev]), \
         _patch("app.services.strategy_watch_evaluator.notify_enabled_channels") as notify:
        result = await evaluate_and_notify()
    assert result == [ev]
    notify.assert_called_once()


@pytest.mark.asyncio
async def test_sustain_delays_entry_until_window_elapses():
    store = MagicMock()
    store.list_watches.return_value = [_watch("idle")]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: _signal()}):
        events = await evaluate_all(sustain_minutes=5)
    assert events == []
    store.update_state.assert_called_once()
    assert "pending_entry_since" in store.update_state.call_args[0][1]


@pytest.mark.asyncio
async def test_sustain_fires_entry_once_window_elapsed():
    from datetime import datetime, timedelta, timezone
    past = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
    store = MagicMock()
    store.list_watches.return_value = [_watch("idle", pending_entry_since=past)]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: _signal()}):
        events = await evaluate_all(sustain_minutes=5)
    assert len(events) == 1
    assert events[0].event_type == "entry"


@pytest.mark.asyncio
async def test_sustain_clock_resets_when_signal_disappears():
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    store = MagicMock()
    store.list_watches.return_value = [_watch("idle", pending_entry_since=now_iso)]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: None}):
        events = await evaluate_all(sustain_minutes=5)
    assert events == []
    assert "pending_entry_since" not in store.update_state.call_args[0][1]


@pytest.mark.asyncio
async def test_sustain_still_pending_does_not_recall_update_state():
    from datetime import datetime, timedelta, timezone
    recent = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    store = MagicMock()
    store.list_watches.return_value = [_watch("idle", pending_entry_since=recent)]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: _signal()}):
        events = await evaluate_all(sustain_minutes=5)
    assert events == []
    store.update_state.assert_not_called()


@pytest.mark.asyncio
async def test_zero_sustain_minutes_fires_instantly_as_before():
    store = MagicMock()
    store.list_watches.return_value = [_watch("idle")]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: _signal()}):
        events = await evaluate_all()  # sustain_minutes defaults to 0
    assert len(events) == 1


@pytest.mark.asyncio
async def test_regular_watch_corrupted_pending_since_does_not_raise_or_fire():
    """A corrupted pending_entry_since on a REGULAR (non-composite) watch must
    restart the clock and suppress the fire, not raise -- an unhandled
    ValueError here would abort evaluate_all() for every remaining watch in
    the same tick, not just this one. Regression test mirroring the composite
    path's existing fail-open fix, applied to the regular-watch idle-phase
    sustain path."""
    store = MagicMock()
    store.list_watches.return_value = [_watch("idle", pending_entry_since="not-a-valid-timestamp")]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars(100.0)), \
         patch.dict("app.services.strategy_watch_evaluator._SIGNAL_FNS",
                    {"pullback_ema": lambda bars, **k: _signal()}):
        events = await evaluate_all(sustain_minutes=5)
    assert events == []
    store.update_state.assert_called_once()
    assert "pending_entry_since" in store.update_state.call_args[0][1]
