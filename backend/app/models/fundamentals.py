from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Column, Date, DateTime, Float, Numeric, String

from app.database import Base


class FundamentalsModel(Base):
    """Quarterly/annual fundamental data per symbol.

    Composite primary key: (symbol, fiscal_period_end).
    All financial figures are raw values in the currency of the filing.
    """

    __tablename__ = "fundamentals"

    symbol = Column(String(10), primary_key=True, nullable=False)
    fiscal_period_end = Column(Date, primary_key=True, nullable=False)
    filed_date = Column(Date, nullable=True)
    cik = Column(String(12), nullable=True)

    # Income statement
    revenue = Column(Numeric, nullable=True)
    net_income = Column(Numeric, nullable=True)
    eps_diluted = Column(Numeric, nullable=True)
    gross_profit = Column(Numeric, nullable=True)
    operating_income = Column(Numeric, nullable=True)

    # Cash flow
    op_cash_flow = Column(Numeric, nullable=True)
    capex = Column(Numeric, nullable=True)

    # Balance sheet
    total_debt = Column(Numeric, nullable=True)
    stockholders_eq = Column(Numeric, nullable=True)
    current_assets = Column(Numeric, nullable=True)
    current_liab = Column(Numeric, nullable=True)

    # Share data
    shares_diluted = Column(Numeric, nullable=True)

    # Computed growth rates (stored so cache hits return accurate growth data)
    revenue_growth_yoy = Column(Float, nullable=True)
    eps_growth_yoy     = Column(Float, nullable=True)
    share_growth_yoy   = Column(Float, nullable=True)

    # Provenance
    source = Column(String(20), nullable=True)
    fetched_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
