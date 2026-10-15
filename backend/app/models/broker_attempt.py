"""Immutable broker submission attempts and the exposure write guard.

Hold rows are created for later reservation. Nothing here cascades from
Portfolio or closed-position history.
"""
from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Index, Integer, String, Text, text

from app.database import Base

_UNRESOLVED = "state IN ('preparing', 'dispatching', 'outcome-unknown')"


class BrokerAttempt(Base):
    __tablename__ = "broker_attempts"

    id = Column(String, primary_key=True)
    payload_canonical = Column(Text, nullable=False)
    payload_fingerprint = Column(String(64), nullable=False)
    state = Column(String(32), nullable=False)
    broker_response = Column(Text, nullable=True)
    broker_order_id = Column(String, nullable=True)
    broker_status = Column(String, nullable=True)
    saved_rec_id = Column(String, nullable=True)
    verification_outcome = Column(String, nullable=True)
    verification_note = Column(Text, nullable=True)
    verification_version = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    dispatch_authorized_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        CheckConstraint(
            "state IN ('preparing', 'dispatching', 'proven-not-submitted', 'submitted', 'filled', 'outcome-unknown')",
            name="ck_broker_attempts_state",
        ),
        Index("ix_broker_attempts_payload_fingerprint", "payload_fingerprint"),
        Index(
            "uq_broker_attempts_unresolved_fingerprint",
            "payload_fingerprint",
            unique=True,
            sqlite_where=text(_UNRESOLVED),
            postgresql_where=text(_UNRESOLVED),
        ),
    )


class ExposureGuard(Base):
    """Singleton write lock shared by attempt identity and later exposure decisions."""

    __tablename__ = "exposure_guards"

    id = Column(String(16), primary_key=True)
    guarded = Column(Integer, nullable=False)


class ExposureHold(Base):
    """Capacity reserved for one attempt. Deleting a position must not delete the hold."""

    __tablename__ = "exposure_holds"

    attempt_id = Column(String, primary_key=True)
    instrument = Column(String, nullable=False)
    quantity = Column(BigInteger, nullable=False)
    limit_price = Column(String, nullable=False)
    multiplier = Column(BigInteger, nullable=False)
    notional = Column(String, nullable=False)
    state = Column(String(32), nullable=False)
    effect = Column(String, nullable=True)
    saved_rec_id = Column(String, nullable=True)
    coverage_quantity = Column(BigInteger, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
