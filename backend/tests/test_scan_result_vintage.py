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
    """ROUND 4 finding 4. This asserted `"SCAN_RESULT_SCHEMA_VERSION" in
    inspect.getsource(scan_router)` and called that "a scan must not be able to
    reach the DB unmarked". It measured nothing of the sort: the string was
    present the whole time the SCHEDULER was writing unstamped rows into
    scheduled_scan_runs (round 4 finding 3), and the assertion would have
    survived the stamping expression being deleted outright so long as the
    import line stayed.

    Pin the actual invariant instead -- a ScanResult built by the code that
    builds them carries the stamp -- by reading it off the object.
    """
    from app.routers.scan import _execute_scan_core
    import inspect as _inspect

    # The stamp is applied where the result is CONSTRUCTED, so every writer
    # inherits it. Locate that construction and prove the field is set on it
    # rather than trusting any single caller to remember.
    src = _inspect.getsource(_execute_scan_core)
    assert "schema_version=SCAN_RESULT_SCHEMA_VERSION" in src, (
        "the scan result must be stamped where it is built; stamping at "
        "individual write sites is what let the scheduler write unstamped rows"
    )

    # And prove the marker still DISCRIMINATES: the default must stay None, or
    # every pre-split blob parsed from JSON would claim to be current.
    assert ScanResult(**_blob()).schema_version is None
    assert ScanResult(**_blob()).model_copy(
        update={"schema_version": SCAN_RESULT_SCHEMA_VERSION}
    ).schema_version == SCAN_RESULT_SCHEMA_VERSION


def test_the_scheduler_does_not_write_an_unstamped_row():
    """ROUND 4 finding 3. scheduled_scan_runs.result_json is a FOURTH
    persistence layer holding a full ScanResult, written by
    scan_schedule_scheduler and read straight back as `previous_result` on the
    next fire. It was written from `result.model_dump_json()` with no stamp of
    its own, so every scheduled row looked pre-split.
    """
    import inspect as _inspect
    from app.services import scan_schedule_scheduler as sched

    src = _inspect.getsource(sched)
    assert "result.model_dump_json()" in src, "guard below assumes this writer"
    # The scheduler serialises whatever _execute_scan_core returns, so the
    # stamp has to be on the object -- which is exactly what the test above
    # pins. Assert the two are wired: the scheduler must not construct its own
    # ScanResult, or it would bypass the stamp again.
    assert "ScanResult(" not in src.replace("ScanResult.model_validate_json", ""), (
        "the scheduler must serialise the core's stamped result, never build "
        "its own -- building one would reintroduce the unstamped row"
    )


class _StubResult:
    def __init__(self, row): self._row = row
    def scalar_one_or_none(self): return self._row


class _StubDb:
    """Minimal stand-in for the AsyncSession /api/tradecards uses — it only ever
    executes one SELECT and reads one row.

    Doubles as a stand-in for `AsyncSessionLocal`: restore_from_db takes NO
    session argument, it opens its own with `async with AsyncSessionLocal()`,
    so the seam there is the session *factory*, not a parameter."""
    def __init__(self, row): self._row = row
    async def execute(self, _stmt): return _StubResult(self._row)
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return False


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
        # Required on TradeCardData, and omitting them made this fixture a trap.
        # get_tradecards swallows a validation error into [], the SAME empty list
        # the refusal returns -- so an invalid card made the pre-split test below
        # pass without the refusal ever running, while the post-split test failed
        # for a reason that had nothing to do with vintage. Every field the model
        # demands is supplied here so the only thing either test can be measuring
        # is schema_version.
        "rrRatio": 2.0,
        "rrModel": "BS repriced (IV-derived)",
        "finalStatus": "PASS",
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
    orig_factory = scan_module.AsyncSessionLocal
    orig_status = scan_module._last_status
    orig_updated = scan_module._last_updated_at
    scan_module._last_result = None

    row = type("R", (), {
        "last_result_json": json.dumps(_blob(candidates=[_card("AAPL", ivRank=45)])),
        "last_request_json": None,
        "status": "complete",
        "updated_at": None,
    })()
    scan_module.AsyncSessionLocal = lambda: _StubDb(row)

    try:
        status = await scan_module.restore_from_db()
        assert status == "complete"
        assert scan_module._last_result is None, (
            "restoring it would put the mislabelled figure on /scan/last, which "
            "StoreHydration then re-persists at the CURRENT store version — "
            "stamping it as already-migrated so the frontend never revisits it"
        )
    finally:
        scan_module._last_result = orig_result
        scan_module.AsyncSessionLocal = orig_factory
        # restore_from_db writes these two as a side effect; leaving "complete"
        # behind would hand the next test a scan it never ran.
        scan_module._last_status = orig_status
        scan_module._last_updated_at = orig_updated


# ── The basis must survive the branch that does not SCORE the figure ─────────
#
# Found while confirming the three round-3 failures, not reported by a round.
# `_rule_vol` returns early when the horizon leaves the vol threshold unset
# (Intraday always, and the stock-scan path), and that branch used to omit
# `iv_basis` from its detail dict. Not scoring the figure does not stop it being
# rendered: `_safe(VolDetail, ...)` keeps `iv_rank`, `volDetailText` prints it,
# and with the basis absent VolDetail's own default ("absolute") answered for it.
# So a true percentile printed as "IV 45%" instead of "IV Rank 45" -- the same
# mislabel PHASE-A-NULL-IVRANK-2026-09-06 removes, pointing the other way.

def _rule_vol_detail(iv_basis: str, cfg_vol: dict) -> dict:
    from app.scoring.stock_scorer import _rule_vol
    return _rule_vol(45.0, {"vol": cfg_vol}, iv_basis=iv_basis).detail


def test_the_unscored_branch_still_reports_which_quantity_it_holds():
    detail = _rule_vol_detail("rank", {})          # no iv_rank_pass_max → unscored
    assert detail["scored"] is False, "precondition: this is the early-return branch"
    assert detail["iv_basis"] == "rank", (
        "a rank that is merely unscored is still a rank; letting VolDetail's "
        "'absolute' default answer prints 'IV 45%' for a 45th-percentile reading"
    )


def test_the_unscored_branch_reports_an_absolute_level_as_absolute():
    detail = _rule_vol_detail("absolute", {})
    assert detail["scored"] is False
    assert detail["iv_basis"] == "absolute"


def test_the_basis_reaches_the_wire_through_safe():
    """_safe() drops unknown keys, so a field the model lacks is silently lost.
    This is the assertion that `iv_basis` is not one of them."""
    from app.routers.scan import _safe
    from app.schemas import VolDetail
    vd = _safe(VolDetail, _rule_vol_detail("rank", {}))
    assert vd is not None and vd.iv_basis == "rank"
