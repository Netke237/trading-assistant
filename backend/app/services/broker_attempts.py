"""Durable submission ledger. Routes must not treat the legacy window as authority.

Dispatch is authorized only after state `dispatching` commits. Preparing and
dispatching survive restart and never become a second leader. Time, a new
process, and the internal short-success view cannot authorize a POST.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Mapping

from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from app.database import AsyncSessionLocal
from app.models.broker_attempt import BrokerAttempt, ExposureGuard, ExposureHold
from app.models.portfolio import PortfolioPositionModel

MAX_INT = 2**63 - 1
GUARD_ID = "global"
LEGACY_SUCCESS_WINDOW = timedelta(seconds=3)
UNRESOLVED_STATES = frozenset({"preparing", "dispatching", "outcome-unknown"})
SUCCESS_STATES = frozenset({"submitted", "filled"})
TERMINAL_STATES = frozenset({"proven-not-submitted", "submitted", "filled", "outcome-unknown"})
_FORWARD = {
    "preparing": frozenset({"outcome-unknown"}),
    "dispatching": frozenset({"proven-not-submitted", "submitted", "filled", "outcome-unknown"}),
}
_FIELDS = frozenset({
    "kind", "broker", "symbol", "instrument", "action", "effect",
    "quantity", "order_type", "limit", "tif", "conid",
})
_KINDS = frozenset({"stock", "option"})
_BROKERS = frozenset({"ibkr_paper", "tradier_paper", "alpaca_paper", "tastytrade_paper"})
_ACTIONS = frozenset({"BUY", "SELL"})
_EFFECTS = frozenset({"OPEN", "CLOSE"})
_ORDER_TYPES = frozenset({"MKT", "LMT"})
_TIFS = frozenset({"DAY", "GTC"})


class BrokerAttemptError(Exception):
    pass


class BrokerAttemptConflict(BrokerAttemptError):
    status_code = 409


class BrokerAttemptRejected(BrokerAttemptError):
    """Payload or identity cannot be stored. Nothing is authorized."""


class BrokerAttemptStorageError(BrokerAttemptError):
    """Missing or uncommitted storage. No dispatch authorization."""


class BrokerAttemptNotFound(BrokerAttemptError):
    status_code = 404


@dataclass(frozen=True)
class ClaimResult:
    attempt_id: str
    state: str
    leader: bool
    authorized: bool
    payload_canonical: str
    fingerprint: str
    verification_version: int
    dispatch_authorized_at: datetime | None
    broker_order_id: str | None
    broker_status: str | None
    broker_response: str | None
    saved_rec_id: str | None


@dataclass(frozen=True)
class LegacyShortSuccessView:
    """Internal compatibility read. `authorized` is always false."""

    matched_attempt_id: str | None
    state: str | None
    expired_known_success: bool
    authorized: bool = False


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _insert(db, model):
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        return sqlite_insert(model)
    if dialect == "postgresql":
        return postgres_insert(model)
    raise BrokerAttemptStorageError(f"unsupported attempt database: {dialect}")


def _token(value, allowed: frozenset, label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise BrokerAttemptRejected(f"{label} is inconsistent")
    return value


def _exact_text(value, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise BrokerAttemptRejected(f"{label} is inconsistent")
    return value


def _quantity(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > MAX_INT:
        raise BrokerAttemptRejected("quantity must be a positive integer")
    return value


def _conid(value, kind: str):
    if kind == "stock":
        if value is not None:
            raise BrokerAttemptRejected("stock payload cannot include a conid")
        return None
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > MAX_INT:
        raise BrokerAttemptRejected("conid must be a positive integer")
    return value


def _decimal_string(value) -> str:
    if isinstance(value, bool) or isinstance(value, float) or value is None:
        raise BrokerAttemptRejected("limit must be an exact decimal string or integer")
    if isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, Decimal):
        number = value
    elif isinstance(value, str):
        if not value or value.strip() != value:
            raise BrokerAttemptRejected("limit must be an exact decimal string or integer")
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise BrokerAttemptRejected("limit must be an exact decimal string or integer") from exc
    else:
        raise BrokerAttemptRejected("limit must be an exact decimal string or integer")
    if not number.is_finite() or number <= 0:
        raise BrokerAttemptRejected("limit must be a positive finite price")
    return format(number.normalize(), "f")


def canonicalize_payload(payload: Mapping) -> tuple[str, str]:
    if not isinstance(payload, Mapping) or isinstance(payload, (str, bytes)):
        raise BrokerAttemptRejected("payload must be an object")
    if set(payload) != _FIELDS:
        raise BrokerAttemptRejected("payload fields are inconsistent")
    kind = _token(payload["kind"], _KINDS, "kind")
    body = {
        "kind": kind,
        "broker": _token(payload["broker"], _BROKERS, "broker"),
        "symbol": _exact_text(payload["symbol"], "symbol"),
        "instrument": _exact_text(payload["instrument"], "instrument"),
        "action": _token(payload["action"], _ACTIONS, "action"),
        "effect": _token(payload["effect"], _EFFECTS, "effect"),
        "quantity": _quantity(payload["quantity"]),
        "order_type": _token(payload["order_type"], _ORDER_TYPES, "order type"),
        "tif": _token(payload["tif"], _TIFS, "tif"),
        "conid": _conid(payload["conid"], kind),
    }
    order_type = body["order_type"]
    limit = payload["limit"]
    if order_type == "MKT":
        if limit is not None:
            raise BrokerAttemptRejected("market order cannot carry a limit")
        body["limit"] = None
    else:
        if limit is None:
            raise BrokerAttemptRejected("limit order requires an exact limit")
        body["limit"] = _decimal_string(limit)
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return canonical, fingerprint


def _check_attempt_id(attempt_id) -> str:
    if not isinstance(attempt_id, str) or not attempt_id or attempt_id.strip() != attempt_id or len(attempt_id) > 128:
        raise BrokerAttemptRejected("attempt id is inconsistent")
    return attempt_id


def _check_saved_rec_id(saved_rec_id):
    if saved_rec_id is None:
        return None
    if not isinstance(saved_rec_id, str) or not saved_rec_id or saved_rec_id.strip() != saved_rec_id or len(saved_rec_id) > 128:
        raise BrokerAttemptRejected("saved row reference is inconsistent")
    return saved_rec_id


_ACCEPTED_STATUS = frozenset({
    "accepted", "presubmitted", "submitted", "pending", "pendingsubmit", "pendingnew", "new",
})
_VERIFY_STATE = {
    "definitely-not-submitted": "proven-not-submitted",
    "submitted": "submitted",
    "filled": "filled",
    "canceled-after-submission": "submitted",
    "partial": "submitted",
}
DEFERRED_COVERAGE_NOTE = (
    "Precise quantity release is deferred. This order keeps its exposure coverage."
)


def _status_token(value) -> str:
    return str(value or "").strip().lower().replace("orderstatus.", "").replace(" ", "").replace("_", "")


def outcome_label(state: str, broker_status, verification_outcome: str | None = None) -> str:
    """Accepted broker evidence is submitted. It is never displayed as filled."""
    status = _status_token(broker_status)
    if status in _ACCEPTED_STATUS:
        return "submitted"
    if verification_outcome == "partial":
        return "partial"
    if verification_outcome == "canceled-after-submission":
        return "canceled after submission"
    if verification_outcome == "definitely-not-submitted" or state == "proven-not-submitted":
        return "not submitted"
    if verification_outcome == "filled" or state == "filled" or status in {"filled", "fill"}:
        return "filled"
    if verification_outcome == "submitted" or state == "submitted":
        return "submitted"
    if state == "outcome-unknown":
        return "outcome unknown"
    if state in {"preparing", "dispatching"}:
        return "unverified"
    return state or "unverified"


def coverage_note(verification_outcome: str | None) -> str | None:
    if verification_outcome in {"partial", "canceled-after-submission"}:
        return DEFERRED_COVERAGE_NOTE
    return None


@dataclass(frozen=True)
class AttemptView:
    attempt_id: str
    state: str
    payload_canonical: str
    fingerprint: str
    verification_version: int
    broker_order_id: str | None
    broker_status: str | None
    broker_response: str | None
    saved_rec_id: str | None
    verification_outcome: str | None
    verification_note: str | None
    created_at: datetime
    updated_at: datetime


def _view(row: BrokerAttempt) -> AttemptView:
    return AttemptView(
        attempt_id=row.id,
        state=row.state,
        payload_canonical=row.payload_canonical,
        fingerprint=row.payload_fingerprint,
        verification_version=row.verification_version,
        broker_order_id=row.broker_order_id,
        broker_status=row.broker_status,
        broker_response=row.broker_response,
        saved_rec_id=row.saved_rec_id,
        verification_outcome=row.verification_outcome,
        verification_note=row.verification_note,
        created_at=_as_utc(row.created_at),
        updated_at=_as_utc(row.updated_at),
    )


def _from_row(row: BrokerAttempt, *, leader: bool, authorized: bool) -> ClaimResult:
    authorized_at = row.dispatch_authorized_at
    return ClaimResult(
        attempt_id=row.id,
        state=row.state,
        leader=leader,
        authorized=authorized,
        payload_canonical=row.payload_canonical,
        fingerprint=row.payload_fingerprint,
        verification_version=row.verification_version,
        dispatch_authorized_at=None if authorized_at is None else _as_utc(authorized_at),
        broker_order_id=row.broker_order_id,
        broker_status=row.broker_status,
        broker_response=row.broker_response,
        saved_rec_id=row.saved_rec_id,
    )


def _prepared_matches(row, body: dict) -> bool:
    prepared = row.prepared_order
    if not isinstance(prepared, dict) or body.get("effect") != "OPEN":
        return False
    if row.qty != body.get("quantity"):
        return False
    for key in ("instrument", "symbol", "action", "effect", "quantity", "order_type", "limit"):
        if prepared.get(key) != body.get(key):
            return False
    for key in ("broker", "tif", "kind", "conid"):
        if key in prepared and prepared.get(key) != body.get(key):
            return False
    return True


class BrokerAttemptService:
    def __init__(self, session_factory=None, *, clock=None, crash_at=None):
        self.sessions = session_factory or AsyncSessionLocal
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        # Test seam only. Production leaves this unset; it never expires a claim.
        self.crash_at = crash_at

    def _now(self) -> datetime:
        return _as_utc(self.clock())

    async def _lock(self, db) -> None:
        if db.get_bind().dialect.name == "sqlite":
            await db.execute(text("PRAGMA busy_timeout=30000"))
        await db.execute(
            _insert(db, ExposureGuard).values(id=GUARD_ID, guarded=0).on_conflict_do_nothing(index_elements=["id"])
        )
        await db.execute(update(ExposureGuard).where(ExposureGuard.id == GUARD_ID).values(guarded=ExposureGuard.guarded))

    async def _unresolved_other(self, db, fingerprint: str, attempt_id: str):
        return (await db.execute(
            select(BrokerAttempt.id).where(
                BrokerAttempt.payload_fingerprint == fingerprint,
                BrokerAttempt.id != attempt_id,
                BrokerAttempt.state.in_(tuple(UNRESOLVED_STATES)),
            )
        )).first()

    async def claim(self, attempt_id: str, payload: Mapping, *, saved_rec_id: str | None = None) -> ClaimResult:
        canonical, fingerprint = canonicalize_payload(payload)
        attempt_id = _check_attempt_id(attempt_id)
        saved_rec_id = _check_saved_rec_id(saved_rec_id)
        try:
            async with self.sessions() as db:
                try:
                    existing = await self._prepare(db, attempt_id, canonical, fingerprint, saved_rec_id)
                except IntegrityError:
                    existing = await self._replay_after_conflict(db, attempt_id, canonical, fingerprint)
                if existing is not None:
                    return existing
                if self.crash_at == "after_preparing":
                    raise BrokerAttemptStorageError("crashed while preparing")
                return await self._mark_dispatching(db, attempt_id, canonical)
        except (BrokerAttemptConflict, BrokerAttemptRejected, BrokerAttemptStorageError):
            raise
        except Exception as exc:
            raise BrokerAttemptStorageError("attempt storage failed closed") from exc

    async def _prepare(self, db, attempt_id, canonical, fingerprint, saved_rec_id):
        now = self._now()
        async with db.begin():
            await self._lock(db)
            current = await db.get(BrokerAttempt, attempt_id)
            if current is not None:
                if current.payload_canonical != canonical:
                    raise BrokerAttemptConflict("Attempt ID already belongs to a different order")
                return _from_row(current, leader=False, authorized=False)
            if await self._unresolved_other(db, fingerprint, attempt_id) is not None:
                raise BrokerAttemptConflict("Unresolved order fingerprint already exists")
            db.add(BrokerAttempt(
                id=attempt_id,
                payload_canonical=canonical,
                payload_fingerprint=fingerprint,
                state="preparing",
                broker_response=None,
                broker_order_id=None,
                broker_status=None,
                saved_rec_id=saved_rec_id,
                verification_outcome=None,
                verification_note=None,
                verification_version=0,
                created_at=now,
                updated_at=now,
                dispatch_authorized_at=None,
            ))
            await db.flush()
            if self.crash_at == "before_commit":
                raise BrokerAttemptStorageError("claim commit failed")
        return None

    async def _replay_after_conflict(self, db, attempt_id, canonical, fingerprint):
        async with db.begin():
            await self._lock(db)
            current = await db.get(BrokerAttempt, attempt_id)
            if current is not None:
                if current.payload_canonical != canonical:
                    raise BrokerAttemptConflict("Attempt ID already belongs to a different order")
                return _from_row(current, leader=False, authorized=False)
            if await self._unresolved_other(db, fingerprint, attempt_id) is not None:
                raise BrokerAttemptConflict("Unresolved order fingerprint already exists")
        raise BrokerAttemptStorageError("attempt insert conflicted without a stored row")

    async def _mark_dispatching(self, db, attempt_id, canonical) -> ClaimResult:
        now = self._now()
        async with db.begin():
            await self._lock(db)
            current = await db.get(BrokerAttempt, attempt_id)
            if current is None:
                raise BrokerAttemptStorageError("prepared attempt missing before dispatch")
            if current.payload_canonical != canonical or current.state != "preparing":
                return _from_row(current, leader=False, authorized=False)
            version = current.verification_version + 1
            changed = await db.execute(
                update(BrokerAttempt)
                .where(
                    BrokerAttempt.id == attempt_id,
                    BrokerAttempt.state == "preparing",
                    BrokerAttempt.verification_version == current.verification_version,
                    BrokerAttempt.payload_canonical == canonical,
                )
                .values(
                    state="dispatching",
                    verification_version=version,
                    dispatch_authorized_at=now,
                    updated_at=now,
                )
            )
            if changed.rowcount != 1:
                await db.refresh(current)
                return _from_row(current, leader=False, authorized=False)
            await db.refresh(current)
            result = _from_row(current, leader=True, authorized=True)
        if self.crash_at == "after_dispatching":
            raise BrokerAttemptStorageError("crashed after dispatching committed")
        if result.state != "dispatching" or result.dispatch_authorized_at is None:
            raise BrokerAttemptStorageError("dispatch claim did not commit")
        return result

    async def record_outcome(
        self,
        attempt_id: str,
        new_state: str,
        *,
        expected_version: int,
        broker_order_id: str | None = None,
        broker_status: str | None = None,
        broker_response: str | None = None,
    ) -> ClaimResult:
        attempt_id = _check_attempt_id(attempt_id)
        if new_state not in TERMINAL_STATES:
            raise BrokerAttemptRejected("unknown attempt outcome")
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 0:
            raise BrokerAttemptRejected("attempt version is inconsistent")
        for label, value in (("broker order id", broker_order_id), ("broker status", broker_status), ("broker response", broker_response)):
            if value is not None and not isinstance(value, str):
                raise BrokerAttemptRejected(f"{label} is inconsistent")
        try:
            async with self.sessions() as db:
                async with db.begin():
                    await self._lock(db)
                    current = await db.get(BrokerAttempt, attempt_id)
                    if current is None:
                        raise BrokerAttemptStorageError("attempt is not stored")
                    if current.state in TERMINAL_STATES or current.verification_version != expected_version:
                        raise BrokerAttemptConflict("attempt outcome is already decided or the version is stale")
                    if new_state not in _FORWARD.get(current.state, frozenset()):
                        raise BrokerAttemptConflict("attempt cannot move to that outcome")
                    version = current.verification_version + 1
                    now = self._now()
                    values = {"state": new_state, "verification_version": version, "updated_at": now}
                    if broker_order_id is not None:
                        values["broker_order_id"] = broker_order_id
                    if broker_status is not None:
                        values["broker_status"] = broker_status
                    if broker_response is not None:
                        values["broker_response"] = broker_response
                    changed = await db.execute(
                        update(BrokerAttempt)
                        .where(
                            BrokerAttempt.id == attempt_id,
                            BrokerAttempt.state == current.state,
                            BrokerAttempt.verification_version == expected_version,
                        )
                        .values(**values)
                    )
                    if changed.rowcount != 1:
                        raise BrokerAttemptConflict("attempt outcome is already decided or the version is stale")
                    if new_state == "proven-not-submitted":
                        await db.execute(
                            update(PortfolioPositionModel)
                            .where(PortfolioPositionModel.order_attempt_id == attempt_id)
                            .values(order_attempt_id=None)
                        )
                    await db.refresh(current)
                    return _from_row(current, leader=False, authorized=False)
        except (BrokerAttemptConflict, BrokerAttemptRejected, BrokerAttemptStorageError):
            raise
        except Exception as exc:
            raise BrokerAttemptStorageError("attempt storage failed closed") from exc

    async def read(self, attempt_id: str) -> ClaimResult:
        attempt_id = _check_attempt_id(attempt_id)
        try:
            async with self.sessions() as db:
                async with db.begin():
                    await self._lock(db)
                    current = await db.get(BrokerAttempt, attempt_id)
                    if current is None:
                        raise BrokerAttemptStorageError("attempt is not stored")
                    return _from_row(current, leader=False, authorized=False)
        except (BrokerAttemptConflict, BrokerAttemptRejected, BrokerAttemptStorageError):
            raise
        except Exception as exc:
            raise BrokerAttemptStorageError("attempt storage failed closed") from exc

    async def list_unresolved(self) -> list[AttemptView]:
        try:
            async with self.sessions() as db:
                async with db.begin():
                    await self._lock(db)
                    rows = (await db.execute(
                        select(BrokerAttempt)
                        .where(BrokerAttempt.state.in_(tuple(UNRESOLVED_STATES)))
                        .order_by(BrokerAttempt.created_at, BrokerAttempt.id)
                    )).scalars().all()
                    return [_view(row) for row in rows]
        except (BrokerAttemptConflict, BrokerAttemptRejected, BrokerAttemptStorageError):
            raise
        except Exception as exc:
            raise BrokerAttemptStorageError("attempt storage failed closed") from exc

    async def get_attempt(self, attempt_id: str) -> AttemptView:
        attempt_id = _check_attempt_id(attempt_id)
        try:
            async with self.sessions() as db:
                async with db.begin():
                    await self._lock(db)
                    current = await db.get(BrokerAttempt, attempt_id)
                    if current is None:
                        raise BrokerAttemptNotFound("attempt is not stored")
                    return _view(current)
        except (BrokerAttemptNotFound, BrokerAttemptConflict, BrokerAttemptRejected, BrokerAttemptStorageError):
            raise
        except Exception as exc:
            raise BrokerAttemptStorageError("attempt storage failed closed") from exc

    async def verify(self, attempt_id: str, outcome: str, note: str, expected_version: int) -> AttemptView:
        """Record a user assertion. Does not call a broker or mint another id."""
        attempt_id = _check_attempt_id(attempt_id)
        if outcome not in _VERIFY_STATE:
            raise BrokerAttemptRejected("verification outcome is not an explicit broker assertion")
        if not isinstance(note, str):
            raise BrokerAttemptRejected("broker evidence note is required")
        note = note.strip()
        if not note or len(note) > 4000:
            raise BrokerAttemptRejected("broker evidence note is required")
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 0:
            raise BrokerAttemptRejected("attempt version is inconsistent")
        new_state = _VERIFY_STATE[outcome]
        try:
            async with self.sessions() as db:
                async with db.begin():
                    await self._lock(db)
                    current = await db.get(BrokerAttempt, attempt_id)
                    if current is None:
                        raise BrokerAttemptNotFound("attempt is not stored")
                    if current.state not in UNRESOLVED_STATES or current.verification_version != expected_version:
                        raise BrokerAttemptConflict("attempt is no longer unverified or the version is stale")
                    now = self._now()
                    changed = await db.execute(
                        update(BrokerAttempt)
                        .where(
                            BrokerAttempt.id == attempt_id,
                            BrokerAttempt.state == current.state,
                            BrokerAttempt.verification_version == expected_version,
                        )
                        .values(
                            state=new_state,
                            verification_outcome=outcome,
                            verification_note=note,
                            verification_version=expected_version + 1,
                            updated_at=now,
                        )
                    )
                    if changed.rowcount != 1:
                        raise BrokerAttemptConflict("attempt is no longer unverified or the version is stale")
                    if new_state == "proven-not-submitted":
                        await db.execute(
                            update(PortfolioPositionModel)
                            .where(PortfolioPositionModel.order_attempt_id == attempt_id)
                            .values(order_attempt_id=None)
                        )
                        await db.execute(
                            delete(ExposureHold).where(ExposureHold.attempt_id == attempt_id)
                        )
                    await db.refresh(current)
                    return _view(current)
        except (BrokerAttemptNotFound, BrokerAttemptConflict, BrokerAttemptRejected, BrokerAttemptStorageError):
            raise
        except Exception as exc:
            raise BrokerAttemptStorageError("attempt storage failed closed") from exc

    async def claim_production(
        self,
        payload: Mapping,
        *,
        attempt_id: str | None = None,
        saved_rec_id: str | None = None,
    ) -> ClaimResult:
        """Resolve one durable id, then claim it. Never a short-window grant."""
        canonical, fingerprint = canonicalize_payload(payload)
        saved_rec_id = _check_saved_rec_id(saved_rec_id)
        body = json.loads(canonical)
        if attempt_id is not None:
            attempt_id = _check_attempt_id(attempt_id)
            if len(attempt_id) > 64:
                raise BrokerAttemptRejected("attempt id is inconsistent")
            result = await self.claim(attempt_id, body, saved_rec_id=saved_rec_id)
            if result.authorized:
                await self._bind_prepared(result.attempt_id, body, saved_rec_id)
                if result.saved_rec_id is None:
                    linked = await self._stored_saved_rec_id(result.attempt_id)
                    if linked is not None:
                        result = replace(result, saved_rec_id=linked)
            return result
        try:
            async with self.sessions() as db:
                prepared = await self._prepare_idless(db, canonical, fingerprint, body, saved_rec_id)
                if isinstance(prepared, ClaimResult):
                    return prepared
                if self.crash_at == "after_preparing":
                    raise BrokerAttemptStorageError("crashed while preparing")
                return await self._mark_dispatching(db, prepared, canonical)
        except (BrokerAttemptConflict, BrokerAttemptRejected, BrokerAttemptStorageError):
            raise
        except Exception as exc:
            raise BrokerAttemptStorageError("attempt storage failed closed") from exc

    async def _latest(self, db, fingerprint: str, states):
        rows = (await db.execute(
            select(BrokerAttempt).where(
                BrokerAttempt.payload_fingerprint == fingerprint,
                BrokerAttempt.state.in_(tuple(states)),
            )
        )).scalars().all()
        if not rows:
            return None
        return max(rows, key=lambda row: _as_utc(row.updated_at))

    async def _one_prepared(self, db, body: dict, saved_rec_id: str | None):
        if body.get("effect") != "OPEN":
            return None
        stmt = select(PortfolioPositionModel).where(PortfolioPositionModel.prepared_order.is_not(None))
        if saved_rec_id:
            stmt = stmt.where(PortfolioPositionModel.rec_id == saved_rec_id)
        rows = (await db.execute(stmt)).scalars().all()
        matched = [row for row in rows if _prepared_matches(row, body)]
        if len(matched) != 1:
            return None
        return matched[0]

    async def _prepare_idless(self, db, canonical: str, fingerprint: str, body: dict, saved_rec_id):
        now = self._now()
        async with db.begin():
            await self._lock(db)
            unresolved = await self._latest(db, fingerprint, UNRESOLVED_STATES)
            if unresolved is not None:
                return _from_row(unresolved, leader=False, authorized=False)
            row = await self._one_prepared(db, body, saved_rec_id)
            if row is not None and row.order_attempt_id:
                owner = await db.get(BrokerAttempt, row.order_attempt_id)
                if owner is None:
                    raise BrokerAttemptStorageError("prepared row owner is missing")
                if owner.payload_canonical != canonical:
                    raise BrokerAttemptConflict("Prepared row belongs to a different order")
                return _from_row(owner, leader=False, authorized=False)
            if row is None:
                success = await self._latest(db, fingerprint, SUCCESS_STATES)
                if success is not None:
                    return _from_row(success, leader=False, authorized=False)
            new_id = uuid.uuid4().hex
            db.add(BrokerAttempt(
                id=new_id,
                payload_canonical=canonical,
                payload_fingerprint=fingerprint,
                state="preparing",
                broker_response=None,
                broker_order_id=None,
                broker_status=None,
                saved_rec_id=row.rec_id if row is not None else saved_rec_id,
                verification_outcome=None,
                verification_note=None,
                verification_version=0,
                created_at=now,
                updated_at=now,
                dispatch_authorized_at=None,
            ))
            await db.flush()
            if row is not None:
                changed = await db.execute(
                    update(PortfolioPositionModel)
                    .where(
                        PortfolioPositionModel.rec_id == row.rec_id,
                        PortfolioPositionModel.order_attempt_id.is_(None),
                    )
                    .values(order_attempt_id=new_id)
                )
                if changed.rowcount != 1:
                    raise BrokerAttemptStorageError("prepared row ownership changed")
            if self.crash_at == "before_commit":
                raise BrokerAttemptStorageError("claim commit failed")
        return new_id

    async def _stored_saved_rec_id(self, attempt_id: str) -> str | None:
        """The request session still holds the pre-bind attempt."""
        async with self.sessions() as db:
            async with db.begin():
                await self._lock(db)
                db.expire_all()
                current = await db.get(BrokerAttempt, attempt_id)
                if current is None:
                    return None
                return current.saved_rec_id

    async def _bind_prepared(self, attempt_id: str, body: dict, saved_rec_id: str | None) -> None:
        try:
            async with self.sessions() as db:
                async with db.begin():
                    await self._lock(db)
                    row = await self._one_prepared(db, body, saved_rec_id)
                    if row is None or row.order_attempt_id not in (None, attempt_id):
                        return
                    if row.order_attempt_id is None:
                        changed = await db.execute(
                            update(PortfolioPositionModel)
                            .where(
                                PortfolioPositionModel.rec_id == row.rec_id,
                                PortfolioPositionModel.order_attempt_id.is_(None),
                            )
                            .values(order_attempt_id=attempt_id)
                        )
                        if changed.rowcount != 1:
                            return
                    await db.execute(
                        update(BrokerAttempt)
                        .where(BrokerAttempt.id == attempt_id, BrokerAttempt.saved_rec_id.is_(None))
                        .values(saved_rec_id=row.rec_id, updated_at=self._now())
                    )
        except Exception as exc:
            raise BrokerAttemptStorageError("attempt storage failed closed") from exc

    async def legacy_short_success_compatible(self, payload: Mapping) -> LegacyShortSuccessView:
        """Historical three-second success window as a read. Never a dispatch grant.

        Production routes resolve a durable id and call `claim` instead.
        """
        _canonical, fingerprint = canonicalize_payload(payload)
        try:
            async with self.sessions() as db:
                async with db.begin():
                    await self._lock(db)
                    rows = (await db.execute(
                        select(BrokerAttempt).where(BrokerAttempt.payload_fingerprint == fingerprint)
                    )).scalars().all()
                    view = self._legacy_view(rows)
            if view.authorized:
                raise BrokerAttemptStorageError("legacy window must not authorize dispatch")
            return view
        except (BrokerAttemptConflict, BrokerAttemptRejected, BrokerAttemptStorageError):
            raise
        except Exception as exc:
            raise BrokerAttemptStorageError("attempt storage failed closed") from exc

    def _legacy_view(self, rows) -> LegacyShortSuccessView:
        unresolved = [row for row in rows if row.state in UNRESOLVED_STATES]
        if unresolved:
            chosen = max(unresolved, key=lambda row: _as_utc(row.updated_at))
            return LegacyShortSuccessView(chosen.id, chosen.state, False, False)
        successes = [row for row in rows if row.state in SUCCESS_STATES]
        if not successes:
            return LegacyShortSuccessView(None, None, False, False)
        chosen = max(successes, key=lambda row: _as_utc(row.updated_at))
        expired = self._now() - _as_utc(chosen.updated_at) > LEGACY_SUCCESS_WINDOW
        return LegacyShortSuccessView(chosen.id, chosen.state, expired, False)
