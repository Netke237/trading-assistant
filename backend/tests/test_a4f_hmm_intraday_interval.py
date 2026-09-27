"""A4f -- HMM_intraday composite watches need an intraday interval.

The regime-alert dialog saved '1D' for HMM_intraday while its Interval select
displayed '5m'; such a watch fetched ~38 daily bars (< regime_hmm.MIN_BARS) and
never fired. The backend now rejects that combination, and stored watches are
migrated to '5min' at load, reported (one WARNING, a persisted
`interval_migrated_from` marker). Plan:
docs/superpowers/plans/2026-09-25-a4f-hmm-intraday-interval-default-plan.md
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from app.data.market import is_intraday_interval
from app.services.strategy_watch_store import StrategyWatchStore


def _composite(wid: str, model: str, interval, **extra) -> dict:
    w = {
        "id": wid, "watch_type": "composite", "symbol": "AAPL", "direction": "Bullish",
        "trigger_def": {"primary": {"model": model}}, "enabled": False,
        "created_at": "2026-09-01T00:00:00+00:00",
        "last_state": {"phase": "idle", "last_event": "entry"},
    }
    if interval is not ...:
        w["interval"] = interval
    w.update(extra)
    return w


def _strategy(wid: str) -> dict:
    return {
        "id": wid, "watch_type": "strategy", "symbol": "MSFT", "strategy_key": "pullback_ema",
        "params_override": {}, "enabled": True, "trigger_def": None, "interval": "1D",
        "direction": "Bullish", "created_at": "2026-09-01T00:00:00+00:00",
        "last_state": {"phase": "idle"},
    }


def _write(path, watches):
    path.write_text(yaml.dump({"schedule": {"enabled": True}, "watches": watches}, sort_keys=False))


# ── B1a: the helper ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("iv", ["1m", "1min", "5m", "5min", "15m", "15min", "30m", "30min", "1h", "60m", "4h"])
def test_b1a_intraday_intervals(iv):
    assert is_intraday_interval(iv) is True


@pytest.mark.parametrize("iv", ["1D", "1W", "daily", "weekly", "", None, "foo", 5])
def test_b1a_non_intraday_intervals(iv):
    assert is_intraday_interval(iv) is False


# ── B1b: the store rejects HMM_intraday on a non-intraday interval ──────────

@pytest.mark.parametrize("iv", ["1D", "1W", "daily", "foo"])
def test_b1b_store_rejects_hmm_intraday_non_intraday(tmp_path, iv):
    store = StrategyWatchStore(path=tmp_path / "w.yaml")
    with pytest.raises(ValueError, match="HMM_intraday"):
        store.add_composite_watch("AAPL", {"primary": {"model": "HMM_intraday"}}, interval=iv)
    assert store.list_watches() == []
    assert not (tmp_path / "w.yaml").exists()


@pytest.mark.parametrize("iv", ["5m", "15m", "1h", "4h"])
def test_b1b_store_accepts_hmm_intraday_intraday(tmp_path, iv):
    store = StrategyWatchStore(path=tmp_path / "w.yaml")
    w = store.add_composite_watch("AAPL", {"primary": {"model": "HMM_intraday"}}, interval=iv)
    assert w["interval"] == {"5m": "5min", "15m": "15min"}.get(iv, iv)  # W2-INTERVAL


@pytest.mark.parametrize("model", ["OMM", "HMM_daily", "any"])
def test_b1b_store_keeps_daily_models_on_1d(tmp_path, model):
    store = StrategyWatchStore(path=tmp_path / "w.yaml")
    w = store.add_composite_watch("AAPL", {"primary": {"model": model}}, interval="1D")
    assert w["interval"] == "1D"


def test_b1b_store_tolerates_malformed_primary(tmp_path):
    store = StrategyWatchStore(path=tmp_path / "w.yaml")
    w = store.add_composite_watch("AAPL", {"primary": "HMM_intraday"}, interval="1D")
    assert w["interval"] == "1D"


# ── B1c: the router answers 400 and stores nothing ───────────────────────────

@pytest.mark.asyncio
async def test_b1c_router_rejects_hmm_intraday_1d(tmp_path):
    from app.main import app
    store = StrategyWatchStore(path=tmp_path / "w.yaml")
    with patch("app.routers.composite_watch.strategy_watch_store", store):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/composite-watches/", json={
                "symbol": "AAPL", "trigger_def": {"primary": {"model": "HMM_intraday"}},
                "direction": "Bullish", "interval": "1D",
            })
            ok = await client.post("/api/composite-watches/", json={
                "symbol": "AAPL", "trigger_def": {"primary": {"model": "HMM_intraday"}},
                "direction": "Bullish", "interval": "5m",
            })
    assert resp.status_code == 400
    assert "HMM_intraday" in resp.json()["detail"]
    assert ok.status_code == 201
    assert [w["interval"] for w in store.list_watches()] == ["5min"]


# ── B2: migration at load ────────────────────────────────────────────────────

def _mixed(tmp_path):
    path = tmp_path / "w.yaml"
    untouched = [
        _strategy("wch_s"),
        _composite("cwch_omm", "OMM", "1D"),
        _composite("cwch_hd", "HMM_daily", "1D"),
        _composite("cwch_ok", "HMM_intraday", "15min"),
    ]
    stale = [
        _composite("cwch_d", "HMM_intraday", "1D"),
        _composite("cwch_w", "HMM_intraday", "1W"),
        _composite("cwch_missing", "HMM_intraday", ...),
    ]
    _write(path, untouched + stale)
    return path, untouched, stale


def test_b2a_only_stale_hmm_intraday_watches_migrate(tmp_path):
    path, untouched, _ = _mixed(tmp_path)
    store = StrategyWatchStore(path=path)
    by_id = {w["id"]: w for w in store.list_watches()}
    for wid, old in (("cwch_d", "1D"), ("cwch_w", "1W"), ("cwch_missing", "1D")):
        assert by_id[wid]["interval"] == "5min"
        assert by_id[wid]["interval_migrated_from"] == old
        assert by_id[wid]["last_state"] == {"phase": "idle", "last_event": "entry"}
        assert by_id[wid]["enabled"] is False
    for w in untouched:
        assert by_id[w["id"]] == w
        assert "interval_migrated_from" not in by_id[w["id"]]


def test_b2b_migration_persisted_and_idempotent(tmp_path, caplog):
    path, _, _ = _mixed(tmp_path)
    StrategyWatchStore(path=path)
    on_disk = {w["id"]: w for w in yaml.safe_load(path.read_text())["watches"]}
    assert on_disk["cwch_d"]["interval"] == "5min"
    assert on_disk["cwch_d"]["interval_migrated_from"] == "1D"
    assert on_disk["cwch_ok"]["interval"] == "15min"

    before = path.read_text()
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="app.services.strategy_watch_store"), \
         patch.object(StrategyWatchStore, "save") as save:
        StrategyWatchStore(path=path)
    save.assert_not_called()
    assert not [r for r in caplog.records if "A4f" in r.getMessage()]
    assert path.read_text() == before


def test_b2c_one_warning_names_every_migrated_watch(tmp_path, caplog):
    path, _, stale = _mixed(tmp_path)
    with caplog.at_level(logging.WARNING, logger="app.services.strategy_watch_store"):
        StrategyWatchStore(path=path)
    a4f = [r for r in caplog.records if "A4f" in r.getMessage()]
    assert len(a4f) == 1
    assert a4f[0].levelno == logging.WARNING
    msg = a4f[0].getMessage()
    for w in stale:
        assert w["id"] in msg
    assert "cwch_ok" not in msg and "cwch_omm" not in msg


def test_b2c_no_log_no_save_when_nothing_to_migrate(tmp_path, caplog):
    path = tmp_path / "w.yaml"
    _write(path, [_strategy("wch_s"), _composite("cwch_ok", "HMM_intraday", "5min")])
    with caplog.at_level(logging.WARNING, logger="app.services.strategy_watch_store"), \
         patch.object(StrategyWatchStore, "save") as save:
        StrategyWatchStore(path=path)
    save.assert_not_called()
    assert not [r for r in caplog.records if "A4f" in r.getMessage()]


def test_b2e_save_failure_does_not_raise(tmp_path, caplog):
    """Plan round 1 F-1: load() runs at import time of the module-level store;
    a failed write must not stop the backend from booting."""
    path, _, _ = _mixed(tmp_path)
    with caplog.at_level(logging.ERROR, logger="app.services.strategy_watch_store"), \
         patch.object(StrategyWatchStore, "save", side_effect=OSError("read-only")):
        store = StrategyWatchStore(path=path)
    assert {w["id"]: w["interval"] for w in store.list_watches()}["cwch_d"] == "5min"
    errors = [r for r in caplog.records if r.levelno == logging.ERROR and "A4f" in r.getMessage()]
    assert len(errors) == 1 and "cwch_d" in errors[0].getMessage()


# ── B2d: end to end -- the evaluator fetches the migrated watch at 5m ───────

@pytest.mark.asyncio
async def test_b2d_evaluator_fetches_migrated_watch_at_5m(tmp_path):
    from app.services.strategy_watch_evaluator import evaluate_all
    path = tmp_path / "w.yaml"
    # strategy_key: evaluate_all's STRATEGY loop reads w["strategy_key"] on every
    # enabled watch, and add_composite_watch never sets it -- a KeyError that
    # aborts the whole run on main (pre-existing, logged against main, not A4f).
    # Set here so the test reaches the composite loop, as test_composite_sustain does.
    _write(path, [_composite("cwch_d", "HMM_intraday", "1D", enabled=True, strategy_key="composite")])
    store = StrategyWatchStore(path=path)
    daily = [{"time": f"2024-01-{1 + i % 28:02d}", "open": 1, "high": 1, "low": 1,
              "close": 1, "volume": 1} for i in range(30)]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars", new=AsyncMock(return_value=daily)), \
         patch("app.data.market.fetch_intraday_candles", return_value=[]) as fetch, \
         patch("app.services.composite_trigger_evaluator.evaluate_scheduled", return_value=False):
        await evaluate_all()
    fetch.assert_called_once()
    # FLIPPED by P4b (decision D5): a watch the A4f migration moved reads with the chart
    # spelling '5min', so it fetches the series a 5min rule reads.
    assert fetch.call_args.kwargs["interval"] == "5min"
