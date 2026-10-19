"""Database guard for portfolio exposure decisions.

The lock matches BrokerAttemptService._lock: one ExposureGuard row, insert
on conflict, then a no-op update so the write lock is held until commit.
Pending ExposureHold rows count in the capacity snapshot. A reported fill's
average entry is weighted here and is not rounded.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, select, text, update
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


class ExposureRefused(RuntimeError):
    """The fresh snapshot cannot admit this order. Nothing was reserved."""


class LinkedExposureRefused(ExposureRefused):
    """A savedRecId was supplied but the prepared row cannot cover this attempt."""


@dataclass(frozen=True)
class HeldExposure:
    attempt_id: str
    instrument: str
    quantity: int
    limit_price: str
    multiplier: int
    notional: str
    saved_rec_id: str | None
    coverage_quantity: int
    created: bool


def _price(value) -> Decimal:
    price = _money(value)
    if not price.is_finite() or price <= 0:
        raise ExposureRefused("Exposure cap cannot be judged: price is not positive")
    return price


def _limit_text(value) -> str:
    return format(_price(value).normalize(), "f")


def _coverage_credit(row, limit_price: Decimal, multiplier: int, coverage: int) -> Decimal:
    """Dollars of this order the linked open row can offset. Never more than the row."""
    if row is None or coverage <= 0:
        return Decimal(0)
    retained = min(int(coverage), int(row.qty or 0))
    if retained <= 0:
        return Decimal(0)
    credit = min(limit_price, _money(row.entry_price)) * Decimal(retained) * Decimal(int(multiplier))
    return credit if credit > 0 else Decimal(0)


def _same_hold(hold, *, instrument, quantity, limit_price, multiplier, effect, saved_rec_id) -> bool:
    return (
        str(hold.instrument) == instrument
        and int(hold.quantity) == int(quantity)
        and str(hold.limit_price) == limit_price
        and int(hold.multiplier) == int(multiplier)
        and str(hold.effect or "OPEN") == str(effect or "OPEN")
        and (hold.saved_rec_id or None) == (saved_rec_id or None)
    )


def _held(hold, *, created: bool) -> HeldExposure:
    return HeldExposure(
        attempt_id=hold.attempt_id,
        instrument=str(hold.instrument),
        quantity=int(hold.quantity),
        limit_price=str(hold.limit_price),
        multiplier=int(hold.multiplier),
        notional=str(hold.notional),
        saved_rec_id=hold.saved_rec_id,
        coverage_quantity=int(hold.coverage_quantity or 0),
        created=created,
    )


def _synthetic(total: Decimal, stock: bool) -> list[RiskPosition]:
    """One same-kind dollar row so a manual send is not refused as a duplicate symbol."""
    if total <= 0:
        return []
    unit = Decimal(1) if stock else Decimal(100)
    entry = float(total / unit)
    return [RiskPosition(
        symbol="__exposure__",
        contract_id="__exposure__|STOCK" if stock else "__exposure__|OPT",
        contracts=1,
        entry_premium=entry,
        current_price=entry,
        capital_at_risk=float(total),
    )]


class ExposureBook:
    """Short exposure transactions. `sessions` is the test/request factory; None uses the app factory."""

    def __init__(self):
        self.sessions = None

    def session_factory(self):
        if self.sessions is not None:
            return self.sessions
        from app.database import AsyncSessionLocal
        return AsyncSessionLocal

    async def admit(
        self,
        *,
        attempt_id: str,
        instrument: str,
        symbol: str,
        quantity: int,
        limit_price,
        multiplier: int,
        effect: str = "OPEN",
        action: str = "BUY",
        order_type: str = "LMT",
        saved_rec_id: str | None = None,
        gate: str = "auto",
        broker: str | None = None,
        tif: str | None = None,
        kind: str | None = None,
        conid=None,
        sessions=None,
    ) -> HeldExposure:
        """Reserve this attempt under a fresh lock. The caller's older snapshot is not read."""
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ExposureRefused("Exposure cap cannot be judged: quantity is not positive")
        if isinstance(multiplier, bool) or not isinstance(multiplier, int) or multiplier <= 0:
            raise ExposureRefused("Exposure cap cannot be judged: multiplier is not positive")
        if not attempt_id or not instrument or not symbol:
            raise ExposureRefused("Exposure cap cannot be judged: the order is incomplete")
        price = _price(limit_price)
        limit_text = format(price.normalize(), "f")
        notional = price * Decimal(quantity) * Decimal(multiplier)
        notional_text = format(notional.normalize(), "f")
        factory = sessions or self.session_factory()
        async with factory() as db:
            async with db.begin():
                await lock_exposure(db)
                db.expire_all()
                current = await db.get(ExposureHold, attempt_id)
                if current is not None:
                    if _same_hold(
                        current, instrument=instrument, quantity=quantity, limit_price=limit_text,
                        multiplier=multiplier, effect=effect, saved_rec_id=saved_rec_id,
                    ):
                        return _held(current, created=False)
                    raise ExposureRefused("Exposure hold already belongs to a different order")
                from app.models.portfolio import PortfolioPositionModel
                from app.services.broker_attempts import _prepared_matches
                from app.services.portfolio_risk import account_value, check_position_risk

                rows = (await db.execute(select(PortfolioPositionModel))).scalars().all()
                holds = await load_holds(db)
                linked = None
                coverage = 0
                match_body = {
                    "instrument": instrument,
                    "symbol": symbol,
                    "action": action,
                    "effect": effect,
                    "quantity": quantity,
                    "order_type": order_type,
                    "limit": None if order_type == "MKT" else limit_text,
                }
                if broker is not None:
                    match_body["broker"] = broker
                if tif is not None:
                    match_body["tif"] = tif
                if kind is not None:
                    match_body["kind"] = kind
                if conid is not None:
                    match_body["conid"] = conid
                if saved_rec_id:
                    linked = next((row for row in rows if row.rec_id == saved_rec_id), None)
                    owned = linked is not None and linked.order_attempt_id in (None, attempt_id)
                    if linked is None or not owned or not _prepared_matches(linked, match_body):
                        raise LinkedExposureRefused(
                            "prepared row is missing, changed, or owned by another attempt"
                        )
                    coverage = int(linked.qty or 0)
                credit = _coverage_credit(linked, price, multiplier, coverage) if gate == "manual" else Decimal(0)
                positions = capacity_positions(rows, holds)
                if gate == "manual":
                    stock = str(instrument).endswith("|STOCK")
                    total = Decimal(0)
                    for position in positions:
                        if str(position.contract_id).endswith("|STOCK") == stock:
                            total += _money(position.capital_at_risk)
                    total -= credit
                    if total < 0:
                        total = Decimal(0)
                    portfolio = _synthetic(total, stock)
                else:
                    portfolio = positions
                risk = check_position_risk(
                    symbol=symbol,
                    contract_id=instrument,
                    proposed_contracts=quantity,
                    entry_premium=float(price),
                    current_price=float(price),
                    portfolio=portfolio,
                    portfolio_value=account_value(),
                )
                if not risk.approved or risk.adjusted_size is not None:
                    raise ExposureRefused(f"Exposure cap breach: {risk.reasons}")
                if linked is not None and linked.order_attempt_id is None:
                    linked.order_attempt_id = attempt_id
                now = datetime.now(timezone.utc)
                hold = ExposureHold(
                    attempt_id=attempt_id,
                    instrument=instrument,
                    quantity=quantity,
                    limit_price=limit_text,
                    multiplier=multiplier,
                    notional=notional_text,
                    state="pending",
                    effect=effect,
                    saved_rec_id=saved_rec_id,
                    coverage_quantity=coverage,
                    created_at=now,
                    updated_at=now,
                )
                db.add(hold)
                return _held(hold, created=True)

    async def release(self, attempt_id: str, sessions=None) -> None:
        """Drop one attempt's hold. Missing rows are already released."""
        factory = sessions or self.session_factory()
        async with factory() as db:
            async with db.begin():
                await lock_exposure(db)
                await db.execute(delete(ExposureHold).where(ExposureHold.attempt_id == attempt_id))

    async def transfer(self, db, attempt_id: str, rec_id: str, coverage_quantity: int) -> None:
        """Point a hold at the row this transaction is booking. Caller commits."""
        hold = await db.get(ExposureHold, attempt_id)
        if hold is None:
            return
        hold.saved_rec_id = rec_id
        hold.coverage_quantity = int(coverage_quantity)
        hold.updated_at = datetime.now(timezone.utc)


book = ExposureBook()


async def admit(**kwargs) -> HeldExposure:
    return await book.admit(**kwargs)


async def release_hold(attempt_id: str, sessions=None) -> None:
    await book.release(attempt_id, sessions=sessions)


async def transfer_hold(db, attempt_id: str, rec_id: str, coverage_quantity: int) -> None:
    await book.transfer(db, attempt_id, rec_id, coverage_quantity)
