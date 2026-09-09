"""A persisted scan result written under an OLDER SCHEMA must not be re-served.

Round 3 finding 2. `scan_sessions.last_result_json` survives an upgrade, and
`ivRank` in a blob written before PHASE-A-NULL-IVRANK-2026-09-06 holds raw
implied volatility x100 under the name of a percentile. Nothing on the record
says which quantity it is, and the basis is no more recoverable here than it was
in the localStorage blobs round 1 addressed — so it is DROPPED, not relabelled.

This matters more than a stale-cache annoyance: the frontend re-persists whatever
`/scan/last` returns at the CURRENT store version, so a bad figure served once is
stamped as already-migrated and never revisited on that browser.

PIECE 3 (2026-09-09) MADE THE SAME FILE COVER A SECOND BUMP, and found that the
three guards could not. Each tested for the ABSENCE of a version (`is None`),
which was equivalent to a comparison only while exactly one bump existed. Piece 3
changed `exit.invalidation` from a flat percentage move to the resolved
structural+2xATR stop without changing its name, bumping the version to 2 -- and
every v1 blob sailed through all three guards. The tests below are therefore
parametrized over EVERY stale version rather than over `None`, so the next bump
is covered before it is written.
"""
import json

import asyncio
import pytest

from app.schemas import ScanResult, SCAN_RESULT_SCHEMA_VERSION


def _blob(**kw) -> dict:
    """A minimal persisted ScanResult, as JSON-compatible dict."""
    base = {"scan_id": "S1", "timestamp": "2026-09-05T10:00:00", "candidates": [], "rejected": []}
    return {**base, **kw}


# Every version a stored blob can carry that is NOT trustworthy today: absent
# (pre-Phase-A) plus every superseded stamp. Parametrizing over this rather than
# over `None` is the point -- see the module docstring.
#
# `SCAN_RESULT_SCHEMA_VERSION - 1` IS IN THE LIST EXPLICITLY, and it is what
# makes these tests measure the guards' SHAPE rather than today's constant.
# Derived purely from `range(1, VERSION)`, the list collapses to `[None]` the
# moment the constant is reverted or a bump is forgotten -- so every stale-blob
# case would silently vanish and the suite would go green on exactly the defect
# it exists to catch. The `- 1` entry is a stale version at every value of the
# constant, so a guard written as `is None` fails here no matter what.
STALE_VERSIONS = sorted(
    {None, SCAN_RESULT_SCHEMA_VERSION - 1, *range(1, SCAN_RESULT_SCHEMA_VERSION)},
    key=lambda v: (v is not None, v),
)


def test_a_result_with_no_version_is_recognised_as_pre_split():
    parsed = ScanResult.model_validate(_blob())
    assert parsed.schema_version is None, (
        "absence is the signal; defaulting it to the current version would make "
        "every pre-split blob claim to be post-split"
    )


def test_the_version_actually_moved_for_piece_3():
    """The bump itself, pinned.

    `exit.invalidation` changed basis without changing name -- a flat percentage
    move off the stock price became the resolved structural+2xATR stop -- and
    `exit.finalStop`, the block that would say which, did not exist before. A v1
    blob is indistinguishable from a piece-3 scan whose bar feed was too thin to
    resolve a stop, so it cannot be relabelled, only refused. Shipping piece 3
    at version 1 served that flat stop into the editable Invalidation field, past
    `checkInvalidation`, and into `PortfolioPosition.stop` for STOP_REACHED to
    fire against.
    """
    assert SCAN_RESULT_SCHEMA_VERSION >= 2


def test_the_current_version_round_trips_through_json():
    stamped = ScanResult(**_blob()).model_copy(
        update={"schema_version": SCAN_RESULT_SCHEMA_VERSION})
    again = ScanResult.model_validate_json(stamped.model_dump_json())
    assert again.schema_version == SCAN_RESULT_SCHEMA_VERSION


@pytest.mark.asyncio
async def test_the_save_path_stamps_every_result_it_persists():
    """ROUND 5 finding 4. Rounds 4 and 5 both caught this test lying about
    itself. It began as `assert "SCAN_RESULT_SCHEMA_VERSION" in
    inspect.getsource(scan_router)` -- green the entire time the scheduler was
    writing unstamped rows -- and round 4 "fixed" it by swapping in a NARROWER
    grep while writing a docstring claiming it now read the stamp off the
    object. It did not. So: actually run the producer and read the field.
    """
    import app.routers.scan as scan_module
    from tests.conftest import _TestSession

    # An empty universe exercises the construction without any network work;
    # the stamp is applied at the ScanResult(...) call, not per candidate.
    async with _TestSession() as db:
        req = scan_module.ScanRequest(
            universe=[], direction="Bullish", horizon="Swing", overrides={})
        result = await scan_module._execute_scan_core(req, db, previous_result=None)

    assert result.schema_version == SCAN_RESULT_SCHEMA_VERSION, (
        "a result the scan BUILDS must carry the stamp, or every writer that "
        "serialises it (the session upsert, the scheduler's "
        "scheduled_scan_runs row, the in-memory _last_result) persists a blob "
        "indistinguishable from a pre-split one"
    )
    # It must survive serialisation, since that is how all three writers store it.
    assert scan_module.ScanResult.model_validate_json(
        result.model_dump_json()).schema_version == SCAN_RESULT_SCHEMA_VERSION


def test_every_scan_result_construction_in_the_router_is_stamped():
    """ROUND 5 finding 4, second half. The execution test above covers the ONE
    path an empty-universe scan takes. The failure mode it cannot see is a
    second construction site added later -- an early return, an error branch --
    that forgets the stamp while the covered path keeps it green. Walk the AST
    instead of grepping, so this holds for every construction and does not
    break when the value expression is refactored.
    """
    import ast
    import inspect as _inspect
    from app.routers import scan as scan_router

    tree = ast.parse(_inspect.getsource(scan_router))
    sites = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name) and node.func.id == "ScanResult"
    ]
    assert sites, "expected at least one ScanResult(...) construction to guard"
    unstamped = [
        node.lineno for node in sites
        if not any(kw.arg == "schema_version" for kw in node.keywords)
    ]
    assert not unstamped, (
        f"ScanResult constructed without schema_version at line(s) {unstamped}; "
        "every construction must stamp, or that path writes a blob the vintage "
        "refusal will discard as pre-split"
    )


def test_the_scheduler_does_not_write_an_unstamped_row():
    """ROUND 4 finding 3 / ROUND 5 finding 4. scheduled_scan_runs.result_json is
    a FOURTH persistence layer, written by scan_schedule_scheduler and read
    straight back as `previous_result` on the next fire. This too was a pair of
    source greps; assert the actual round trip instead.
    """
    import app.routers.scan as scan_module
    from tests.conftest import _TestSession

    async def _run():
        async with _TestSession() as db:
            req = scan_module.ScanRequest(
                universe=[], direction="Bullish", horizon="Swing", overrides={})
            return await scan_module._execute_scan_core(req, db, previous_result=None)

    result = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(_run())
    # This is verbatim what the scheduler persists (scan_schedule_scheduler.py:145).
    result_json = result.model_dump_json()
    restored = scan_module.ScanResult.model_validate_json(result_json)
    assert restored.schema_version == SCAN_RESULT_SCHEMA_VERSION, (
        "the row the scheduler writes must be distinguishable from a pre-split "
        "blob; unstamped, a future vintage guard on that table discards ALL of "
        "them, since none would be marked"
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
@pytest.mark.parametrize("stale", STALE_VERSIONS)
async def test_tradecards_serves_nothing_from_a_stale_blob(stale):
    """/api/tradecards reads the row DIRECTLY, bypassing restore_from_db, so it
    carries its own copy of the refusal. 45 in `ivRank` here is raw IV x100, and
    the v1 case carries a flat `exit.invalidation` with no `finalStop`."""
    from app.routers.tradecards import get_tradecards
    extra = {} if stale is None else {"schema_version": stale}
    row = _Row(_blob(candidates=[_card("AAPL", ivRank=45, ivPercentile=0)], **extra))
    assert await get_tradecards(_StubDb(row)) == [], (
        f"a schema_version={stale} card must not reach the card the user acts "
        "from: at least one of its fields no longer means what its name says"
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
@pytest.mark.parametrize("stale", STALE_VERSIONS)
async def test_restore_from_db_drops_a_stale_result_and_the_status_with_it(stale):
    """ROUND 5 finding 11. This used to assert `status == "complete"` and called
    keeping it deliberate. It is not defensible: /scan/last-run then reported
    COMPLETED at the old timestamp while /scan/last returned null, so the TopBar
    pill claimed a finished scan with every table under it empty and the only
    explanation in a server log the user never sees. The status describes the
    result; when the result is refused the status goes with it."""
    from app.routers import scan as scan_module

    orig_result = scan_module._last_result
    orig_factory = scan_module.AsyncSessionLocal
    orig_status = scan_module._last_status
    orig_updated = scan_module._last_updated_at
    scan_module._last_result = None

    extra = {} if stale is None else {"schema_version": stale}
    row = type("R", (), {
        "last_result_json": json.dumps(_blob(candidates=[_card("AAPL", ivRank=45)], **extra)),
        "last_request_json": None,
        "status": "complete",
        "updated_at": None,
    })()
    scan_module.AsyncSessionLocal = lambda: _StubDb(row)

    try:
        status = await scan_module.restore_from_db()
        assert status == "idle", (
            "a status of 'complete' with no result behind it renders a TopBar "
            "pill asserting a scan the user cannot see the output of"
        )
        assert scan_module._last_status == "idle"
        assert scan_module._last_updated_at is None, (
            "a stale timestamp under an idle status dates a scan that no "
            "longer exists"
        )
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


class _ScalarsResult:
    def __init__(self, rows): self._rows = rows
    def scalars(self): return self
    def all(self): return self._rows


class _WatchlistDb:
    """Stand-in for the session /api/watchlist uses.

    It runs TWO selects -- the watchlist symbols, then the scan session row --
    so unlike `_StubDb` this one has to answer them differently. By ORDER, not
    by inspecting the statement: the endpoint's two calls are fixed and
    adjacent, and parsing the statement would couple the fixture to
    SQLAlchemy's internals for no gain.
    """
    def __init__(self, symbols, session_row):
        self._results = [
            _ScalarsResult([type("W", (), {"symbol": sym})() for sym in symbols]),
            _StubResult(session_row),
        ]

    async def execute(self, _stmt):
        return self._results.pop(0)


async def _watchlist_rows(symbols, session_row, monkeypatch):
    """Drive the REAL endpoint and return what it served.

    Calling `get_watchlist` rather than restating its guard is the whole point
    of the two tests below. Written as
    `assert (blob.schema_version or 0) >= SCAN_RESULT_SCHEMA_VERSION` against a
    locally parsed blob they were TAUTOLOGICAL: reverting watchlist.py to
    `is not None` left them green, so the endpoint's guard was still untested
    and the next bump would have been caught for /scan/last and /api/tradecards
    but not here -- the exact hole these tests were added to close. It is also
    the same defect this file's docstring records rounds 4 and 5 catching in
    the stamping test: a test asserting its own restatement of the code instead
    of the code.

    The live-fetch fallback is stubbed to return nothing, so a row it produces
    is unmistakable (score 0 / NO_DATA) against one the scan blob decided
    (score 80 / PASS).
    """
    from app.routers import watchlist as wl

    async def _no_price(_client, _sym): return None
    async def _no_company(_client, _sym): return None
    monkeypatch.setattr(wl, "fetch_price_async", _no_price)
    monkeypatch.setattr(wl, "fetch_company_name_async", _no_company)
    return await wl.get_watchlist(_WatchlistDb(symbols, session_row))


@pytest.mark.asyncio
@pytest.mark.parametrize("stale", STALE_VERSIONS)
async def test_the_watchlist_does_not_serve_scores_out_of_a_stale_blob(stale, monkeypatch):
    """Phase A round 5 found /api/watchlist serving scores, statuses and
    `stockBreakdown` out of the very blob /scan/last and /api/tradecards had
    just refused. Its guard was written as an absence test like the other two,
    so piece 3's bump would have re-opened exactly that hole."""
    extra = {} if stale is None else {"schema_version": stale}
    row = _Row(_blob(candidates=[_card("AAPL", ivRank=45)], **extra))
    rows = await _watchlist_rows(["AAPL"], row, monkeypatch)

    assert len(rows) == 1
    assert rows[0].score == 0 and rows[0].status == "NO_DATA", (
        f"a schema_version={stale} blob decided this row (score {rows[0].score}, "
        f"status {rows[0].status}): its scores were computed against fields that "
        "no longer mean what their names say"
    )


@pytest.mark.asyncio
async def test_the_watchlist_still_serves_a_current_blob(monkeypatch):
    """The refusal must be narrow, exactly as it is for /api/tradecards -- or
    the fix is not a guard, it is an outage."""
    row = _Row(_blob(candidates=[_card("MSFT", ivRank=None, iv=42.0)],
                     schema_version=SCAN_RESULT_SCHEMA_VERSION))
    rows = await _watchlist_rows(["MSFT"], row, monkeypatch)

    assert len(rows) == 1
    assert rows[0].score == 80 and rows[0].status == "PASS", (
        "a current blob must still decide the row; falling through to the live "
        "fetch would blank every watchlist score after an upgrade"
    )


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
