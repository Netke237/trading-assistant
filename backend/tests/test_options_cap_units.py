"""#368: Options USD boundary semantics and persisted schedule recovery."""
import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from app.schemas import ScanRequest, ScanResult
from app.schemas.scan_schedule import ScanScheduleEntry
from app.services.scan_schedule_store import ScanScheduleStore, list_scheduled_scan_runs
from tests.test_scan_schedule import _options_entry_body


@pytest.mark.parametrize('marker', [None, 1])
def test_schedule_units_roundtrip(tmp_path, marker):
    request = dict(universe=['AAPL'], direction='Bullish', horizon='Swing', min_cap_usd=25_000_000, max_cap_usd=2_000_000_000)
    if marker is not None:
        request['cap_filter_units_version'] = marker
    entry = ScanScheduleEntry(id='cap', **_options_entry_body(resolved_request=request))
    path = tmp_path / 'schedule.yaml'
    store = ScanScheduleStore(path)
    store.upsert(entry.model_dump(mode='json'))
    assert ScanScheduleStore(path).get('cap')['resolved_request'] == request
    assert ScanRequest.model_validate(request).cap_filter_units_version == marker
    before = path.read_bytes()
    for bad in [0, 2, -1, '1', 'future']:
        with pytest.raises(ValidationError):
            ScanScheduleEntry(id='cap', **_options_entry_body(resolved_request={**request, 'cap_filter_units_version': bad}))
        assert path.read_bytes() == before


@pytest.mark.asyncio
@pytest.mark.parametrize('caps,allowed', [
    ({'min_cap_usd': 25}, False), ({'max_cap_usd': 25}, False),
    ({'min_cap_usd': -25}, False), ({'max_cap_usd': -25}, False),
    ({'min_cap_usd': 2_000_000_000}, False),
    ({}, True), ({'min_cap_usd': 0}, True), ({'max_cap_usd': 0}, True),
    ({'min_cap_usd': 0, 'max_cap_usd': 0}, True),
    ({'min_cap_usd': 25_000_000, 'cap_filter_units_version': 1}, True),
    ({'max_cap_usd': 2_000_000_000, 'cap_filter_units_version': 1}, True),
])
async def test_schedule_legacy_caps_refuse_until_explicit_resync(monkeypatch, tmp_path, caps, allowed):
    from app.services import scan_schedule_scheduler as scheduler
    from tests.conftest import _TestSession
    import app.database as dbmod
    import app.routers.scan as scan

    store = ScanScheduleStore(tmp_path / 'schedule.yaml')
    raw = dict(universe=['AAPL'], direction='Bullish', horizon='Swing', **caps)
    entry = dict(id='cap-recovery', **_options_entry_body(resolved_request=raw))
    store.upsert(deepcopy(entry))
    original = store._path.read_bytes()
    monkeypatch.setattr(scheduler, 'scan_schedule_store', store)
    monkeypatch.setattr(dbmod, 'AsyncSessionLocal', _TestSession)
    core = AsyncMock(return_value=ScanResult(scan_id='cap-run', timestamp='2026-01-01T00:00:00Z', candidates=[], rejected=[]))
    monkeypatch.setattr(scan, '_execute_scan_core', core)
    async def reported(req, *, callback, **kwargs):
        return await callback()
    report = AsyncMock(side_effect=reported)
    monkeypatch.setattr(scheduler, 'run_reported_scan', report)
    error = AsyncMock()
    monkeypatch.setattr(scheduler, '_notify_scan_schedule_error', error)
    monkeypatch.setattr(scheduler, '_notify_scan_schedule_success', AsyncMock())
    await scheduler._run_scheduled_entry(entry['id'])
    assert store.get(entry['id']) == entry
    assert store._path.read_bytes() == original
    async with _TestSession() as db:
        runs = await list_scheduled_scan_runs(db, entry['id'])
    assert runs[0].status == ('success' if allowed else 'error')
    if allowed:
        assert core.call_count == report.call_count == 1
        assert core.call_args.args[0].min_cap_usd == caps.get('min_cap_usd')
        assert core.call_args.args[0].max_cap_usd == caps.get('max_cap_usd')
        error.assert_not_called()
    else:
        core.assert_not_called()
        report.assert_not_called()
        assert 're-save' in runs[0].error.lower()
        assert 'search profile' in runs[0].error.lower()
        assert 'units' in runs[0].error.lower()
        assert error.call_args.args[1] == runs[0].error
        # An explicit profile resync supplies fresh USD amounts and provenance.
        entry['resolved_request'] = {**raw, 'min_cap_usd': 25_000_000, 'max_cap_usd': 2_000_000_000, 'cap_filter_units_version': 1}
        store.upsert(entry)
        await scheduler._run_scheduled_entry(entry['id'])
        core.assert_awaited_once()
        req = core.call_args.args[0]
        assert (req.min_cap_usd, req.max_cap_usd) == (25_000_000, 2_000_000_000)


@pytest.mark.asyncio
@pytest.mark.parametrize('bound,threshold', [('min_cap_usd', 25_000_000), ('max_cap_usd', 25_000_000), ('min_cap_usd', 2_000_000_000), ('max_cap_usd', 2_000_000_000), ('min_cap_usd', 0), ('max_cap_usd', 0)])
@pytest.mark.parametrize('offset', [-1, 0, 1])
async def test_actual_options_filter_usd_boundaries(monkeypatch, bound, threshold, offset):
    import app.routers.scan as scan
    # Stop immediately after the real cap filter accepts; no downstream scorer/provider.
    class PastCapFilter(Exception):
        pass
    monkeypatch.setattr(scan, 'fetch_company_name_async', AsyncMock(return_value='Frozen'))
    monkeypatch.setattr(scan, 'fetch_fundamentals_calendar', AsyncMock(return_value=None))
    monkeypatch.setattr(scan, 'fetch_calendar_dates_async', AsyncMock(return_value=(None, None)))
    monkeypatch.setattr(scan, 'fetch_market_cap_async', AsyncMock(return_value=threshold + offset))
    monkeypatch.setattr(scan, '_load_scoring_cfg', Mock(side_effect=PastCapFilter))
    args = ('AAPL', 'Bullish', 'Swing', Mock(), asyncio.Semaphore(1), 'cap-fixture')
    kwargs = {bound: threshold, 'bars_map': {'AAPL': [{'close': 100}]}}
    rejected = offset < 0 if bound == 'min_cap_usd' else offset > 0
    if rejected:
        result = await scan._process_symbol(*args, **kwargs)
        assert result.reason.startswith('cap filter')
    else:
        with pytest.raises(PastCapFilter):
            await scan._process_symbol(*args, **kwargs)
