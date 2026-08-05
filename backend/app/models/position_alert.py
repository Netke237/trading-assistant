from __future__ import annotations

from sqlalchemy import Column, String, Float, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone

from app.database import Base


class PositionAlertHistoryModel(Base):
    """One row per genuinely new/reminder-worthy portfolio alert fire.

    Written independently of notify_alert()'s dispatch gating (masterEnabled /
    enabledTypes) so a muted alert type still leaves an audit trail — see
    app/services/position_alert_log.py for the writer and its own dedup.

    reference_value's unit depends on reference_kind:
      "price" (TP_HIT/STOP_REACHED/PREMIUM_STOP) -> a dollar amount
      "days"  (TIME_STOP/EVENT_RISK)              -> a day count
      "regime" (REGIME_CHANGE)                    -> unused, see `note`
    """
    __tablename__ = "position_alert_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rec_id = Column(String, nullable=False, index=True)
    symbol = Column(String, nullable=False)
    alert_type = Column(String, nullable=False)
    source = Column(String, nullable=False)  # "backend" | "frontend"
    price = Column(Float, nullable=True)
    reference_value = Column(Float, nullable=True)
    reference_kind = Column(String, nullable=True)
    direction = Column(String, nullable=True)
    contract = Column(String, nullable=True)
    note = Column(String, nullable=True)
    triggered_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index('ix_position_alert_history_rec_id_alert_type', 'rec_id', 'alert_type'),
    )
