"""Atomic daily risk budget, using the application's database and event loop."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from typing import Callable
from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from app.database import AsyncSessionLocal
from app.models.daily_risk import DailyRiskAttempt, DailyRiskBudget, DailyRiskLoss
from app.models.closed_position import ClosedPositionModel
from app.services import portfolio_risk

MAX_CENTS = 2**63 - 1


class DailyRiskError(RuntimeError):
    pass


class _UTCDateChanged(Exception):
    """Roll back a transaction whose lock wait crossed the UTC boundary."""


def _number(value, *, positive=False) -> Decimal:
    try:
        if isinstance(value, bool):
            raise ValueError('boolean money')
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or (positive and result <= 0):
            raise ValueError('nonfinite or invalid money')
        return result
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise DailyRiskError('Daily risk budget requires finite valid money') from exc


def _cents(value: Decimal, *, allowance=False) -> int:
    result = int((value * 100).to_integral_value(rounding=ROUND_FLOOR if allowance else ROUND_CEILING))
    if result < 0 or result > MAX_CENTS:
        raise DailyRiskError('Daily risk budget exceeds integer money capacity')
    return result


def _utc(value: datetime) -> datetime:
    # SQLite returns naive values for UTC DateTime columns.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _insert(db, model):
    dialect = db.get_bind().dialect.name
    if dialect == 'sqlite':
        return sqlite_insert(model)
    if dialect == 'postgresql':
        return postgres_insert(model)
    raise DailyRiskError(f'Unsupported daily risk database: {dialect}')


@dataclass(frozen=True)
class Reservation:
    id: str
    day: str
    reserved_cents: int
    state: str


def _history():
    from app.services.auto_trader import auto_trader
    return auto_trader.get_state().history


class DailyRiskService:
    def __init__(self, session_factory=None, *, config_provider=None, history_provider=None, clock=None):
        self.sessions = session_factory or AsyncSessionLocal
        self.config = config_provider or portfolio_risk._load_config
        self.history = history_provider or _history
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _limit(self) -> int:
        try:
            config = self.config()
            account = _number(portfolio_risk.account_value(config), positive=True)
            fraction = _number(config.get('auto_trade', {}).get('max_daily_loss_pct', .02))
            if fraction > 1:
                raise DailyRiskError('Daily risk fraction must be between zero and one')
            return _cents(account * fraction, allowance=True)
        except DailyRiskError:
            raise
        except Exception as exc:
            raise DailyRiskError(f'Cannot read daily risk configuration: {exc}') from exc

    async def _lock_day(self, db, day):
        await db.execute(_insert(db, DailyRiskBudget).values(day=day, reserved_cents=0, loss_cents=0).on_conflict_do_nothing(index_elements=['day']))
        # UPDATE locks an existing row on Postgres and serializes SQLite writers.
        await db.execute(update(DailyRiskBudget).where(DailyRiskBudget.day == day).values(reserved_cents=DailyRiskBudget.reserved_cents))

    async def record_realized_loss(self, db, closed_row):
        pnl = _number(abs(closed_row.realized_pnl_dollar))
        amount = _cents(pnl) if closed_row.realized_pnl_dollar < 0 else 0
        if not amount:
            return
        closed_at = closed_row.closed_at
        if closed_at is None:
            closed_at = self.clock()
            closed_row.closed_at = closed_at
        day = _utc(closed_at).date().isoformat()
        await self._lock_day(db, day)
        inserted = await db.execute(_insert(db, DailyRiskLoss).values(closed_id=closed_row.id, day=day, loss_cents=amount).on_conflict_do_nothing(index_elements=['closed_id']))
        if inserted.rowcount:
            changed = await db.execute(update(DailyRiskBudget).where(DailyRiskBudget.day == day, DailyRiskBudget.loss_cents <= MAX_CENTS - amount - DailyRiskBudget.reserved_cents).values(loss_cents=DailyRiskBudget.loss_cents + amount))
            if not changed.rowcount:
                raise DailyRiskError('Recorded daily losses exceed integer money capacity')

    async def _bootstrap(self, db, day):
        start = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
        rows = (await db.execute(select(ClosedPositionModel).where(ClosedPositionModel.closed_at >= start, ClosedPositionModel.closed_at < start + timedelta(days=1), ClosedPositionModel.realized_pnl_dollar < 0))).scalars().all()
        for row in rows:
            await self.record_realized_loss(db, row)
        from app.services.auto_trader import _is_rejected_status
        for row in self.history():
            if _is_rejected_status(row.get('status', '')):
                continue
            timestamp = row.get('timestamp')
            if not timestamp or _utc(datetime.fromisoformat(timestamp)).date().isoformat() != day:
                continue
            risk = _number(row.get('premium_at_risk') or 0)
            if not risk:
                continue
            attempt_id = row.get('attempt_id')
            if not attempt_id:
                raise DailyRiskError('Cannot import retained auto risk without an attempt ID')
            amount = _cents(risk)
            inserted = await db.execute(_insert(db, DailyRiskAttempt).values(id=attempt_id, day=day, reserved_cents=amount, state='retained', outcome=str(row.get('status', '')), instrument=str(row.get('symbol', 'legacy-auto')), source='legacy-auto', quantity=0, price='0', multiplier=100).on_conflict_do_nothing(index_elements=['id']))
            if inserted.rowcount:
                changed = await db.execute(update(DailyRiskBudget).where(DailyRiskBudget.day == day, DailyRiskBudget.reserved_cents <= MAX_CENTS - amount - DailyRiskBudget.loss_cents).values(reserved_cents=DailyRiskBudget.reserved_cents + amount))
                if not changed.rowcount:
                    raise DailyRiskError('Imported auto risk exceeds integer money capacity')

    async def reserve(self, attempt_id: str, *, instrument: str, quantity: int, price: float, source: str, multiplier: int = 1) -> Reservation:
        if not attempt_id or len(attempt_id) > 64 or not instrument or not source:
            raise DailyRiskError('Opening risk requires an attempt ID, instrument and source')
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0 or quantity > MAX_CENTS or isinstance(multiplier, bool) or not isinstance(multiplier, int) or multiplier <= 0 or multiplier > MAX_CENTS:
            raise DailyRiskError('Opening risk requires positive integer quantity and multiplier')
        payment = _number(price, positive=True)
        amount = _cents(payment * quantity * multiplier)
        # Each retry releases the prior day's locks before acquiring another
        # day, so midnight does not create a cross-day lock ordering cycle.
        for _ in range(3):
            day = _utc(self.clock()).date().isoformat()
            try:
                async with self.sessions() as db:
                    # Persist imported risk even when the opening is refused.
                    async with db.begin():
                        await self._lock_day(db, day)
                        if _utc(self.clock()).date().isoformat() != day:
                            raise _UTCDateChanged()
                        await self._bootstrap(db, day)
                    async with db.begin():
                        await self._lock_day(db, day)
                        if _utc(self.clock()).date().isoformat() != day:
                            raise _UTCDateChanged()
                        limit = self._limit()
                        existing = await db.get(DailyRiskAttempt, attempt_id)
                        if existing:
                            if (existing.instrument, existing.quantity, Decimal(existing.price), existing.source, existing.multiplier) != (instrument, quantity, payment, source, multiplier):
                                raise DailyRiskError('Attempt ID already belongs to different opening risk')
                            if existing.state == 'released':
                                raise DailyRiskError('Released attempt ID cannot dispatch again')
                            if existing.day != day:
                                raise DailyRiskError('Attempt ID belongs to an earlier UTC day')
                            if _utc(self.clock()).date().isoformat() != day:
                                raise _UTCDateChanged()
                            return Reservation(existing.id, existing.day, existing.reserved_cents, existing.state)
                        changed = await db.execute(update(DailyRiskBudget).where(DailyRiskBudget.day == day, DailyRiskBudget.reserved_cents + DailyRiskBudget.loss_cents <= limit - amount).values(reserved_cents=DailyRiskBudget.reserved_cents + amount))
                        if not changed.rowcount:
                            raise DailyRiskError('Daily risk budget exhausted')
                        db.add(DailyRiskAttempt(id=attempt_id, day=day, reserved_cents=amount, state='retained', outcome='', instrument=instrument, source=source, quantity=quantity, price=str(payment), multiplier=multiplier))
                        await db.flush()
                        if _utc(self.clock()).date().isoformat() != day:
                            raise _UTCDateChanged()
                    return Reservation(attempt_id, day, amount, 'retained')
            except _UTCDateChanged:
                continue
        raise DailyRiskError('UTC day changed repeatedly; opening order refused')

    async def resolve(self, attempt_id: str, *, definitely_not_submitted: bool, outcome: str = '') -> None:
        async with self.sessions() as db:
            async with db.begin():
                attempt = await db.get(DailyRiskAttempt, attempt_id)
                if attempt is None:
                    raise DailyRiskError('Daily risk attempt was not reserved')
                await self._lock_day(db, attempt.day)
                # Reload after the day lock: another resolver may have released it.
                await db.refresh(attempt)
                if attempt.state == 'retained' and definitely_not_submitted:
                    await db.execute(update(DailyRiskBudget).where(DailyRiskBudget.day == attempt.day).values(reserved_cents=DailyRiskBudget.reserved_cents - attempt.reserved_cents))
                    attempt.state = 'released'
                attempt.outcome = outcome


service = DailyRiskService()
reserve = service.reserve
resolve = service.resolve
record_realized_loss = service.record_realized_loss
