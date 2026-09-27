"""P3c item 1: the options scan drops an Intraday name with no 15-min regime bars.

Decision P3A-INTRADAY-REFUSAL-MATCHES-FIRE-2026-09-25. The auto-trader's fire
refuses a name whose 15-min regime fetch raised or came back empty whenever it
measures (YAML regime_gate enabled, or regime sizing on). The options scan used
to keep such a name with the regime unmeasured, so it could propose what the
fire would refuse. It now drops it on the same condition, with the stock scan's
helper (called, not copied), BEFORE the pre-screen and the chain fetch.
"""
from __future__ import annotations

import copy
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routers import scan, stock_scan
from app.schemas import RejectedCandidate
from app.services.config_loader import load_scoring_cfg
from tests.test_a4_intraday_regime_bars import DAILY, INTRADAY, _sem


def _cfg(*, gate: bool = True, sizing: bool | str = True) -> dict:
    cfg = copy.deepcopy(load_scoring_cfg())
    cfg["regime_gate"]["enabled"] = gate
    if sizing == "malformed":
        cfg["regime_sizing"] = {"enabled": True, "floor": "not-a-number"}
    else:
        cfg["regime_sizing"]["enabled"] = sizing
    return cfg


async def _run(horizon: str, *, intraday, cfg: dict | None = None):
    """Drive `_process_symbol`. The pre-screen card PASSES, so a name that is
    not dropped reaches the chain fetch (stubbed empty -> "no option chain")."""
    fetch = MagicMock(
        side_effect=intraday if isinstance(intraday, Exception) else None,
        return_value=None if isinstance(intraday, Exception) else intraday,
    )
    chain = AsyncMock(return_value=[])
    with ExitStack() as st:
        st.enter_context(patch("app.routers.scan.fetch_candles_async"))
        st.enter_context(patch("app.routers.scan.fetch_price_async", new_callable=AsyncMock, return_value=181.0))
        st.enter_context(patch("app.routers.scan.fetch_company_name_async", new_callable=AsyncMock, return_value="X"))
        st.enter_context(patch("app.routers.scan.fetch_fundamentals_calendar", new_callable=AsyncMock, return_value={}))
        st.enter_context(patch("app.routers.scan.fetch_calendar_dates_async", new_callable=AsyncMock, return_value=(None, None)))
        st.enter_context(patch("app.routers.scan.fetch_intraday_candles", fetch))
        st.enter_context(patch("app.routers.scan._compute_omm", MagicMock(return_value=None)))
        st.enter_context(patch("app.routers.scan._compute_dhmm", MagicMock(return_value=None)))
        st.enter_context(patch("app.routers.scan.fetch_option_chain_async", chain))
        st.enter_context(patch("app.routers.scan.log_event"))
        if cfg is not None:
            st.enter_context(patch("app.routers.scan._load_scoring_cfg", return_value=cfg))
        score = st.enter_context(patch("app.routers.scan.score_stock"))
        score.return_value = MagicMock(status="PASS", score=80, rules=[], components={})
        result = await scan._process_symbol(
            symbol="AAPL", direction="Bullish", horizon=horizon, client=AsyncMock(),
            sem=_sem(), scan_id="p3c1", bars_map={"AAPL": DAILY},
        )
    return result, chain, score


def _is_regime_drop(result) -> bool:
    return isinstance(result, RejectedCandidate) and result.reason.startswith("regime data unavailable:")


@pytest.mark.asyncio
async def test_fetch_raises_with_gate_enabled_drops_before_the_chain_fetch():
    result, chain, score = await _run("Intraday", intraday=RuntimeError("tradier down"), cfg=_cfg())
    assert _is_regime_drop(result)
    assert "fetch failed" in result.reason and "tradier down" in result.reason
    chain.assert_not_awaited()
    score.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_returns_empty_with_gate_enabled_drops_without_fetch_failed_suffix():
    result, chain, _ = await _run("Intraday", intraday=[], cfg=_cfg())
    assert _is_regime_drop(result)
    assert "fetch failed" not in result.reason
    chain.assert_not_awaited()


@pytest.mark.asyncio
async def test_gate_and_sizing_both_off_keeps_the_name():
    result, chain, _ = await _run("Intraday", intraday=RuntimeError("down"),
                                  cfg=_cfg(gate=False, sizing=False))
    assert not _is_regime_drop(result)
    chain.assert_awaited_once()


@pytest.mark.asyncio
async def test_gate_off_with_malformed_sizing_block_fails_closed():
    result, chain, _ = await _run("Intraday", intraday=[], cfg=_cfg(gate=False, sizing="malformed"))
    assert _is_regime_drop(result)
    chain.assert_not_awaited()


@pytest.mark.asyncio
async def test_short_series_is_not_dropped_by_this_rule():
    result, chain, score = await _run("Intraday", intraday=INTRADAY[:5], cfg=_cfg())
    assert not _is_regime_drop(result)
    chain.assert_awaited_once()
    assert score.call_args.kwargs["regime_signal"] is None


@pytest.mark.asyncio
async def test_swing_ignores_a_failing_intraday_fetch():
    result, chain, _ = await _run("Swing", intraday=RuntimeError("down"), cfg=_cfg())
    assert not _is_regime_drop(result)
    chain.assert_awaited_once()


def test_anti_drift_the_helper_is_the_stock_scans():
    assert scan._regime_data_drop is stock_scan._regime_data_drop
    assert scan._NO_REGIME_FILTER.regime_filter is False
