from sqlalchemy import Boolean, Column, String
from sqlalchemy.orm import relationship

from app.models.base import Base


class Admin(Base):
    __tablename__ = "admins"

    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    sync_status = Column(
        String(20),
        default="SYNCED",
        nullable=False,
        index=True,
    )

    children = relationship("Child", back_populates="parent", lazy="selectin")
    quests = relationship(
        "Quest", back_populates="assigned_admin", lazy="selectin"
    )
    override_logs = relationship(
        "OverrideLog", back_populates="admin", lazy="selectin"
    )
