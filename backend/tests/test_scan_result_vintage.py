"""A persisted scan result from before the IV basis split must not be re-served.

Round 3 finding 2. `scan_sessions.last_result_json` survives an upgrade, and
`ivRank` in a blob written before PHASE-A-NULL-IVRANK-2026-09-06 holds raw
implied volatility x100 under the name of a percentile. Nothing on the record
says which quantity it is, and the basis is no more recoverable here than it was
in the localStorage blobs round 1 addressed — so it is DROPPED, not relabelled.

This matters more than a stale-cache annoyance: the frontend re-persists whatever
`/scan/last` returns at the CURRENT store version, so a bad figure served once is
stamped as already-migrated and never revisited on that browser.
"""
import json

import pytest

from app.schemas import ScanResult, SCAN_RESULT_SCHEMA_VERSION


def _blob(**kw) -> dict:
    """A minimal persisted ScanResult, as JSON-compatible dict."""
    base = {"scan_id": "S1", "timestamp": "2026-09-05T10:00:00", "candidates": [], "rejected": []}
    return {**base, **kw}


def test_a_result_with_no_version_is_recognised_as_pre_split():
    parsed = ScanResult.model_validate(_blob())
    assert parsed.schema_version is None, (
        "absence is the signal; defaulting it to the current version would make "
        "every pre-split blob claim to be post-split"
    )


def test_the_current_version_round_trips_through_json():
    stamped = ScanResult(**_blob()).model_copy(
        update={"schema_version": SCAN_RESULT_SCHEMA_VERSION})
    again = ScanResult.model_validate_json(stamped.model_dump_json())
    assert again.schema_version == SCAN_RESULT_SCHEMA_VERSION


def test_the_save_path_stamps_every_result_it_persists():
    # Pinned against the router's own source rather than re-implementing the
    # expression: a scan must not be able to reach the DB unmarked, or the very
    # next restore would discard a perfectly good result.
    import inspect
    from app.routers import scan as scan_router
    src = inspect.getsource(scan_router)
    assert "SCAN_RESULT_SCHEMA_VERSION" in src
    assert "last_result_json=(" in src


class _StubResult:
    def __init__(self, row): self._row = row
    def scalar_one_or_none(self): return self._row


class _StubDb:
    """Minimal stand-in for the AsyncSession /api/tradecards uses — it only ever
    executes one SELECT and reads one row."""
    def __init__(self, row): self._row = row
    async def execute(self, _stmt): return _StubResult(self._row)


def _card(symbol: str, **contract_details) -> dict:
    cd = {"strike": 185, "expiry": "2026-12-01", "right": "C", "mid": 2.0,
          "delta": 0.5, "theta": -0.05, "dte": 60}
    cd.update(contract_details)
    return {
        "symbol": symbol, "company": symbol, "price": 185.0, "direction": "Bullish",
        "status": "PASS", "stockScore": 80, "stockConfidence": "PASS",
        "stockBreakdown": {"trend": 80, "pullback": 80, "trigger": 80,
                           "event": 80, "volatility": 80},
        "contract": f"{symbol}|185|2026-12-01|C", "contractScore": 70,
        "contractConfidence": "PASS",
        "contractBreakdown": {"dteFit": 70, "delta": 70, "ivAttractiveness": 70,
                              "liquidity": 70, "spread": 70},
        "contractDetails": cd,
        "entry": {"limit": 2.0, "maxFill": 2.1, "orderType": "Limit"},
        "exit": {"invalidation": 180.0, "premiumStop": 1.0, "timeStopDays": 30,
                 "target": 200.0, "targets": []},
    }


class _Row:
    def __init__(self, blob): self.last_result_json = json.dumps(blob)


@pytest.mark.asyncio
async def test_tradecards_serves_nothing_from_a_pre_split_blob():
    """/api/tradecards reads the row DIRECTLY, bypassing restore_from_db, so it
    carries its own copy of the refusal. 45 in `ivRank` here is raw IV x100."""
    from app.routers.tradecards import get_tradecards
    row = _Row(_blob(candidates=[_card("AAPL", ivRank=45, ivPercentile=0)]))  # no schema_version
    assert await get_tradecards(_StubDb(row)) == [], (
        "a pre-split card must not reach the card the user acts from: it would "
        "print 'IV rank 45' for a 45% absolute IV"
    )


@pytest.mark.asyncio
async def test_tradecards_still_serves_a_stamped_blob():
    from app.routers.tradecards import get_tradecards
    row = _Row(_blob(candidates=[_card("MSFT", ivRank=None, iv=42.0, ivPercentile=None)],
                     schema_version=SCAN_RESULT_SCHEMA_VERSION))
    cards = await get_tradecards(_StubDb(row))
    assert len(cards) == 1 and cards[0].symbol == "MSFT", (
        "the refusal must be narrow: a post-split result is still served"
    )


@pytest.mark.asyncio
async def test_restore_from_db_drops_a_pre_split_result_but_keeps_the_status():
    """The status pill and the request survive; only the unattributable cards go."""
    from app.routers import scan as scan_module

    orig_result = scan_module._last_result
    scan_module._last_result = None

    class _Sess:
        async def execute(self, _stmt):
            return _StubResult(type("R", (), {
                "last_result_json": json.dumps(_blob(candidates=[_card("AAPL", ivRank=45)])),
                "last_request_json": None,
                "status": "complete",
                "updated_at": None,
            })())
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    try:
        status = await scan_module.restore_from_db(_Sess())
        assert status == "complete"
        assert scan_module._last_result is None, (
            "restoring it would put the mislabelled figure on /scan/last, which "
            "StoreHydration then re-persists at the CURRENT store version — "
            "stamping it as already-migrated so the frontend never revisits it"
        )
    finally:
        scan_module._last_result = orig_result
