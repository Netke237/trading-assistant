"""Q3 -- stop bad data being persisted.

Plan: docs/superpowers/plans/2026-09-24-q3-persisted-data-hardening-plan.md
  1. POST /api/portfolio refuses a zero or negative qty (PATCH already did).
  2. alert_dedup.json is written atomically, so a failed write cannot
     truncate the previous dedup / first-seen records.
  3. config_loader's direction_conviction validator: tuple paths (no dotted-key
     forgery), an anchor holder whose block a legal horizon reads is accepted,
     and a self-referential anchor no longer raises RecursionError.
"""
from __future__ import annotations

import json
import logging
import os
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
import yaml

from app.services.config_loader import (
    _validated_direction_conviction_blocks,
    load_direction_conviction_min_trend,
)


# ── 1. PortfolioPositionCreate.qty ──────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.database import Base, get_db
    from app.main import app
    from app.models import audit_event, portfolio, watchlist  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    db_session = session_factory()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with (
        patch("app.routers.portfolio.fetch_contract_quote_async", new=AsyncMock(return_value=None)),
        patch("app.routers.portfolio.fetch_price_async", new=AsyncMock(return_value=None)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.clear()
    await db_session.close()
    await engine.dispose()


_PAYLOAD = {
    "recId": "REC-Q3-QTY",
    "symbol": "AAPL",
    "contract": "AAPL|190|2026-06-20|C",
    "direction": "Bullish",
    "entryPrice": 4.50,
    "entryDate": "2026-05-08",
    "stop": 2.25,
    "targets": [],
    "dteTotal": 43,
    "portfolioValue": 50_000.0,
}


@pytest.mark.asyncio
@pytest.mark.parametrize("qty", [0, -3])
async def test_create_refuses_a_non_positive_qty_and_saves_nothing(client, qty):
    resp = await client.post("/api/portfolio", json={**_PAYLOAD, "qty": qty})
    assert resp.status_code == 422, resp.text
    assert any(err["loc"][-1] == "qty" for err in resp.json()["detail"])
    listed = await client.get("/api/portfolio")
    assert listed.json() == []


@pytest.mark.asyncio
async def test_create_accepts_qty_one_the_boundary(client):
    resp = await client.post("/api/portfolio", json={**_PAYLOAD, "qty": 1})
    assert resp.status_code == 201, resp.text
    listed = (await client.get("/api/portfolio")).json()
    assert [p["qty"] for p in listed] == [1]


@pytest.mark.asyncio
async def test_create_default_qty_is_still_one(client):
    resp = await client.post("/api/portfolio", json=_PAYLOAD)
    assert resp.status_code == 201, resp.text


# ── 2. alert_dedup.json atomic write ────────────────────────────────────────

@pytest.fixture
def an():
    import app.services.notifications.alert_notifier as module
    return module


def _seed_previous_file(an) -> bytes:
    an._fired["REC-OLD|STOP_REACHED"] = 1000.0
    an._first_seen["REC-OLD|STOP_REACHED"] = "2026-09-01T00:00:00+00:00"
    an._save_dedup()
    return an._DEDUP_PATH.read_bytes()


def _leftover_temp_files(an) -> list[str]:
    return [p.name for p in an._DEDUP_PATH.parent.iterdir()
            if p.name != an._DEDUP_PATH.name and "alert_dedup" in p.name]


def test_save_then_load_round_trips(an):
    _seed_previous_file(an)
    an._fired.clear(); an._first_seen.clear()
    an._load_dedup()
    assert an._fired == {"REC-OLD|STOP_REACHED": 1000.0}
    assert an._first_seen == {"REC-OLD|STOP_REACHED": "2026-09-01T00:00:00+00:00"}
    assert _leftover_temp_files(an) == []


def test_a_write_that_fails_midway_leaves_the_previous_file_intact(an, monkeypatch, caplog):
    """The defect: open(path, 'w') truncates BEFORE the write, so a failure
    part-way left an empty or half-written file, which _load_dedup then
    swallowed -- every dedup hold and first-seen record gone on restart.
    Here the new bytes are already in the temp file when the sync fails."""
    before = _seed_previous_file(an)
    an._fired["REC-NEW|STOP_REACHED"] = 2000.0

    def _sync_fails(fd):
        raise OSError("disk full")

    monkeypatch.setattr(an.os, "fsync", _sync_fails)
    with caplog.at_level(logging.WARNING, logger=an.__name__):
        an._save_dedup()

    assert an._DEDUP_PATH.read_bytes() == before
    assert _leftover_temp_files(an) == []
    assert any("Could not persist dedup state" in r.getMessage()
               and r.levelno == logging.WARNING for r in caplog.records)


def test_a_failed_rename_leaves_the_previous_file_intact(an, monkeypatch):
    before = _seed_previous_file(an)
    an._fired["REC-NEW|STOP_REACHED"] = 2000.0

    def _no_replace(src, dst):
        raise OSError("rename refused")

    monkeypatch.setattr(an.os, "replace", _no_replace)
    an._save_dedup()

    assert an._DEDUP_PATH.read_bytes() == before
    assert _leftover_temp_files(an) == []


def test_an_unserialisable_value_never_touches_the_file(an):
    """The old json.dump streamed straight into the truncated target, so a value
    it could not encode left a half-written file behind."""
    before = _seed_previous_file(an)
    an._first_seen["REC-BAD|STOP_REACHED"] = object()
    an._save_dedup()
    assert an._DEDUP_PATH.read_bytes() == before
    assert _leftover_temp_files(an) == []


def test_a_successful_save_replaces_the_file_with_the_new_state(an):
    _seed_previous_file(an)
    an._fired["REC-NEW|STOP_REACHED"] = 2000.0
    an._save_dedup()
    data = json.loads(an._DEDUP_PATH.read_text(encoding="utf-8"))
    assert data["fired"] == {"REC-OLD|STOP_REACHED": 1000.0, "REC-NEW|STOP_REACHED": 2000.0}
    assert _leftover_temp_files(an) == []


def test_a_corrupt_file_on_load_is_reported_at_warning(an, caplog):
    an._DEDUP_PATH.write_text('{"fired": {"REC-1|STOP', encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger=an.__name__):
        an._load_dedup()
    assert an._fired == {} and an._first_seen == {}
    assert any("Could not load dedup state" in r.getMessage()
               and r.levelno == logging.WARNING for r in caplog.records)


# ── 3. config_loader direction_conviction validator ─────────────────────────

def _load(text: str) -> dict:
    return yaml.safe_load(text)


def test_a_flat_dotted_key_cannot_forge_a_legal_path():
    """3a. A top-level key literally spelled `horizons.position` used to join to
    the legal string 'horizons.position.direction_conviction', pass validation,
    and sit inert while the gate ran on the real block's 40."""
    cfg = _load("""
horizons.position:
  direction_conviction: {bearish_min_trend: 99}
horizons:
  position:
    direction_conviction: {bearish_min_trend: 40}
""")
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match=r"misplaced direction_conviction block.*horizons\.position\.direction_conviction"):
            load_direction_conviction_min_trend("Bearish", "Position")


def test_a_dotted_key_inside_horizons_cannot_forge_either():
    cfg = {"horizons": {
        "position.x": {"direction_conviction": {"bearish_min_trend": 99}},
        "position": {"direction_conviction": {"bearish_min_trend": 40}},
    }}
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match="misplaced direction_conviction block"):
            load_direction_conviction_min_trend("Bearish", "Position")


def test_an_anchor_holder_whose_block_a_horizon_merges_is_accepted():
    """3b. The `_defaults: &anchor` holder a YAML merge key needs, carrying the
    block itself. PyYAML resolves the merge to the SAME dict object, so the
    block is genuinely read at horizons.position -- it is not inert."""
    cfg = _load("""
horizons:
  _defaults: &dc
    direction_conviction: {bullish_min_trend: 55, bearish_min_trend: 45}
  position:
    <<: *dc
""")
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        assert load_direction_conviction_min_trend("Bullish", "Position") == 55.0
        assert load_direction_conviction_min_trend("Bearish", "Position") == 45.0


def test_a_block_aliased_into_a_horizon_is_accepted():
    cfg = _load("""
_shared:
  direction_conviction: &blk {bearish_min_trend: 45}
horizons:
  swing:
    direction_conviction: *blk
""")
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        assert load_direction_conviction_min_trend("Bearish", "Swing") == 45.0


def test_an_anchor_holder_nobody_merges_is_still_rejected():
    cfg = _load("""
horizons:
  _defaults: &dc
    direction_conviction: {bearish_min_trend: 45}
  position:
    weights: {trend: 0.3}
""")
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match=r"misplaced direction_conviction block.*horizons\._defaults"):
            load_direction_conviction_min_trend("Bearish", "Position")


def test_a_holder_block_overridden_by_the_horizon_is_still_rejected():
    """The horizon merges the holder but then writes its own block, so the
    holder's is never read -- editing it would change nothing."""
    cfg = _load("""
horizons:
  _defaults: &dc
    direction_conviction: {bearish_min_trend: 45}
  position:
    <<: *dc
    direction_conviction: {bearish_min_trend: 40}
""")
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match="misplaced direction_conviction block"):
            load_direction_conviction_min_trend("Bearish", "Position")


def test_a_misplaced_null_block_gets_no_identity_exemption():
    """`None is None` everywhere, so a scalar must never borrow a legal
    horizon's identity. Misplaced `direction_conviction: null` under `vol`
    while position also has an explicit null: still rejected."""
    cfg = {"horizons": {"position": {
        "direction_conviction": None,
        "vol": {"direction_conviction": None},
    }}}
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match="misplaced direction_conviction block"):
            load_direction_conviction_min_trend("Bearish", "Position")


# Round 2 (the code) finding: the first exemption asked only "does SOME horizon
# read this object?", so a block aliased into the WRONG place was excused by
# another horizon's legal read, and the horizon the operator meant ran on its
# old threshold. Each case below was accepted at 0d02be6 and rejected on main.

@pytest.mark.parametrize("text,where", [
    ("""
horizons:
  swing:
    direction_conviction: &b {bullish_min_trend: 60, bearish_min_trend: 60}
  position:
    vol:
      direction_conviction: *b
""", r"horizons\.position\.vol\.direction_conviction"),
    ("""
horizons:
  _defaults: &d
    direction_conviction: {bullish_min_trend: 60, bearish_min_trend: 60}
  swing:
    <<: *d
  position:
    trend:
      <<: *d
""", r"horizons\.position\.trend\.direction_conviction"),
    ("""
horizons:
  swing: &s
    direction_conviction: {bullish_min_trend: 60, bearish_min_trend: 60}
  position:
    vol: *s
""", r"horizons\.position\.vol\.direction_conviction"),
    # A mis-cased horizon aliasing another horizon's block: Position meant,
    # swing's block borrowed.
    ("""
horizons:
  swing:
    direction_conviction: &b {bullish_min_trend: 60, bearish_min_trend: 60}
  Position:
    direction_conviction: *b
""", r"horizons\.Position\.direction_conviction"),
    # An '_'-prefixed holder INSIDE a known horizon is still the wrong place
    # for that horizon, whoever else reads the object.
    ("""
horizons:
  swing:
    direction_conviction: &b {bullish_min_trend: 60, bearish_min_trend: 60}
  position:
    _local:
      direction_conviction: *b
""", r"horizons\.position\._local\.direction_conviction"),
    # A holder without the '_' convention is not an anchor holder.
    ("""
shared:
  direction_conviction: &b {bullish_min_trend: 60, bearish_min_trend: 60}
horizons:
  swing:
    direction_conviction: *b
""", r"shared\.direction_conviction"),
])
def test_a_block_read_elsewhere_does_not_excuse_a_wrong_placement(text, where):
    cfg = _load(text)
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match="misplaced direction_conviction block.*" + where):
            load_direction_conviction_min_trend("Bullish", "Position")


def test_a_null_block_in_an_anchor_holder_gets_no_exemption():
    """`None is None` everywhere: a holder's `direction_conviction: null` must
    not borrow position's explicit null as a legal read."""
    cfg = {"_holder": {"direction_conviction": None},
           "horizons": {"position": {"direction_conviction": None}}}
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match=r"misplaced direction_conviction block.*_holder"):
            load_direction_conviction_min_trend("Bearish", "Position")


def test_a_self_referential_anchor_is_not_a_recursion_error():
    """3c. `horizons: &x {swing: *x}` used to recurse until RecursionError,
    which neither router catches -- a bare 500 with no detail."""
    cfg = _load("horizons: &x\n  swing: *x\n")
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        try:
            _validated_direction_conviction_blocks()
        except ValueError:
            pass  # a named error is acceptable; RecursionError is not


def test_a_cycle_does_not_hide_a_misplaced_block():
    cfg = _load("""
horizons: &x
  swing: *x
  position:
    vol:
      direction_conviction: {bearish_min_trend: 70}
""")
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match="misplaced direction_conviction block"):
            _validated_direction_conviction_blocks()


def test_mixed_type_unknown_keys_give_the_named_error_not_typeerror():
    """3d(i). Without `str(k)` in the sort, a bool key beside a str key raises
    TypeError from sorted(), which neither router catches."""
    cfg = {"horizons": {"position": {"direction_conviction": {
        True: 5, "typo_key": 7, "bearish_min_trend": 40,
    }}}}
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match="unknown direction_conviction key"):
            load_direction_conviction_min_trend("Bearish", "Position")


def test_a_numeric_intraday_threshold_in_the_yaml_is_honoured():
    """3d(ii). Intraday has no code default (exempt), so only the YAML can gate
    it -- and nothing pinned that a number written there is read."""
    cfg = {"horizons": {"intraday": {"direction_conviction": {
        "bullish_min_trend": 25, "bearish_min_trend": 35,
    }}}}
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        assert load_direction_conviction_min_trend("Bullish", "Intraday") == 25.0
        assert load_direction_conviction_min_trend("Bearish", "Intraday") == 35.0
