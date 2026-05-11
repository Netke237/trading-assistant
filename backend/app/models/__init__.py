# Import all ORM models so SQLAlchemy's Base.metadata is populated.
# Required for Alembic autogenerate and create_all() calls.

from app.models.portfolio import PortfolioPositionModel  # noqa: F401
from app.models.watchlist import WatchlistSymbolModel  # noqa: F401
from app.models.audit_event import AuditEventModel  # noqa: F401
from app.models.scan_session import ScanSession  # noqa: F401
from app.models.scan_session import ScanSession  # noqa: F401
