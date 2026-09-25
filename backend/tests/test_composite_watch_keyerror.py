"""One enabled composite watch used to make evaluate_all raise KeyError
'strategy_key', so NO watch of either kind was notified on that tick.

Plan: docs/superpowers/plans/2026-09-25-composite-watch-keyerror-plan.md

Every watch here is created through the REAL StrategyWatchStore
(add_watch / add_composite_watch), because the older composite tests passed a
hand-written dict carrying `"strategy_key": "composite"` -- a field the store
never writes -- and that is exactly how this defect stayed hidden.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import strategy_watch_evaluator as ev
from app.services.strategy_watch_store import StrategyWatchStore

_TRIGGER = {"primary": {"model": "OMM", "to_state": "Bull"}}


def _bars(close: float = 100.0, n: int = 260) -> list[dict]:
    return [{"time": f"2024-{1 + i // 28:02d}-{1 + i % 28:02d}",
             "open": close, "high": close + 1, "low": close - 1,
             "close": close, "volume": 1_000_000} for i in range(n)]


def _signal():
    sig = MagicMock()
    sig.direction = "Bullish"
    sig.entry_price = 100.0
    sig.stop_price = 95.0
    sig.target_price = 110.0
    sig.rr_ratio = 2.0
    return sig


@pytest.fixture
def store(tmp_path):
    return StrategyWatchStore(path=tmp_path / "strategy_watches.yaml")


def _patches(store, *, composite_fires: bool):
    return (
        patch.object(ev, "strategy_watch_store", store),
        patch.object(ev, "get_bars", new=AsyncMock(return_value=_bars())),
        patch.dict(ev._SIGNAL_FNS, {"pullback_ema": lambda bars, **kw: _signal()}),
        patch("app.services.composite_trigger_evaluator.evaluate_scheduled",
              return_value=composite_fires),
        patch("app.services.composite_trigger_evaluator.describe_match", return_value={}),
    )


async def _run(store, *, composite_fires=False, notify=False):
    p = _patches(store, composite_fires=composite_fires)
    with p[0], p[1], p[2], p[3], p[4]:
        if notify:
            return await ev.evaluate_and_notify()
        return await ev.evaluate_all()


def test_the_real_store_writes_no_strategy_key_on_a_composite(store):
    """The premise. If the store ever starts writing one, the fixtures in
    test_composite_sustain.py stop being unrealistic, and this can go."""
    w = store.add_composite_watch("AAPL", _TRIGGER)
    assert "strategy_key" not in w


@pytest.mark.asyncio
@pytest.mark.parametrize("composite_first", [True, False])
async def test_a_composite_watch_does_not_silence_a_strategy_watch(store, composite_first):
    if composite_first:
        store.add_composite_watch("AAPL", _TRIGGER)
        store.add_watch("MSFT", "pullback_ema")
    else:
        store.add_watch("MSFT", "pullback_ema")
        store.add_composite_watch("AAPL", _TRIGGER)

    events = await _run(store)

    assert [(e.symbol, e.strategy_key, e.event_type) for e in events] == [
        ("MSFT", "pullback_ema", "entry"),
    ]


@pytest.mark.asyncio
async def test_the_composite_loop_is_reached_and_fires(store):
    store.add_composite_watch("AAPL", _TRIGGER)
    store.add_watch("MSFT", "pullback_ema")

    events = await _run(store, composite_fires=True)

    assert sorted((e.symbol, e.strategy_key) for e in events) == [
        ("AAPL", "composite"), ("MSFT", "pullback_ema"),
    ]


@pytest.mark.asyncio
async def test_a_watch_missing_its_strategy_key_skips_only_itself(store):
    store.add_watch("MSFT", "pullback_ema")
    store.add_watch("NVDA", "pullback_ema")
    # A hand-edited / future-shaped entry: strategy-typed but keyless.
    del store._watches[0]["strategy_key"]

    events = await _run(store)

    assert [e.symbol for e in events] == ["NVDA"]


@pytest.mark.asyncio
async def test_evaluate_and_notify_sends_one_notification_per_event(store):
    store.add_composite_watch("AAPL", _TRIGGER)
    store.add_watch("MSFT", "pullback_ema")
    sent = AsyncMock(return_value=True)

    with patch.object(ev, "notify_enabled_channels", sent):
        events = await _run(store, composite_fires=True, notify=True)

    assert len(events) == 2
    assert sent.await_count == 2
