"""Test AlternativeContract attachment to TradeCardData in scan results."""

from unittest.mock import patch

_MOCK_CANDLES = [
    {"time": f"2026-0{i//10+1}-{i%28+1:02d}", "open": 184.0, "high": 190.0,
     "low": 182.0, "close": 187.0, "volume": 1_000_000}
    for i in range(30)
]

_MOCK_MULTI_CHAIN = [
    {
        "strike": 185, "expiry": "2026-06-20", "price": 4.50, "spread": 0.15,
        "delta": 0.55, "theta": -0.06, "ivRank": 50, "dte": 41,
        "right": "C", "volume": 800,
    },
    {
        "strike": 190, "expiry": "2026-06-20", "price": 2.50, "spread": 0.20,
        "delta": 0.45, "theta": -0.05, "ivRank": 55, "dte": 41,
        "right": "C", "volume": 500,
    },
    {
        "strike": 195, "expiry": "2026-06-20", "price": 1.00, "spread": 0.10,
        "delta": 0.30, "theta": -0.03, "ivRank": 60, "dte": 41,
        "right": "C", "volume": 300,
    },
]


def test_scan_produces_alternatives_with_multi_contract_chain(client):
    with patch("app.routers.scan.fetch_price",        return_value=185.0), \
         patch("app.routers.scan.fetch_candles",       return_value=_MOCK_CANDLES), \
         patch("app.routers.scan.fetch_option_chain",  return_value=_MOCK_MULTI_CHAIN):
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {},
        })
    assert r.status_code == 200
    data = r.json()

    for c in data["candidates"]:
        assert "alternatives" in c
        assert "alternativesCount" in c
        assert c["alternativesCount"] >= 1, (
            f"Expected at least 1 alternative for {c['symbol']}, got {c['alternativesCount']}"
        )
        assert c["alternativesCount"] == len(c["alternatives"]), (
            f"alternativesCount {c['alternativesCount']} != len(alternatives) {len(c['alternatives'])}"
        )

        for alt in c["alternatives"]:
            assert alt["score"] < c["contractScore"], (
                f"Alternative score {alt['score']} should be < primary {c['contractScore']}"
            )
            for field in ("symbol", "strike", "expiry", "right", "dte", "mid", "delta",
                          "theta", "ivRank", "score", "contractConfidence",
                          "contractBreakdown", "rrRatio", "rrModel", "reason"):
                assert field in alt, f"AlternativeContract missing field '{field}'"


def test_scan_single_contract_produces_no_alternatives(client):
    _MOCK_SINGLE = [
        {
            "strike": 190, "expiry": "2026-06-20", "price": 2.50, "spread": 0.20,
            "delta": 0.45, "theta": -0.05, "ivRank": 55, "dte": 41,
            "right": "C", "volume": 500,
        }
    ]
    with patch("app.routers.scan.fetch_price",        return_value=185.0), \
         patch("app.routers.scan.fetch_candles",       return_value=_MOCK_CANDLES), \
         patch("app.routers.scan.fetch_option_chain",  return_value=_MOCK_SINGLE):
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {},
        })
    assert r.status_code == 200
    data = r.json()
    for c in data["candidates"]:
        assert c["alternativesCount"] == 0
        assert c["alternatives"] == []


def test_scan_bullish_alternatives_have_right_C(client):
    with patch("app.routers.scan.fetch_price",        return_value=185.0), \
         patch("app.routers.scan.fetch_candles",       return_value=_MOCK_CANDLES), \
         patch("app.routers.scan.fetch_option_chain",  return_value=_MOCK_MULTI_CHAIN):
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing", "overrides": {},
        })
    assert r.status_code == 200
    data = r.json()
    for c in data["candidates"]:
        for alt in c["alternatives"]:
            assert alt["right"] == "C", f"Bullish alternative should have right=C, got {alt['right']}"


def test_scan_bearish_alternatives_have_right_P(client):
    _MOCK_PUT_CHAIN = [
        {
            "strike": 180, "expiry": "2026-06-20", "price": 4.50, "spread": 0.15,
            "delta": -0.55, "theta": -0.06, "ivRank": 50, "dte": 41,
            "right": "P", "volume": 800,
        },
        {
            "strike": 175, "expiry": "2026-06-20", "price": 2.50, "spread": 0.20,
            "delta": -0.45, "theta": -0.05, "ivRank": 55, "dte": 41,
            "right": "P", "volume": 500,
        },
        {
            "strike": 170, "expiry": "2026-06-20", "price": 1.00, "spread": 0.10,
            "delta": -0.30, "theta": -0.03, "ivRank": 60, "dte": 41,
            "right": "P", "volume": 300,
        },
    ]
    with patch("app.routers.scan.fetch_price",        return_value=185.0), \
         patch("app.routers.scan.fetch_candles",       return_value=_MOCK_CANDLES), \
         patch("app.routers.scan.fetch_option_chain",  return_value=_MOCK_PUT_CHAIN):
        r = client.post("/api/scan", json={
            "universe": ["AAPL"], "direction": "Bearish", "horizon": "Swing", "overrides": {},
        })
    assert r.status_code == 200
    data = r.json()
    for c in data["candidates"]:
        for alt in c["alternatives"]:
            assert alt["right"] == "P", f"Bearish alternative should have right=P, got {alt['right']}"
