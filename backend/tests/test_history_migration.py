"""Exercise the HISTORY migration on a disposable prior-head database."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def test_history_upgrade_downgrade_preserves_daily_bars(tmp_path):
    path = tmp_path / "migration.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE ohlcv_daily (symbol TEXT, date TEXT, close NUMERIC)")
        db.execute("INSERT INTO ohlcv_daily VALUES ('TEST','2010-01-04',12.3456)")
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{path.as_posix()}"}
    cwd = Path(__file__).resolve().parents[1]

    def alembic(*args):
        subprocess.run([sys.executable, "-m", "alembic", "-c", "migrations/alembic.ini", *args],
                       cwd=cwd, env=env, check=True, capture_output=True, text=True)

    alembic("stamp", "f62a9e1b4c70")
    alembic("upgrade", "c15d709a26b1")  # this test pins HISTORY's own migration; later heads need tables this bare DB lacks
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "c15d709a26b1"
        columns = {row[1] for row in db.execute("PRAGMA table_info(ohlcv_history_state)")}
        assert {"symbol", "floor_requested_start", "floor_checked_at", "seam_signature"} <= columns
        db.execute("INSERT INTO ohlcv_history_state (symbol, seam_date) VALUES ('TEST', '2016-01-04')")
    alembic("downgrade", "f62a9e1b4c70")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT * FROM ohlcv_daily").fetchall() == [("TEST", "2010-01-04", 12.3456)]
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='ohlcv_history_state'").fetchall()
