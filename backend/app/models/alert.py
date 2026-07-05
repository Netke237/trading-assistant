# backend/app/models/alert.py
from __future__ import annotations

from sqlalchemy import Column, String, Boolean, Integer, Text, ForeignKey, Index
from app.database import Base


class AlertRuleModel(Base):
    __tablename__ = 'alert_rules'

    id = Column(String(36), primary_key=True)
    user_id = Column(String(64), nullable=False, default='default')
    name = Column(String(200), nullable=False)
    symbol = Column(String(10), nullable=False)
    interval = Column(String(10), nullable=False)
    enabled = Column(Boolean(), nullable=False, default=True)
    rule_json = Column(Text(), nullable=False)
    cooldown_minutes = Column(Integer(), nullable=False, default=60)
    expiry_date = Column(Text(), nullable=True)
    created_at = Column(Text(), nullable=False)
    last_triggered_at = Column(Text(), nullable=True)
    condition_state = Column(Text(), nullable=False, default='{}')

    __table_args__ = (
        Index('ix_alert_rules_symbol', 'symbol'),
        Index('ix_alert_rules_user_id', 'user_id'),
    )


class AlertHistoryModel(Base):
    __tablename__ = 'alert_history'

    id = Column(String(36), primary_key=True)
    rule_id = Column(String(36), ForeignKey('alert_rules.id', ondelete='CASCADE'), nullable=False)
    symbol = Column(String(10), nullable=True)
    interval = Column(String(10), nullable=True)
    triggered_at = Column(Text(), nullable=False)
    candle_json = Column(Text(), nullable=False)
    trigger_values = Column(Text(), nullable=False)
    reason = Column(Text(), nullable=False)

    __table_args__ = (
        Index('ix_alert_history_rule_id', 'rule_id'),
        Index('ix_alert_history_symbol', 'symbol'),
    )
