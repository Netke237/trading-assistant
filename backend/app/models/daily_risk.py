"""Durable opening spend and gross loss. Independent of deletable trade history."""
from sqlalchemy import BigInteger, CheckConstraint, Column, String
from app.database import Base


class DailyRiskBudget(Base):
    __tablename__ = 'daily_risk_budgets'
    day = Column(String(10), primary_key=True)
    reserved_cents = Column(BigInteger, nullable=False, default=0)
    loss_cents = Column(BigInteger, nullable=False, default=0)
    __table_args__ = (CheckConstraint('reserved_cents >= 0 AND loss_cents >= 0'),)


class DailyRiskAttempt(Base):
    __tablename__ = 'daily_risk_attempts'
    id = Column(String(64), primary_key=True)
    day = Column(String(10), nullable=False, index=True)
    reserved_cents = Column(BigInteger, nullable=False)
    state = Column(String(20), nullable=False)
    outcome = Column(String, nullable=False, default='')
    instrument = Column(String, nullable=False)
    source = Column(String, nullable=False)
    quantity = Column(BigInteger, nullable=False)
    price = Column(String, nullable=False)
    multiplier = Column(BigInteger, nullable=False)


class DailyRiskLoss(Base):
    __tablename__ = 'daily_risk_losses'
    closed_id = Column(String(64), primary_key=True)
    day = Column(String(10), nullable=False)
    loss_cents = Column(BigInteger, nullable=False)
