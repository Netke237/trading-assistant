from sqlalchemy import Column, String, Float, Integer, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone

from app.database import Base


class PortfolioPositionModel(Base):
    __tablename__ = "portfolio_positions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rec_id = Column(String, nullable=False, unique=True, index=True)
    symbol = Column(String, nullable=False)
    contract = Column(String, nullable=False, unique=True, index=True)
    direction = Column(String, nullable=False)
    entry_price = Column(Float, nullable=False)
    qty = Column(Integer, nullable=False, default=1)
    entry_date = Column(String, nullable=False)
    stop = Column(Float, nullable=True)
    structural_stop = Column(Float, nullable=True)
    # Piece 4 — per-position premium stop. NULL means "inherit the global"
    # (risk_rules.yaml -> reward_risk.premium_stop_pct), which is a distinct,
    # load-bearing state and NOT a value waiting to be backfilled: a position
    # stamped 0.60 at creation would stop responding when the global moved.
    # Resolve every read through services/premium_stop.resolve_premium_stop_pct.
    premium_stop_pct = Column(Float, nullable=True, default=None)
    targets = Column(JSON, nullable=True, default=list)
    dte_total = Column(Integer, nullable=True)
    entry_stock_price = Column(Float, nullable=True)
    alert_state = Column(JSON, nullable=True, default=dict)
    # Exit-plan pipeline (docs/superpowers/plans/2026-08-26-exit-plan-pipeline.md) —
    # Phase 0 scaffolding. Business logic that populates/consumes these lands in
    # later phases; the columns exist now so migrations, schemas, and router
    # plumbing don't block on each feature's own PR.
    exit_plan = Column(JSON, nullable=True, default=None)
    max_loss_override = Column(JSON, nullable=True, default=None)
    active_tp_method = Column(String, nullable=False, default="ladder")
    resolved_tp_price = Column(Float, nullable=True)
    resolved_tp_updated_at = Column(DateTime(timezone=True), nullable=True)
    alert_overrides = Column(JSON, nullable=True, default=dict)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
