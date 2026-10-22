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
    # Phase G (piece 5) — the trader's explicit method pick, recorded on the
    # position at creation. NULLABLE, NO SERVER DEFAULT, NO BACKFILL, for the
    # same reason premium_stop_pct above is: NULL is a real state — "opened
    # before G, or opened by a path with no human in it" — and not a value
    # waiting to be filled in. D11 requires existing open positions untouched,
    # and the after-scan auto-executor (S5) is exempt from G's send gate and
    # deliberately writes NULL here (PHASE-G-S5-EXEMPT-2026-09-14).
    #
    # The portfolio must render NULL as "—", NEVER as 'ladder'. These are the
    # RECORD of what a human chose; active_tp_method above is the ALERT DRIVER
    # seeded from them, and the two can legitimately disagree (a barrier-race
    # pick records 'barrier_race' here and seeds 'ladder' there).
    picked_method = Column(String, nullable=True)
    # Units are in the names deliberately: only picked_row_stock_price may ever
    # reach resolved_tp_price, which is compared against the STOCK quote.
    picked_row_stock_price = Column(Float, nullable=True)
    picked_row_option_price = Column(Float, nullable=True)
    picked_stop_basis = Column(String, nullable=True)
    picked_at = Column(String, nullable=True)
    # STOCKS-HORIZON-T1 H6 -- the scan's hold (calendar days) a STOCK position
    # was sent with. Set => alert_generator raises TIME_STOP once the position
    # has been held this many days. NULL (options rows, rows opened before H6,
    # paths with no scan) => no hold, never a time stop.
    hold_max_days = Column(Integer, nullable=True)
    # Save-before-order marker and its attempt owner. Both stay NULL on rows
    # that were not server-prepared for one order; migration does not backfill.
    prepared_order = Column(JSON, nullable=True)
    order_attempt_id = Column(String, nullable=True, index=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
