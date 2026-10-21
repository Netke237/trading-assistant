"""INGEST-SKIP-EXCLUDED: the automatic ingestion universe skips `scope: scan` exclusions.

The nightly scheduler and `startup_catch_up()` build their symbol list with
`ingestion_universe()`; a manual `POST /api/data/ingest` still ingests exactly what it is given.
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, Mock

import pytest

from app.data import universe_exclusions, universe_presets
from app.data.universe_exclusions import Exclusion, ExclusionListError
from app.services import ingestion_job as job

EXCLUSIONS = {
    "XSCAN": Exclusion(symbol="XSCAN", scope="scan", reason="price feed ended"),
    "XEVID": Exclusion(symbol="XEVID", scope="evidence", reason="bar-basis jump"),
}


def _presets(monkeypatch, symbols: list[str]) -> None:
    by_key = {"SP500": symbols, "NDX100": [], "DOW30": []}
    monkeypatch.setattr(universe_presets, "expand_universe", lambda keys: by_key[keys[0]])


def _exclusions(monkeypatch, exclusions: dict[str, Exclusion]) -> None:
    monkeypatch.setattr(universe_exclusions, "load_exclusions", lambda *a, **k: dict(exclusions))


def test_scope_scan_symbol_is_removed(monkeypatch):
    _presets(monkeypatch, ["AAA", "XSCAN", "BBB"])
    _exclusions(monkeypatch, EXCLUSIONS)
    assert job.ingestion_universe() == ["SPY", "AAA", "BBB"]


def test_scope_evidence_symbol_is_kept(monkeypatch):
    _presets(monkeypatch, ["XSCAN", "XEVID"])
    _exclusions(monkeypatch, EXCLUSIONS)
    assert job.ingestion_universe() == ["SPY", "XEVID"]


def test_reference_kept_first_even_if_listed(monkeypatch):
    _presets(monkeypatch, ["XSCAN", "AAA", "SPY"])
    _exclusions(monkeypatch, {**EXCLUSIONS,
                              "SPY": Exclusion(symbol="SPY", scope="scan", reason="hypothetical")})
    assert job.ingestion_universe() == ["SPY", "AAA"]


def test_skip_count_logged_once(monkeypatch, caplog):
    _presets(monkeypatch, ["AAA", "XSCAN", "XEVID"])
    _exclusions(monkeypatch, EXCLUSIONS)
    with caplog.at_level(logging.INFO, logger=job.logger.name):
        job.ingestion_universe()
    skips = [r.getMessage() for r in caplog.records if "excluded symbols" in r.getMessage()]
    assert skips == ["ingestion: skipping 1 excluded symbols (scope: scan): XSCAN"]


@pytest.mark.parametrize("error", [ExclusionListError("bad yaml"), RuntimeError("boom")])
def test_unloadable_exclusion_list_fails_open(monkeypatch, caplog, error):
    _presets(monkeypatch, ["AAA", "XSCAN", "XEVID"])

    def broken(*a, **k):
        raise error

    monkeypatch.setattr(universe_exclusions, "load_exclusions", broken)
    with caplog.at_level(logging.WARNING, logger=job.logger.name):
        assert job.ingestion_universe() == ["SPY", "AAA", "XSCAN", "XEVID"]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "exclusion list" in warnings[0].getMessage()


@pytest.mark.asyncio
async def test_nightly_scheduler_gets_filtered_universe(monkeypatch):
    from app.services import history_retention as retention, ingestion_scheduler
    _presets(monkeypatch, ["AAA", "XSCAN", "XEVID"])
    _exclusions(monkeypatch, EXCLUSIONS)
    monkeypatch.setattr(retention, "_load_settings", lambda: {"scheduling": {"history_years": 19}})
    start = Mock()
    monkeypatch.setattr(job, "start_ingestion_task", start)
    monkeypatch.setattr(ingestion_scheduler, "_run_nightly_maintenance", AsyncMock())
    await ingestion_scheduler._run_nightly()
    start.assert_called_once_with(["SPY", "AAA", "XEVID"], years=19)


@pytest.mark.asyncio
async def test_startup_catch_up_gets_filtered_universe(monkeypatch):
    class _Session:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    _presets(monkeypatch, ["AAA", "XSCAN", "XEVID"])
    _exclusions(monkeypatch, EXCLUSIONS)
    monkeypatch.setattr(job, "AsyncSessionLocal", _Session)
    monkeypatch.setattr(job, "_last_stored_date", AsyncMock(return_value=None))
    start = Mock(return_value=True)
    monkeypatch.setattr(job, "start_ingestion_task", start)
    assert await job.startup_catch_up() is True
    start.assert_called_once_with(["SPY", "AAA", "XEVID"], years=6)


@pytest.mark.asyncio
@pytest.mark.parametrize("requested, expected", [
    (["XSCAN", "AAA"], ["XSCAN", "AAA"]),
    (["SP500"], ["AAA", "XSCAN", "XEVID"]),
])
async def test_manual_ingest_is_not_filtered(monkeypatch, requested, expected):
    """Regression guard: an explicit manual request still ingests excluded symbols."""
    from app.routers import ingestion as router
    from app.services import history_retention as retention
    _presets(monkeypatch, ["AAA", "XSCAN", "XEVID"])
    _exclusions(monkeypatch, EXCLUSIONS)
    monkeypatch.setattr(retention, "_load_settings", lambda: {})
    start = Mock(return_value=True)
    monkeypatch.setattr(router, "start_ingestion_task", start)
    result = await router.trigger_ingest(router.IngestRequest(symbols=requested))
    assert start.call_args.args[0] == expected
    assert result["total"] == len(expected)
