# Import all ORM models so SQLAlchemy's Base.metadata is populated.
# Required for Alembic autogenerate and create_all() calls.

from app.models.portfolio import PortfolioPositionModel  # noqa: F401
from app.models.watchlist import WatchlistSymbolModel  # noqa: F401
from app.models.audit_event import AuditEventModel  # noqa: F401
from app.models.alert import AlertRuleModel, AlertHistoryModel  # noqa: F401
from app.models.closed_position import ClosedPositionModel, EquitySnapshotModel  # noqa: F401
from app.models.fundamentals import FundamentalsModel  # noqa: F401
from app.models.scheduled_scan_run import ScheduledScanRunModel  # noqa: F401
from app.models.daily_risk import DailyRiskBudget, DailyRiskAttempt, DailyRiskLoss  # noqa: F401
from app.models.broker_attempt import BrokerAttempt, ExposureGuard, ExposureHold  # noqa: F401
