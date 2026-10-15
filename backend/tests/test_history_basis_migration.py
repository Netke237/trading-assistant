"""Exercise the single-provider basis migration on a disposable prior-head database."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

NEW_REVISION = "a6a5b5d01fa5"
PRIOR_HEAD = "a93b8d24f760"


def _alembic_runner(path):
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{path.as_posix()}"}
    cwd = Path(__file__).resolve().parents[1]

    def alembic(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "migrations/alembic.ini", *args],
            cwd=cwd, env=env, check=True, capture_output=True, text=True)

    return alembic


def _create_history_state(db):
    # The c15d709a26b1 shape of ohlcv_history_state.
    db.execute(
        "CREATE TABLE ohlcv_history_state ("
        " symbol VARCHAR(10) NOT NULL PRIMARY KEY,"
        " floor_requested_start DATE, floor_date DATE, floor_provider VARCHAR(20),"
        " floor_checked_at DATETIME, seam_date DATE, old_source VARCHAR(20),"
        " seam_signature VARCHAR(64))")
    db.execute(
        "INSERT INTO ohlcv_history_state VALUES ('TEST','2016-01-01','2016-01-04','tiingo',"
        "'2026-10-14 01:00:00','2020-10-12','tiingo','abc123')")


OLD_ROW = ("TEST", "2016-01-01", "2016-01-04", "tiingo", "2026-10-14 01:00:00",
           "2020-10-12", "tiingo", "abc123")
OLD_COLUMNS = ["symbol", "floor_requested_start", "floor_date", "floor_provider",
               "floor_checked_at", "seam_date", "old_source", "seam_signature"]


def test_basis_columns_upgrade_and_downgrade_preserve_state_row(tmp_path):
    path = tmp_path / "basis_migration.db"
    with sqlite3.connect(path) as db:
        _create_history_state(db)
    alembic = _alembic_runner(path)

    alembic("stamp", PRIOR_HEAD)
    alembic("upgrade", NEW_REVISION)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == NEW_REVISION
        columns = [row[1] for row in db.execute("PRAGMA table_info(ohlcv_history_state)")]
        assert {"basis_provider", "basis_rebuilt_at"} <= set(columns)
        row = db.execute(
            f"SELECT {', '.join(OLD_COLUMNS)}, basis_provider, basis_rebuilt_at "
            "FROM ohlcv_history_state").fetchall()
        assert row == [OLD_ROW + (None, None)]

    alembic("downgrade", PRIOR_HEAD)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == PRIOR_HEAD
        columns = [row[1] for row in db.execute("PRAGMA table_info(ohlcv_history_state)")]
        assert "basis_provider" not in columns
        assert "basis_rebuilt_at" not in columns
        assert columns == OLD_COLUMNS
        assert db.execute(
            f"SELECT {', '.join(OLD_COLUMNS)} FROM ohlcv_history_state").fetchall() == [OLD_ROW]


def test_alembic_has_single_head_the_basis_revision(tmp_path):
    alembic = _alembic_runner(tmp_path / "heads.db")
    out = alembic("heads").stdout
    heads = [line.split()[0] for line in out.splitlines() if line.strip()]
    assert heads == [NEW_REVISION]
