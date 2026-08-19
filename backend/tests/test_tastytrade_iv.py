from unittest.mock import patch, MagicMock, AsyncMock
import pytest

from app.data import tastytrade_iv


def _fake_metric(symbol, rank, pct):
    m = MagicMock()
    m.symbol = symbol
    m.implied_volatility_index_rank = str(rank)
    m.implied_volatility_percentile = str(pct)
    return m


def test_fetch_iv_metrics_tastytrade_returns_none_when_unconfigured():
    with patch("app.data.tastytrade_iv.get_session", return_value=None):
        assert tastytrade_iv.fetch_iv_metrics_tastytrade(["AAPL"]) is None


def test_fetch_iv_metrics_tastytrade_maps_fields(monkeypatch):
    """Wire format is 0-1 decimal strings ("0.623" = rank 62.3) — verified
    against the live /market-metrics response. The adapter must normalize to
    the 0-100 scale fetch_iv_metrics_ibkr returns."""
    fake_session = MagicMock()

    async def fake_get_market_metrics(session, symbols):
        assert session is fake_session
        assert list(symbols) == ["AAPL"]
        return [_fake_metric("AAPL", 0.623, 0.581)]

    with patch("app.data.tastytrade_iv.get_session", return_value=fake_session), \
         patch("app.data.tastytrade_iv.get_market_metrics", side_effect=fake_get_market_metrics):
        result = tastytrade_iv.fetch_iv_metrics_tastytrade(["AAPL"])

    assert result == {"AAPL": {"ivRank": 62.3, "ivPercentile": 58.1}}


def test_fetch_iv_metrics_tastytrade_preserves_rank_above_100(monkeypatch):
    """Rank exceeds 100 when current IV is above the 52-week high (wire
    "1.234" = rank 123.4). The adapter must scale it honestly — not clamp to
    100, not pass it raw, and not apply a conditional `x*100 if x<=1` heuristic."""
    fake_session = MagicMock()

    async def fake_get_market_metrics(session, symbols):
        return [_fake_metric("AAPL", 1.234, 0.999)]

    with patch("app.data.tastytrade_iv.get_session", return_value=fake_session), \
         patch("app.data.tastytrade_iv.get_market_metrics", side_effect=fake_get_market_metrics):
        result = tastytrade_iv.fetch_iv_metrics_tastytrade(["AAPL"])

    assert result == {"AAPL": {"ivRank": 123.4, "ivPercentile": 99.9}}


def test_fetch_iv_metrics_tastytrade_returns_none_on_error():
    fake_session = MagicMock()

    async def raising_get_market_metrics(session, symbols):
        raise RuntimeError("network error")

    with patch("app.data.tastytrade_iv.get_session", return_value=fake_session), \
         patch("app.data.tastytrade_iv.get_market_metrics", side_effect=raising_get_market_metrics):
        assert tastytrade_iv.fetch_iv_metrics_tastytrade(["AAPL"]) is None
