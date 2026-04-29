from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base


class Child(Base):
    __tablename__ = "children"

    name = Column(String(100), nullable=False)
    daily_time_budget = Column(Integer, nullable=False)
    avatar_url = Column(String(500), nullable=True)
    parent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("admins.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Positive framing: access is granted by default, can be revoked
    app_access_state = Column(
        String(20),
        default="GRANTED",
        nullable=False,
        index=True,
    )
    current_quest_id = Column(
        UUID(as_uuid=True),
        ForeignKey("quests.id", ondelete="SET NULL"),
        nullable=True,
    )
    sync_status = Column(
        String(20),
        default="SYNCED",
        nullable=False,
        index=True,
    )

    parent = relationship("Admin", back_populates="children")
    quests = relationship("Quest", back_populates="child", lazy="selectin")
    time_logs = relationship("TimeLog", back_populates="child", lazy="selectin")
    override_logs = relationship(
        "OverrideLog", back_populates="child", lazy="selectin"
    )
