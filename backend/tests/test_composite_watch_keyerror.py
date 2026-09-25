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


# ── Round 1 F1: ONCE PER ENTRY (Kenneth, 2026-09-25) ────────────────────────
# evaluate_scheduled is level-triggered, so before this a composite re-sent the
# same "setup" alert on every scheduler run while its regime held.

def _composite_state(store):
    return next(w for w in store.list_watches()
                if w.get("watch_type") == "composite")["last_state"]


async def _run_fires(store, fires: bool):
    return [e for e in await _run(store, composite_fires=fires)
            if e.strategy_key == "composite"]


@pytest.mark.asyncio
async def test_a_held_condition_alerts_once_not_every_run(store):
    store.add_composite_watch("AAPL", _TRIGGER)

    assert len(await _run_fires(store, True)) == 1
    assert _composite_state(store)["phase"] == "armed"
    assert _composite_state(store)["last_event"] == "entry"
    assert await _run_fires(store, True) == []
    assert await _run_fires(store, True) == []


@pytest.mark.asyncio
async def test_true_false_true_alerts_twice(store):
    store.add_composite_watch("AAPL", _TRIGGER)

    assert len(await _run_fires(store, True)) == 1
    assert await _run_fires(store, False) == []
    assert _composite_state(store)["phase"] == "idle"
    # the display record of the last alert survives the re-arm
    assert _composite_state(store)["last_event"] == "entry"
    assert len(await _run_fires(store, True)) == 1


@pytest.mark.asyncio
async def test_sustained_fire_alerts_once_and_clears_the_pending_clock(store):
    from datetime import datetime, timedelta, timezone
    w = store.add_composite_watch("AAPL", {**_TRIGGER, "sustain_minutes": 5})
    past = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
    store.update_state(w["id"], {"pending_entry_since": past})

    assert len(await _run_fires(store, True)) == 1
    assert "pending_entry_since" not in _composite_state(store)
    assert await _run_fires(store, True) == []
    assert await _run_fires(store, True) == []


@pytest.mark.asyncio
async def test_an_evaluation_failure_leaves_the_state_untouched(store):
    store.add_composite_watch("AAPL", _TRIGGER)
    assert len(await _run_fires(store, True)) == 1
    before = dict(_composite_state(store))

    p = _patches(store, composite_fires=False)
    with p[0], p[1], p[2], p[4], patch(
        "app.services.composite_trigger_evaluator.evaluate_scheduled",
        side_effect=RuntimeError("feed down"),
    ):
        await ev.evaluate_all()

    assert _composite_state(store) == before  # still armed: an outage does not re-arm


@pytest.mark.asyncio
async def test_a_legacy_empty_state_reads_as_idle(store):
    w = store.add_composite_watch("AAPL", _TRIGGER)
    store._watches[0]["last_state"] = {}
    assert len(await _run_fires(store, True)) == 1


# ── Round 1 F2: add_watch's duplicate check hit the same KeyError ───────────

def test_adding_a_strategy_watch_beside_a_composite_works(store):
    store.add_composite_watch("MSFT", _TRIGGER)
    w = store.add_watch("MSFT", "pullback_ema")
    assert w["strategy_key"] == "pullback_ema"


def test_a_bulk_add_across_a_composite_adds_every_symbol(store):
    store.add_composite_watch("MSFT", _TRIGGER)
    added = store.add_watches_bulk(["AAPL", "MSFT", "NVDA"], "pullback_ema")
    assert [w["symbol"] for w in added] == ["AAPL", "MSFT", "NVDA"]


def test_the_duplicate_check_still_refuses_a_real_duplicate(store):
    store.add_composite_watch("MSFT", _TRIGGER)
    store.add_watch("MSFT", "pullback_ema")
    with pytest.raises(ValueError, match="already watched"):
        store.add_watch("MSFT", "pullback_ema")


# ── Round 2 F1: a feed/model failure is NO READING, not "condition false" ───
# evaluate_scheduled fails closed internally (no bars, model error, structure
# error, too few bars for a strategy confirmation). Read as False, a blip
# mid-regime re-armed an armed composite, and the next good reading re-sent the
# same entry. These drive the REAL evaluate_scheduled.

from types import SimpleNamespace

from app.services import composite_trigger_evaluator as cte

_OMM_BULL = SimpleNamespace(state="Bull", conviction_pct=80, p_stay=0.9)
_OMM_TRIGGER = {"primary": {"model": "OMM", "to_state": "Bull"}, "min_confirmations": 0}


async def _run_real(store, omm_results):
    """One evaluate_and_notify per entry in omm_results (None = model had no
    result), counting notifications actually sent."""
    sent = AsyncMock(return_value=True)
    with patch.object(ev, "strategy_watch_store", store), \
         patch.object(ev, "get_bars", new=AsyncMock(return_value=_bars())), \
         patch.object(ev, "notify_enabled_channels", sent), \
         patch("app.services.composite_trigger_evaluator.describe_match", return_value={}), \
         patch("app.services.regime_omm.compute_omm", side_effect=list(omm_results)):
        for _ in omm_results:
            await ev.evaluate_and_notify()
    return sent.await_count


@pytest.mark.asyncio
async def test_a_model_blip_mid_regime_does_not_resend_the_entry(store):
    store.add_composite_watch("AAPL", _OMM_TRIGGER)
    assert await _run_real(store, [_OMM_BULL, None, _OMM_BULL]) == 1
    assert _composite_state(store)["phase"] == "armed"


@pytest.mark.asyncio
async def test_a_blip_while_idle_neither_fires_nor_writes(store):
    store.add_composite_watch("AAPL", _OMM_TRIGGER)
    before = dict(_composite_state(store))
    assert await _run_real(store, [None]) == 0
    assert _composite_state(store) == before


@pytest.mark.asyncio
async def test_a_genuine_false_still_re_arms(store):
    store.add_composite_watch("AAPL", _OMM_TRIGGER)
    bear = SimpleNamespace(state="Bear", conviction_pct=80, p_stay=0.9)
    assert await _run_real(store, [_OMM_BULL, bear, _OMM_BULL]) == 2


def _call(td, *, bars_daily=None, bars_intraday=None, flag):
    return cte.evaluate_scheduled(
        "AAPL", td, _bars() if bars_daily is None else bars_daily,
        bars_intraday or [], unknown_as_none=flag,
    )


@pytest.mark.parametrize("flag,expected", [(True, None), (False, False)])
def test_each_unknown_path_is_none_with_the_flag_and_false_without(flag, expected):
    # no daily bars
    assert _call(_OMM_TRIGGER, bars_daily=[], flag=flag) is expected
    # OMM had no result
    with patch("app.services.regime_omm.compute_omm", return_value=None):
        assert _call(_OMM_TRIGGER, flag=flag) is expected
    # HMM_intraday with no intraday bars
    assert _call({"primary": {"model": "HMM_intraday"}, "min_confirmations": 0},
                 flag=flag) is expected
    # HMM model raised
    with patch("app.services.regime_hmm.compute_intraday_hmm", side_effect=RuntimeError("x")):
        assert _call({"primary": {"model": "HMM_daily"}, "min_confirmations": 0},
                     flag=flag) is expected
    # structure detection raised, confirmations required
    with patch("app.services.regime_omm.compute_omm", return_value=_OMM_BULL), \
         patch("app.services.market_structure.compute_structure", side_effect=RuntimeError("x")):
        assert _call({**_OMM_TRIGGER, "min_confirmations": 1}, flag=flag) is expected
    # a listed strategy confirmation starved of bars
    with patch("app.services.regime_omm.compute_omm", return_value=_OMM_BULL):
        assert _call({**_OMM_TRIGGER, "strategy_confirmations": ["mean_reversion_vwap"]},
                     flag=flag) is expected


def test_a_met_strategy_minimum_is_true_even_with_another_strategy_starved():
    """The unknown only replaces a SHORTFALL: rsi firing meets min 1 even though
    vwap had no intraday bars -- True with or without the flag."""
    td = {**_OMM_TRIGGER, "strategy_confirmations": ["mean_reversion_rsi", "mean_reversion_vwap"],
          "min_strategy_confirmations": 1}
    with patch("app.services.regime_omm.compute_omm", return_value=_OMM_BULL), \
         patch.object(cte, "_check_strategy_signals", return_value=1):
        assert _call(td, flag=True) is True
        assert _call(td, flag=False) is True


def test_a_genuine_miss_is_false_with_the_flag():
    bear = SimpleNamespace(state="Bear", conviction_pct=80, p_stay=0.9)
    with patch("app.services.regime_omm.compute_omm", return_value=bear):
        assert _call(_OMM_TRIGGER, flag=True) is False
