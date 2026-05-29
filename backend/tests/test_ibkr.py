"""Tests for the IBKR Client Portal Web API adapter (app.data.ibkr)."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

import app.data.ibkr as ibkr_mod


# ── Helpers ───────────────────────────────────────────────────────────────────


def _reset_caches() -> None:
    """Reset all module-level caches between tests."""
    ibkr_mod._auth_cache = None
    ibkr_mod._conid_cache.clear()


def _mock_response(json_data, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


# ── ibkr_available ─────────────────────────────────────────────────────────────


def test_ibkr_available_true():
    """Returns True when gateway responds with authenticated=true."""
    _reset_caches()
    auth_resp = _mock_response({"authenticated": True})
    tickle_resp = _mock_response({})

    with patch("app.data.ibkr.httpx.get", return_value=auth_resp) as mock_get, \
         patch("app.data.ibkr.httpx.post", return_value=tickle_resp) as mock_post:
        result = ibkr_mod.ibkr_available()

    assert result is True
    mock_get.assert_called_once()
    # tickle keep-alive should have been called
    mock_post.assert_called_once()
    assert "tickle" in mock_post.call_args[0][0]


def test_ibkr_available_false_not_authenticated():
    """Returns False when gateway responds with authenticated=false."""
    _reset_caches()
    auth_resp = _mock_response({"authenticated": False})

    with patch("app.data.ibkr.httpx.get", return_value=auth_resp), \
         patch("app.data.ibkr.httpx.post") as mock_post:
        result = ibkr_mod.ibkr_available()

    assert result is False
    # No keep-alive when not authenticated
    mock_post.assert_not_called()


def test_ibkr_available_connection_error():
    """Returns False when the gateway is unreachable (ConnectError)."""
    _reset_caches()

    with patch("app.data.ibkr.httpx.get", side_effect=Exception("connection refused")):
        result = ibkr_mod.ibkr_available()

    assert result is False


# ── _conid ────────────────────────────────────────────────────────────────────


def test_conid_resolves():
    """Resolves symbol to int conid from secdef/search response."""
    _reset_caches()
    secdef_resp = _mock_response([{"conid": "12345", "sections": [{"secType": "STK"}]}])

    with patch("app.data.ibkr.httpx.post", return_value=secdef_resp):
        result = ibkr_mod._conid("AAPL")

    assert result == 12345
    assert isinstance(result, int)


def test_conid_cache_hit():
    """Second call with same symbol uses cache; HTTP only called once."""
    _reset_caches()
    secdef_resp = _mock_response([{"conid": "99999", "sections": [{"secType": "STK"}]}])

    with patch("app.data.ibkr.httpx.post", return_value=secdef_resp) as mock_post:
        r1 = ibkr_mod._conid("TSLA")
        r2 = ibkr_mod._conid("TSLA")

    assert r1 == r2 == 99999
    mock_post.assert_called_once()


# ── fetch_intraday_ibkr ───────────────────────────────────────────────────────


def test_fetch_intraday_ibkr_happy_path():
    """Returns correct bar list when auth, conid, and history all succeed."""
    _reset_caches()

    auth_resp = _mock_response({"authenticated": True})
    tickle_resp = _mock_response({})
    secdef_resp = _mock_response([{"conid": "12345", "sections": [{"secType": "STK"}]}])
    history_resp = _mock_response({
        "data": [
            {"t": 1_700_000_000_000, "o": 150.1, "h": 152.5, "l": 149.8, "c": 151.2, "v": 1000},
            {"t": 1_700_003_600_000, "o": 151.2, "h": 153.0, "l": 150.5, "c": 152.0, "v": 1200},
        ]
    })

    def _mock_get(url, **kwargs):
        if "auth/status" in url:
            return auth_resp
        return history_resp

    def _mock_post(url, **kwargs):
        if "tickle" in url:
            return tickle_resp
        return secdef_resp

    with patch("app.data.ibkr.httpx.get", side_effect=_mock_get), \
         patch("app.data.ibkr.httpx.post", side_effect=_mock_post):
        result = ibkr_mod.fetch_intraday_ibkr("AAPL", "15min", 55)

    assert len(result) == 2
    assert result[0]["time"] == 1_700_000_000
    assert result[0]["open"] == round(150.1, 4)
    assert result[0]["volume"] == 1000
    # Shape check
    for bar in result:
        assert set(bar.keys()) == {"time", "open", "high", "low", "close", "volume"}


def test_fetch_intraday_ibkr_gateway_down():
    """Returns [] when ibkr_available() returns False."""
    _reset_caches()

    with patch("app.data.ibkr.ibkr_available", return_value=False):
        result = ibkr_mod.fetch_intraday_ibkr("AAPL", "15min", 55)

    assert result == []


# ── fetch_iv_metrics_ibkr ─────────────────────────────────────────────────────


def test_fetch_iv_metrics_ibkr_happy_path():
    """Returns dict with ivRank and ivPercentile when snapshot has both fields."""
    _reset_caches()

    auth_resp = _mock_response({"authenticated": True})
    tickle_resp = _mock_response({})
    secdef_resp = _mock_response([{"conid": "12345", "sections": [{"secType": "STK"}]}])
    snapshot_resp = _mock_response([{"conidEx": "12345", "7308": "45.3", "7309": "62.1"}])

    def _mock_get(url, **kwargs):
        if "auth/status" in url:
            return auth_resp
        if "snapshot" in url:
            return snapshot_resp
        return MagicMock()

    def _mock_post(url, **kwargs):
        if "tickle" in url:
            return tickle_resp
        return secdef_resp

    with patch("app.data.ibkr.httpx.get", side_effect=_mock_get), \
         patch("app.data.ibkr.httpx.post", side_effect=_mock_post):
        result = ibkr_mod.fetch_iv_metrics_ibkr("AAPL")

    assert result is not None
    assert result["ivRank"] == 45.3
    assert result["ivPercentile"] == 62.1


def test_fetch_iv_metrics_ibkr_missing_fields():
    """Returns None when snapshot item has no 7308/7309 fields."""
    _reset_caches()

    auth_resp = _mock_response({"authenticated": True})
    tickle_resp = _mock_response({})
    secdef_resp = _mock_response([{"conid": "12345", "sections": [{"secType": "STK"}]}])
    snapshot_resp = _mock_response([{"conidEx": "12345"}])

    def _mock_get(url, **kwargs):
        if "auth/status" in url:
            return auth_resp
        return snapshot_resp

    def _mock_post(url, **kwargs):
        if "tickle" in url:
            return tickle_resp
        return secdef_resp

    with patch("app.data.ibkr.httpx.get", side_effect=_mock_get), \
         patch("app.data.ibkr.httpx.post", side_effect=_mock_post):
        result = ibkr_mod.fetch_iv_metrics_ibkr("AAPL")

    assert result is None


def test_fetch_iv_metrics_gateway_down():
    """Returns None when ibkr_available() returns False."""
    _reset_caches()

    with patch("app.data.ibkr.ibkr_available", return_value=False):
        result = ibkr_mod.fetch_iv_metrics_ibkr("AAPL")

    assert result is None


# ── New tests (Minor #5, #6, #7) ─────────────────────────────────────────────


def test_conid_fallback_no_stk_section():
    """Returns conid from first result when no entry has an STK section."""
    _reset_caches()
    # No "sections" key at all — should still return the conid from first entry
    secdef_resp = _mock_response([{"conid": "77777"}])

    with patch("app.data.ibkr.httpx.post", return_value=secdef_resp):
        result = ibkr_mod._conid("MSFT")

    assert result == 77777
    assert isinstance(result, int)


def test_fetch_intraday_ibkr_4h_resamples():
    """fetch_intraday_ibkr with '4h' resamples 1h bars; output has fewer bars."""
    _reset_caches()

    # 5 consecutive 1-hour bars (timestamps in ms, 1h apart)
    base_ms = 1_700_000_000_000
    one_hour_ms = 3_600_000
    raw_bars = [
        {"t": base_ms + i * one_hour_ms, "o": 100.0, "h": 102.0, "l": 99.0, "c": 101.0, "v": 500}
        for i in range(5)
    ]
    history_resp = _mock_response({"data": raw_bars})

    def _mock_get(url, **kwargs):
        if "auth/status" in url:
            return _mock_response({"authenticated": True})
        return history_resp

    def _mock_post(url, **kwargs):
        if "tickle" in url:
            return _mock_response({})
        return _mock_response([{"conid": "99", "sections": [{"secType": "STK"}]}])

    with patch("app.data.ibkr.httpx.get", side_effect=_mock_get), \
         patch("app.data.ibkr.httpx.post", side_effect=_mock_post):
        result = ibkr_mod.fetch_intraday_ibkr("AAPL", "4h", 180)

    # 5 input 1h bars → 1 or 2 resampled 4h bars (fewer than 5)
    assert len(result) < 5
    assert len(result) >= 1
    for bar in result:
        assert set(bar.keys()) == {"time", "open", "high", "low", "close", "volume"}


def test_conid_caches_failure():
    """_conid caches failures as sentinel; second call does NOT fire HTTP again."""
    _reset_caches()

    with patch("app.data.ibkr.httpx.post", side_effect=Exception("timeout")) as mock_post:
        r1 = ibkr_mod._conid("BAD")
        r2 = ibkr_mod._conid("BAD")

    assert r1 is None
    assert r2 is None
    # HTTP should only have been called ONCE; second call hit the sentinel in cache
    mock_post.assert_called_once()
