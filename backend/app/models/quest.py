from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base


class Quest(Base):
    __tablename__ = "quests"

    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    child_id = Column(
        UUID(as_uuid=True),
        ForeignKey("children.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_admin_id = Column(
        UUID(as_uuid=True),
        ForeignKey("admins.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    state = Column(
        String(30),
        default="PENDING",
        nullable=False,
        index=True,
    )
    proof_required = Column(Boolean, default=False, nullable=False)
    points_reward = Column(Integer, default=0, nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    sync_status = Column(
        String(20),
        default="SYNCED",
        nullable=False,
        index=True,
    )

    child = relationship("Child", back_populates="quests")
    assigned_admin = relationship("Admin", back_populates="quests")
