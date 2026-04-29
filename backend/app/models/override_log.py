from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base


class OverrideLog(Base):
    __tablename__ = "override_logs"

    admin_id = Column(
        UUID(as_uuid=True),
        ForeignKey("admins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    child_id = Column(
        UUID(as_uuid=True),
        ForeignKey("children.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    override_type = Column(
        String(30),
        nullable=False,
        index=True,
    )
    reason = Column(Text, nullable=False)
    minutes_granted = Column(Integer, nullable=True)
    previous_state = Column(String(50), nullable=False)
    new_state = Column(String(50), nullable=False)
    sync_status = Column(
        String(20),
        default="SYNCED",
        nullable=False,
        index=True,
    )

    admin = relationship("Admin", back_populates="override_logs")
    child = relationship("Child", back_populates="override_logs")
