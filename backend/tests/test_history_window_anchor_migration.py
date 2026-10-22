"""HISTORY-INCREMENTAL-NIGHTLY B0: the window-anchor columns on a disposable database."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

NEW_REVISION = "b7d4e2a9c816"
PRIOR_HEAD = "e5c1a7d3b902"

OLD_COLUMNS = ["symbol", "floor_requested_start", "floor_date", "floor_provider",
               "floor_checked_at", "seam_date", "old_source", "seam_signature",
               "basis_provider", "basis_rebuilt_at"]
OLD_ROW = ("TEST", "2016-01-01", "2016-01-04", "tiingo", "2026-10-14 01:00:00",
           None, None, None, "tiingo", "2026-10-14 01:00:00")


def _alembic_runner(path):
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{path.as_posix()}"}
    cwd = Path(__file__).resolve().parents[1]

    def alembic(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "migrations/alembic.ini", *args],
            cwd=cwd, env=env, check=True, capture_output=True, text=True)

    return alembic


def _create_prior_state(path):
    # The a6a5b5d01fa5 (and e5c1a7d3b902) shape of ohlcv_history_state.
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE ohlcv_history_state ("
            " symbol VARCHAR(10) NOT NULL PRIMARY KEY,"
            " floor_requested_start DATE, floor_date DATE, floor_provider VARCHAR(20),"
            " floor_checked_at DATETIME, seam_date DATE, old_source VARCHAR(20),"
            " seam_signature VARCHAR(64), basis_provider VARCHAR(20), basis_rebuilt_at DATETIME)")
        db.execute("INSERT INTO ohlcv_history_state VALUES (?,?,?,?,?,?,?,?,?,?)", OLD_ROW)


def _columns(db):
    return [row[1] for row in db.execute("PRAGMA table_info(ohlcv_history_state)")]


def test_window_anchor_upgrade_and_downgrade_preserve_state_row(tmp_path):
    path = tmp_path / "window_anchor.db"
    _create_prior_state(path)
    alembic = _alembic_runner(path)
    alembic("stamp", PRIOR_HEAD)

    alembic("upgrade", NEW_REVISION)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == NEW_REVISION
        assert _columns(db) == OLD_COLUMNS + ["window_verified_through", "window_verified_at"]
        assert db.execute(
            f"SELECT {', '.join(OLD_COLUMNS)}, window_verified_through, window_verified_at "
            "FROM ohlcv_history_state").fetchall() == [OLD_ROW + (None, None)]

    alembic("downgrade", "-1")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == PRIOR_HEAD
        assert _columns(db) == OLD_COLUMNS
        assert db.execute(
            f"SELECT {', '.join(OLD_COLUMNS)} FROM ohlcv_history_state").fetchall() == [OLD_ROW]


def test_window_anchor_revision_stacks_on_the_single_prior_head(tmp_path):
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "migrations"))
    script = ScriptDirectory.from_config(config)
    assert script.get_revision(NEW_REVISION).down_revision == PRIOR_HEAD
    heads = script.get_heads()
    assert len(heads) == 1, heads
    assert NEW_REVISION in {rev.revision for rev in script.iterate_revisions(heads[0], "base")}
    out = _alembic_runner(tmp_path / "heads.db")("heads").stdout
    assert [line.split()[0] for line in out.splitlines() if line.strip()] == heads
