"""
Regression test: _fetch_intraday_yf must fetch intraday bars with period=,
letting yfinance compute the start/end window itself, NOT explicit start=/end=.

History: an earlier approach passed explicit start=/end= dates. That broke when
the local clock ran ahead of yfinance's servers (an end date "in the future"
from Yahoo's perspective returned a truncated window → "INSUFFICIENT DATA" in
the Intraday regime panel). The fix (commit c7bc1d4, 2026-05-30) switched to
period=, so yfinance resolves the actual window on its side and the clock-skew
problem disappears. This test guards that behavior.
"""
from __future__ import annotations

from unittest.mock import patch

import pandas as pd


def test_fetch_intraday_yf_uses_period_not_start_end():
    """
    _fetch_intraday_yf must call yfinance.download with period= and let yfinance
    determine the window — NOT explicit start=/end= date parameters.
    """
    from app.data.market import _fetch_intraday_yf

    captured: dict = {}

    def _capture_download(*args, **kwargs):
        captured.update(kwargs)
        return pd.DataFrame()

    with patch("yfinance.download", side_effect=_capture_download):
        _fetch_intraday_yf("SPY", interval="15m", days=55)

    assert "period" in captured, (
        "yfinance.download must be called with period= so yfinance resolves the "
        "start/end window itself (avoids clock-skew truncation)."
    )
    assert "start" not in captured, (
        "yfinance.download must NOT pass an explicit start= date — a local clock "
        "ahead of Yahoo's servers truncated the window → INSUFFICIENT DATA."
    )
    assert "end" not in captured, "yfinance.download must NOT pass an explicit end= date."
