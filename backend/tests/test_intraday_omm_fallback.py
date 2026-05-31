"""
Regression test: when hmmlearn is unavailable (Python 3.14+), the regime
endpoint must populate `intraday_omm` using OMM on the intraday 15-min bars
instead of leaving the Intraday panel blank.

RED: intraday_omm field does not exist in MarketRegime yet.
"""
from __future__ import annotations

import random
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


def _make_bars(n: int, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    base = 500.0
    bars = []
    for i in range(n):
        c = base + rng.gauss(0, 2)
        bars.append({"time": f"2026-01-{i % 28 + 1:02d} 09:30", "open": c - 0.1,
                     "high": c + 0.5, "low": c - 0.5, "close": c, "volume": 50_000})
        base = c
    return bars


def test_intraday_omm_present_when_hmm_unavailable():
    """
    When compute_intraday_hmm returns None (hmmlearn absent) and intraday bars
    are available, MarketRegime.intraday_omm must be a populated OmmData object.
    """
    from app.main import app

    fake_intra = _make_bars(500)       # plenty of bars

    with (
        patch("app.routers.regime.fetch_intraday_candles", return_value=fake_intra),
        patch("app.routers.regime.compute_intraday_hmm", return_value=None),
        # keep fetch_candles working so the rest of the endpoint doesn't blow up
        patch("app.routers.regime.fetch_candles", return_value=_make_bars(300)),
        patch("app.routers.regime.fetch_price", return_value=None),
    ):
        client = TestClient(app)
        resp = client.get("/api/regime")

    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data.get("intraday_omm") is not None, (
        "intraday_omm must be populated when HMM is unavailable; "
        f"got intraday_hmm_status={data.get('intraday_hmm_status')!r}"
    )
    omm = data["intraday_omm"]
    assert omm["state"] in ("Bull", "Bear", "Choppy")
    assert 0.0 <= omm["p_stay"] <= 1.0
    assert omm["stability"] in ("Stable", "Fragile")
