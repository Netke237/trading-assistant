from sqlalchemy import Column, String, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime, timezone

from app.database import Base


class WatchedContractModel(Base):
    __tablename__ = "watched_contracts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contract_id = Column(String, nullable=False, unique=True, index=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    # The grading inputs Step 6 used for this contract when it was starred
    # (contract_rules / hold_min_days / hold_max_days / stock_score), so the
    # Watchlist grades it as the scan did. NULL = starred before this column
    # existed, or starred without grading: a real state, not a missing value,
    # so no default and no backfill. none_as_null: a Python None is SQL NULL,
    # never the JSON literal `null`.
    grading = Column(JSON(none_as_null=True), nullable=True)
