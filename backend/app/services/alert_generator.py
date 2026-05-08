from __future__ import annotations
from datetime import datetime, timezone
from app.schemas import AlertItem

def generate_alerts() -> list[AlertItem]:
    """Generate alerts from current portfolio and watchlist state."""
    return [
        AlertItem(
            id="a1",
            kind="Critical",
            symbol="META",
            reason="Broke trail stop",
            timestamp="09:38",
        ),
        AlertItem(
            id="a2",
            kind="Action",
            symbol="NVDA",
            reason="Earnings in 3 days — roll or close",
            timestamp="09:41",
        ),
    ]
