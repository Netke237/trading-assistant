"""Database guard for portfolio exposure decisions.

The lock matches BrokerAttemptService._lock: one ExposureGuard row, insert
on conflict, then a no-op update so the write lock is held until commit.
Pending ExposureHold rows count in the capacity snapshot. A reported fill's
average entry is weighted here and is not rounded.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models.broker_attempt import ExposureGuard, ExposureHold
from app.services.portfolio_risk import PortfolioPosition as RiskPosition
from app.services.portfolio_risk import orm_positions_to_risk

GUARD_ID = "global"


class ExposureStorageError(RuntimeError):
    pass


def _insert(db, model):
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        return sqlite_insert(model)
    if dialect == "postgresql":
        return postgres_insert(model)
    raise ExposureStorageError(f"unsupported exposure database: {dialect}")


async def lock_exposure(db) -> None:
    """Serialize capacity decisions. Caller commits or rolls back to release it."""
    if db.get_bind().dialect.name == "sqlite":
        await db.execute(text("PRAGMA busy_timeout=30000"))
    await db.execute(
        _insert(db, ExposureGuard).values(id=GUARD_ID, guarded=0).on_conflict_do_nothing(index_elements=["id"])
    )
    await db.execute(
        update(ExposureGuard).where(ExposureGuard.id == GUARD_ID).values(guarded=ExposureGuard.guarded)
    )


async def restart_read(db) -> None:
    """Drop a read snapshot so the next lock starts a fresh transaction.

    A session that already selected rows would keep that snapshot across the
    guard wait and miss the writer it waited for. Pending writes are left
    alone.
    """
    sync = db.sync_session
    if sync.new or sync.dirty or sync.deleted:
        return
    await db.rollback()


def weighted_entry(old_qty: int, old_entry: float, new_qty: int, fill_price: float) -> float:
    delta = new_qty - old_qty
    return (old_qty * old_entry + delta * fill_price) / new_qty


def exposure_breach_warning(risk, *, combined: float) -> str | None:
    """Informational warning for a fill that is stored even when over the cap."""
    if risk.approved and risk.adjusted_size is None:
        return None
    reasons = [reason for reason in risk.reasons if reason]
    if risk.adjusted_size is not None and "size_reduced_to_fit_exposure_limit" not in reasons:
        reasons.append("size_reduced_to_fit_exposure_limit")
    if not reasons:
        reasons.append("exposure_breach")
    return f"exposure_breach: {' '.join(reasons)}; combined exposure {combined:.2f}"


def _money(value) -> Decimal:
    return Decimal(str(value))


def _uncovered_notional(hold, row) -> Decimal:
    """Hold notional minus coverage the linked open row still backs.

    The credit uses the lower of the order limit and the stored entry, and
    cannot exceed the hold or the retained quantity.
    """
    notional = _money(hold.notional)
    if notional <= 0:
        return Decimal(0)
    credit = Decimal(0)
    coverage = int(hold.coverage_quantity or 0)
    if row is not None and coverage > 0:
        retained = min(coverage, int(row.qty or 0))
        if retained > 0:
            basis = min(_money(hold.limit_price), _money(row.entry_price))
            credit = basis * Decimal(retained) * Decimal(int(hold.multiplier))
            if credit > notional:
                credit = notional
    remaining = notional - credit
    return remaining if remaining > 0 else Decimal(0)


def capacity_positions(rows, holds, *, cover_rows=None) -> list[RiskPosition]:
    """Open rows plus the uncovered notional of each remaining hold."""
    positions = orm_positions_to_risk(rows)
    catalog = {row.rec_id: row for row in (rows if cover_rows is None else cover_rows)}
    for hold in holds:
        remaining = _uncovered_notional(hold, catalog.get(hold.saved_rec_id))
        if remaining <= 0:
            continue
        instrument = str(hold.instrument or "")
        symbol = instrument.split("|", 1)[0] or "HOLD"
        price = float(_money(hold.limit_price))
        positions.append(RiskPosition(
            symbol=symbol,
            contract_id=instrument,
            contracts=max(int(hold.quantity or 0), 1),
            entry_premium=price,
            current_price=price,
            capital_at_risk=float(remaining),
        ))
    return positions


async def load_holds(db):
    return (await db.execute(select(ExposureHold))).scalars().all()
