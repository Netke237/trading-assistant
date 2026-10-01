"""Watched contracts carry the grading Step 6 used (WATCHLIST-SCAN-CONTRACT-RULES).

A star stores {contract_rules, hold_min_days, hold_max_days, stock_score}, so
the Watchlist grades it as the scan did instead of on contract_rules.yaml.

Harness: a bare FastAPI() with only the watched_contracts router (app.main's
lifespan starts schedulers) on its own in-memory aiosqlite engine. The table is
created from WatchedContractModel.__table__ directly: app/models/__init__.py
does not import watched_contracts, so Base.metadata.create_all would miss it.
"""

import asyncio
import importlib.util
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.main import request_validation_handler
from app.models.watched_contracts import WatchedContractModel
from app.routers.watched_contracts import router

_ID = "XOM|190|2026-12-18|C"
_G = {
    "contract_rules": {"min_volume": 20, "min_open_interest": 75, "max_bid_ask_spread_pct": 0.3},
    "hold_min_days": 20, "hold_max_days": 25, "stock_score": 72,
}


def _make_app(with_handler=True):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(WatchedContractModel.__table__.create)
    asyncio.run(_create())

    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _db():
        async with sessions() as s:
            yield s

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = _db
    if with_handler:
        # pydantic echoes the offending input into the 422 body; a NaN there
        # makes Starlette's allow_nan=False encoder raise -> 500 without it.
        app.add_exception_handler(RequestValidationError, request_validation_handler)
    return app, engine


@pytest.fixture
def wc():
    app, engine = _make_app()
    with TestClient(app) as c:
        c.engine = engine
        yield c


def _detail(c):
    r = c.get("/api/watched-contracts/detail")
    assert r.status_code == 200
    return r.json()


def _raw(c, sql):
    async def _q():
        async with c.engine.connect() as conn:
            return (await conn.execute(text(sql))).all()
    return asyncio.run(_q())


# ── 1-3: storing, the old shape, overwrite semantics ──────────────────────────

def test_post_with_grading_is_served_verbatim(wc):
    assert wc.post("/api/watched-contracts", json={"contract_id": _ID, "grading": _G}).status_code == 201
    assert _detail(wc) == [{"contract_id": _ID, "grading": _G}]


def test_post_without_grading_keeps_the_old_shape(wc):
    wc.post("/api/watched-contracts", json={"contract_id": _ID})
    assert _detail(wc) == [{"contract_id": _ID, "grading": None}]
    assert wc.get("/api/watched-contracts").json() == [_ID]


def test_overwrite_keep_and_clear(wc):
    g2 = {**_G, "stock_score": 55, "contract_rules": {}}
    wc.post("/api/watched-contracts", json={"contract_id": _ID, "grading": _G})
    wc.post("/api/watched-contracts", json={"contract_id": _ID, "grading": g2})
    assert _detail(wc)[0]["grading"] == g2                       # not keep-first
    wc.post("/api/watched-contracts", json={"contract_id": _ID})
    assert _detail(wc)[0]["grading"] == g2                       # absent leaves it
    wc.post("/api/watched-contracts", json={"contract_id": _ID, "grading": None})
    assert _detail(wc)[0]["grading"] is None                     # explicit null clears
    assert len(_detail(wc)) == 1


def test_null_rules_and_null_hold_are_kept_as_null(wc):
    g = {"contract_rules": None, "hold_min_days": None, "hold_max_days": None, "stock_score": None}
    wc.post("/api/watched-contracts", json={"contract_id": _ID, "grading": g})
    assert _detail(wc)[0]["grading"] == g


def test_unknown_rule_keys_are_dropped(wc):
    g = {**_G, "contract_rules": {**_G["contract_rules"], "event_reject_days": 7}}
    assert wc.post("/api/watched-contracts", json={"contract_id": _ID, "grading": g}).status_code == 201
    assert _detail(wc)[0]["grading"] == _G


# ── 4: invalid grading is a 422 ───────────────────────────────────────────────

@pytest.mark.parametrize("bad", [
    {"contract_rules": {"min_volume": True}},
    {"contract_rules": {"min_volume": "5"}},
    {"contract_rules": {"min_volume": None}},
    {"hold_min_days": 25, "hold_max_days": 20},
    {"hold_min_days": 20},
    {"hold_max_days": 20},
    {"hold_min_days": -1, "hold_max_days": 5},
    {"hold_min_days": 20.0, "hold_max_days": 25},
    {"stock_score": 101},
    {"stock_score": "70"},
], ids=str)
def test_invalid_grading_is_a_422(wc, bad):
    r = wc.post("/api/watched-contracts", json={"contract_id": _ID, "grading": bad})
    assert r.status_code == 422, r.text
    assert wc.get("/api/watched-contracts").json() == []


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1" + "0" * 400])
def test_non_finite_and_huge_rule_values_are_a_422_not_a_500(wc, literal):
    body = '{"contract_id": "%s", "grading": {"contract_rules": {"min_volume": %s}}}' % (_ID, literal)
    r = wc.post("/api/watched-contracts", content=body, headers={"content-type": "application/json"})
    assert r.status_code == 422, r.text


def test_without_the_validation_handler_a_nan_body_is_a_500():
    """Why the harness (and production, app.main) register the handler."""
    app, _ = _make_app(with_handler=False)
    body = '{"contract_id": "%s", "grading": {"contract_rules": {"min_volume": NaN}}}' % _ID
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/api/watched-contracts", content=body, headers={"content-type": "application/json"})
    assert r.status_code == 500


# ── 5: stored rows that no longer validate ────────────────────────────────────

def test_an_invalid_stored_grading_is_served_as_null(wc):
    wc.post("/api/watched-contracts", json={"contract_id": _ID, "grading": _G})
    _raw_write(wc, """UPDATE watched_contracts SET grading = '{"hold_min_days": 5}'""")
    assert _detail(wc) == [{"contract_id": _ID, "grading": None}]


def _raw_write(c, sql):
    async def _q():
        async with c.engine.begin() as conn:
            await conn.execute(text(sql))
    asyncio.run(_q())


def test_explicit_null_stores_sql_null_not_json_null(wc):
    wc.post("/api/watched-contracts", json={"contract_id": _ID, "grading": _G})
    wc.post("/api/watched-contracts", json={"contract_id": _ID, "grading": None})
    assert _raw(wc, "SELECT contract_id FROM watched_contracts WHERE grading IS NULL") == [(_ID,)]


def test_a_new_row_without_grading_stores_sql_null(wc):
    wc.post("/api/watched-contracts", json={"contract_id": _ID})
    assert _raw(wc, "SELECT contract_id FROM watched_contracts WHERE grading IS NULL") == [(_ID,)]


# ── 6: the migration ──────────────────────────────────────────────────────────

def _load_migration():
    path = next(Path(__file__).resolve().parents[1].glob("migrations/versions/*_add_grading_to_watched_contracts.py"))
    spec = importlib.util.spec_from_file_location("grading_migration", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_adds_and_drops_the_column(tmp_path):
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine, inspect

    migration = _load_migration()
    assert migration.down_revision == "f3d5c81b0a47"

    engine = create_engine(f"sqlite:///{tmp_path / 'wc.db'}")
    with engine.connect() as conn:
        # The OLD table, by raw DDL -- not from the current model, which already has `grading`.
        conn.execute(text(
            "CREATE TABLE watched_contracts (id CHAR(32) PRIMARY KEY, contract_id VARCHAR NOT NULL UNIQUE, "
            "created_at DATETIME)"
        ))
        conn.execute(text("INSERT INTO watched_contracts VALUES ('a', 'XOM|190|2026-12-18|C', NULL)"))
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.upgrade()
        assert "grading" in {c["name"] for c in inspect(conn).get_columns("watched_contracts")}
        assert conn.execute(text("SELECT grading FROM watched_contracts")).all() == [(None,)]
        with Operations.context(ctx):
            migration.downgrade()
        assert "grading" not in {c["name"] for c in inspect(conn).get_columns("watched_contracts")}
        assert conn.execute(text("SELECT contract_id FROM watched_contracts")).all() == [("XOM|190|2026-12-18|C",)]


# ── the shared finite-number check ────────────────────────────────────────────

@pytest.mark.parametrize("val,ok", [
    (5, True), (0.3, True), (-1, True), (True, False), (False, False), ("5", False), (None, False),
    (float("nan"), False), (float("inf"), False), (10 ** 400, False),
])
def test_is_finite_rule_value(val, ok):
    from app.scoring.contract_validator import is_finite_rule_value
    assert is_finite_rule_value(val) is ok
