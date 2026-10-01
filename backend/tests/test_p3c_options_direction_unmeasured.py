"""P3c item 2: the options direction gate removes an UNMEASURED trend.

Decision P3C-UNMEASURED-TREND-NO-SCHEMA-FIELD-2026-09-25. The options gate used
to run only after `gather`, on `stockBreakdown.trend` -- an int, so a trend
rule with nothing to measure (placeholder 0/50) or no trend rule at all was
judged as if it were a reading. `_process_symbol` now removes it as
`direction_conviction_unmeasured:` on the PRE-SCREEN card, with the stock
scan's helper (called, not copied), before the chain fetch. The options scan
also fetches the relative_strength benchmark once per scan, as the stock scan
does, so that method's trend can be measured at all.
"""
from __future__ import annotations

import logging
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routers import scan, stock_scan
from app.schemas import RejectedCandidate
from app.scoring.stock_scorer import RuleResult, StockScoreCard
from tests.test_a4_intraday_regime_bars import DAILY, INTRADAY, _sem
from tests.test_scan_direction_funnel import _card, _run as _funnel_run
from tests.test_scan_endpoint import (
    _MOCK_CANDLES, _enter_mock_patches, _no_db_leak, _rr_test_chain,
)

_UNMEASURED = "direction_conviction_unmeasured:"


def _score_card(rules: list[RuleResult]) -> StockScoreCard:
    return StockScoreCard(symbol="AAPL", direction="Bullish", horizon="Swing",
                          score=80, status="PASS", rules=rules)


async def _run(horizon: str, rules: list[RuleResult], *, min_trend: float | None):
    """Drive `_process_symbol` with a PASSING pre-screen card carrying `rules`.
    A name the new check keeps reaches the chain fetch (stubbed empty ->
    "no option chain")."""
    chain = AsyncMock(return_value=[])
    with ExitStack() as st:
        st.enter_context(patch("app.routers.scan.fetch_candles_async"))
        st.enter_context(patch("app.routers.scan.fetch_price_async", new_callable=AsyncMock, return_value=181.0))
        st.enter_context(patch("app.routers.scan.fetch_company_name_async", new_callable=AsyncMock, return_value="X"))
        st.enter_context(patch("app.routers.scan.fetch_fundamentals_calendar", new_callable=AsyncMock, return_value={}))
        st.enter_context(patch("app.routers.scan.fetch_calendar_dates_async", new_callable=AsyncMock, return_value=(None, None)))
        # Completed 15-min bars, so item 1's regime-data drop cannot fire first
        # on an Intraday run, and no live call is made.
        st.enter_context(patch("app.routers.scan.fetch_intraday_candles", MagicMock(return_value=INTRADAY)))
        st.enter_context(patch("app.routers.scan._compute_omm", MagicMock(return_value=None)))
        st.enter_context(patch("app.routers.scan._compute_dhmm", MagicMock(return_value=None)))
        st.enter_context(patch("app.routers.scan.fetch_option_chain_async", chain))
        st.enter_context(patch("app.routers.scan.log_event"))
        st.enter_context(patch("app.routers.scan.score_stock", MagicMock(return_value=_score_card(rules))))
        result = await scan._process_symbol(
            symbol="AAPL", direction="Bullish", horizon=horizon, client=AsyncMock(),
            sem=_sem(), scan_id="p3c2", bars_map={"AAPL": DAILY},
            direction_min_trend=min_trend,
        )
    return result, chain


def _is_unmeasured(result) -> bool:
    return isinstance(result, RejectedCandidate) and result.reason.startswith(_UNMEASURED)


@pytest.mark.asyncio
async def test_unmeasured_trend_is_removed_before_the_chain_fetch():
    result, chain = await _run("Swing", [RuleResult("trend", "CAUTION", 50, {}, measured=False)],
                               min_trend=40)
    assert _is_unmeasured(result)
    assert result.reason == f"{_UNMEASURED} no trend measurement for Bullish Swing"
    chain.assert_not_awaited()


@pytest.mark.asyncio
async def test_measured_trend_at_50_passes_this_check():
    result, chain = await _run("Swing", [RuleResult("trend", "CAUTION", 50, {})], min_trend=40)
    assert not _is_unmeasured(result)
    chain.assert_awaited_once()


@pytest.mark.asyncio
async def test_measured_trend_below_the_floor_is_left_to_the_post_gather_gate():
    """Only the UNMEASURED verdict acts here; this item does not move the
    measured floor."""
    result, chain = await _run("Swing", [RuleResult("trend", "REJECT", 10, {})], min_trend=40)
    assert not _is_unmeasured(result)
    assert not (isinstance(result, RejectedCandidate) and result.reason.startswith("direction_conviction"))
    chain.assert_awaited_once()


@pytest.mark.asyncio
async def test_card_with_no_trend_rule_is_removed_as_unmeasured():
    result, chain = await _run("Swing", [], min_trend=40)
    assert _is_unmeasured(result)
    chain.assert_not_awaited()


@pytest.mark.asyncio
async def test_intraday_is_exempt():
    result, chain = await _run("Intraday", [RuleResult("trend", "CAUTION", 50, {}, measured=False)],
                               min_trend=None)
    assert not _is_unmeasured(result)
    chain.assert_awaited_once()


# ── relative_strength: the benchmark is fetched once per scan ────────────────

def _bench(last_day: str) -> list[dict]:
    return [{"time": "2026-01-02", "close": 500.0}, {"time": last_day, "close": 505.0}]


def _rs_score_stock():
    """Measured trend when a benchmark reached score_stock, the relative-strength
    placeholder (unmeasured 50) when it did not -- as stock_scorer does."""
    def _score(*_a, benchmark_candles=None, **_kw):
        return _score_card([RuleResult("trend", "PASS" if benchmark_candles else "CAUTION",
                                       80 if benchmark_candles else 50, {},
                                       measured=benchmark_candles is not None)])
    return MagicMock(side_effect=_score)


def _post_rs(client, bench):
    fetch_quotes_patch, get_bars_patch = _no_db_leak()
    score = _rs_score_stock()
    with _enter_mock_patches(price=185.0, candles=_MOCK_CANDLES, chain=_rr_test_chain(),
                             company="Apple Inc."), \
         fetch_quotes_patch, get_bars_patch, \
         patch("app.routers.scan.score_stock", score), \
         patch("app.routers.scan._rs_benchmark_candles", bench):
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing",
            "overrides": {"trend_method": "relative_strength"},
        })
    assert r.status_code == 200, r.text
    return r.json(), score


def test_relative_strength_benchmark_reaches_both_score_stock_calls(client):
    bench = AsyncMock(return_value=_bench(_MOCK_CANDLES[-1]["time"]))
    body, score = _post_rs(client, bench)
    bench.assert_awaited_once()
    req = bench.await_args.args[0]
    assert req.horizon == "Swing" and req.overrides == {"trend_method": "relative_strength"}
    assert score.call_count == 2, "expected the pre-screen and the post-chain score"
    for call in score.call_args_list:
        assert call.kwargs["benchmark_candles"] is not None
    assert [c["symbol"] for c in body["candidates"]] == ["AAPL"]


def test_relative_strength_benchmark_fetch_none_removes_the_name_unmeasured(client):
    body, score = _post_rs(client, AsyncMock(return_value=None))
    assert body["candidates"] == []
    assert body["rejected"][0]["reason"].startswith(_UNMEASURED)
    assert score.call_count == 1
    assert body["pipeline"]["failed_direction_unmeasured"] == 1
    assert body["pipeline"]["failed_direction"] == 0


def test_relative_strength_benchmark_helper_raising_does_not_fail_the_scan(client, caplog):
    with caplog.at_level(logging.WARNING, logger=scan._log.name):
        body, _ = _post_rs(client, AsyncMock(side_effect=KeyError("trend")))
    assert body["rejected"][0]["reason"].startswith(_UNMEASURED)
    assert "rs_benchmark resolve failed" in caplog.text


def test_relative_strength_misaligned_benchmark_is_removed_and_counted(client, caplog):
    with caplog.at_level(logging.INFO, logger=scan._log.name):
        body, _ = _post_rs(client, AsyncMock(return_value=_bench("2025-12-31")))
    assert body["rejected"][0]["reason"].startswith(_UNMEASURED)
    assert "rs_benchmark: misaligned=1 of 1" in caplog.text


# ── Funnel and banner ────────────────────────────────────────────────────────

def _unmeasured(sym: str) -> RejectedCandidate:
    return RejectedCandidate(symbol=sym, reason=f"{_UNMEASURED} no trend measurement for Bullish Swing")


def test_funnel_counts_unmeasured_apart_from_measured_and_no_banner_when_one_survives(client):
    """open_questions[53]: an unmeasured name is removed before the chain fetch,
    so it has its own bucket rather than failed_direction (which the funnel
    places after chain and contracts). The floor applied travels with it
    (open_questions[27], options half)."""
    body = _funnel_run(client, {
        "AAA": _unmeasured("AAA"),
        "BBB": _card("BBB", 10, "Bullish"),    # measured, below the Swing floor
        "CCC": _card("CCC", 90, "Bullish"),    # kept
    }, direction="Bullish", horizon="Swing")
    p = body["pipeline"]
    assert p["failed_direction"] == 1
    assert p["failed_direction_unmeasured"] == 1
    assert p["direction_min_trend"] == scan.load_direction_conviction_min_trend("Bullish", "Swing")
    assert p["other_rejected"] == 0
    assert p["candidates"] == 1
    assert not body["direction_banner"]


def test_banner_is_the_stock_form_when_the_gate_removed_everything(client):
    body = _funnel_run(client, {
        "AAA": _unmeasured("AAA"),
        "BBB": _card("BBB", 10, "Bullish"),
    }, direction="Bullish", horizon="Swing")
    floor = scan.load_direction_conviction_min_trend("Bullish", "Swing")
    assert body["direction_banner"] == (
        "No bullish candidates survived. The direction-conviction gate "
        f"removed 2 of 2 (trend below {floor:g})."
    )
    assert "market structure" not in body["direction_banner"]


def test_all_unmeasured_scan_shows_the_banner(client):
    body = _funnel_run(client, {"AAA": _unmeasured("AAA"), "BBB": _unmeasured("BBB")},
                       direction="Bullish", horizon="Swing")
    assert body["pipeline"]["failed_direction_unmeasured"] == 2
    assert body["pipeline"]["failed_direction"] == 0
    assert "removed 2 of 2" in body["direction_banner"]


def test_banner_names_the_other_gates_when_they_removed_the_rest(client):
    body = _funnel_run(client, {
        "AAA": _unmeasured("AAA"),
        "BBB": RejectedCandidate(symbol="BBB", reason="no option chain"),
    }, direction="Bullish", horizon="Swing")
    assert "removed 1 of 2" in body["direction_banner"]
    assert body["direction_banner"].endswith(
        "; the rest were removed by other gates — see the pipeline.")


def test_anti_drift_the_helpers_are_the_stock_scans():
    assert scan._direction_conviction_drop is stock_scan._direction_conviction_drop
    assert scan._rs_benchmark_candles is stock_scan._rs_benchmark_candles
    assert scan._aligned_benchmark is stock_scan._aligned_benchmark


def test_exempt_horizon_reports_no_floor(client):
    """Intraday is exempt: the pipeline carries no floor, so the funnel cannot
    print a threshold the scan never applied."""
    body = _funnel_run(client, {"CCC": _card("CCC", 90, "Bullish")},
                       direction="Bullish", horizon="Intraday")
    assert body["pipeline"]["direction_min_trend"] is None
    assert body["pipeline"]["failed_direction_unmeasured"] == 0
