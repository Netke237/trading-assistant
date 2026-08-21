# backend/tests/test_backfill_zero_stop_migration.py
"""Regression test for the 28b49e5ff040 data migration: any pre-existing
portfolio row with stop=0 or structural_stop=0 is a stale artifact of the
bug fixed alongside it in app/routers/portfolio.py (a stock price is never
<= 0, so 0 could only ever mean "unset"), and STOP_REACHED /
STRUCTURAL_STOP_BREACHED gate on `is not None`, not `> 0` -- left in the
database, such a row keeps firing real notifications for a Bearish position
even after the app-level fix ships.

Runs the migration's exact UPDATE statements directly against a schema built
from the current ORM models, rather than through `alembic upgrade` -- this
codebase's SQLite test databases bootstrap via Base.metadata.create_all() and
never execute Alembic at all (see test_alembic_heads.py's docstring), so
there is no existing harness for driving a real upgrade() end-to-end.
"""
from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.database import Base
from app.models.portfolio import PortfolioPositionModel

_BACKFILL_SQL = (
    "UPDATE portfolio_positions SET stop = NULL WHERE stop = 0",
    "UPDATE portfolio_positions SET structural_stop = NULL WHERE structural_stop = 0",
)


def test_backfill_nulls_zero_stop_and_preserves_real_and_null_values(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as s:
        s.add(PortfolioPositionModel(
            rec_id="REC-ZERO", symbol="AAPL", contract="AAPL|STOCK", direction="Bearish",
            entry_price=100.0, qty=1, entry_date="2026-01-01", stop=0, structural_stop=0,
        ))
        s.add(PortfolioPositionModel(
            rec_id="REC-REAL", symbol="MSFT", contract="MSFT|STOCK", direction="Bullish",
            entry_price=100.0, qty=1, entry_date="2026-01-01", stop=95.0, structural_stop=90.0,
        ))
        s.add(PortfolioPositionModel(
            rec_id="REC-NULL", symbol="TSLA", contract="TSLA|STOCK", direction="Bullish",
            entry_price=100.0, qty=1, entry_date="2026-01-01", stop=None, structural_stop=None,
        ))
        s.commit()

    with engine.begin() as conn:
        for stmt in _BACKFILL_SQL:
            conn.execute(text(stmt))

    with Session() as s:
        def _fetch(rec_id: str) -> PortfolioPositionModel:
            return s.query(PortfolioPositionModel).filter_by(rec_id=rec_id).one()

        zero = _fetch("REC-ZERO")
        real = _fetch("REC-REAL")
        already_null = _fetch("REC-NULL")

    assert zero.stop is None
    assert zero.structural_stop is None
    assert real.stop == 95.0
    assert real.structural_stop == 90.0
    assert already_null.stop is None
    assert already_null.structural_stop is None
