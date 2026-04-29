from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Time
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base


class TimeLog(Base):
    __tablename__ = "time_logs"

    child_id = Column(
        UUID(as_uuid=True),
        ForeignKey("children.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date = Column(Date, nullable=False, index=True)
    budgeted_minutes = Column(Integer, nullable=False)
    used_minutes = Column(Integer, default=0, nullable=False)
    bonus_minutes = Column(Integer, default=0, nullable=False)
    day_state = Column(
        String(20),
        default="UPCOMING",
        nullable=False,
        index=True,
    )
    reset_time = Column(Time, nullable=True)
    sync_status = Column(
        String(20),
        default="SYNCED",
        nullable=False,
        index=True,
    )
    calendar_import_state = Column(
        String(20),
        default="QUEUED",
        nullable=False,
        index=True,
    )

    child = relationship("Child", back_populates="time_logs")
