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
    fake_session = MagicMock()

    async def fake_get_market_metrics(session, symbols):
        assert session is fake_session
        assert list(symbols) == ["AAPL"]
        return [_fake_metric("AAPL", 62.3, 58.1)]

    with patch("app.data.tastytrade_iv.get_session", return_value=fake_session), \
         patch("app.data.tastytrade_iv.get_market_metrics", side_effect=fake_get_market_metrics):
        result = tastytrade_iv.fetch_iv_metrics_tastytrade(["AAPL"])

    assert result == {"AAPL": {"ivRank": 62.3, "ivPercentile": 58.1}}


def test_fetch_iv_metrics_tastytrade_returns_none_on_error():
    fake_session = MagicMock()

    async def raising_get_market_metrics(session, symbols):
        raise RuntimeError("network error")

    with patch("app.data.tastytrade_iv.get_session", return_value=fake_session), \
         patch("app.data.tastytrade_iv.get_market_metrics", side_effect=raising_get_market_metrics):
        assert tastytrade_iv.fetch_iv_metrics_tastytrade(["AAPL"]) is None
