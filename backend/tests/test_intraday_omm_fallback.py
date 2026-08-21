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


def test_intraday_status_unavailable_when_hmmlearn_missing():
    """hmmlearn absent → 'unavailable' + fit never attempted; OMM fallback still runs."""
    import importlib.util as _ilu
    from app.main import app

    real_find_spec = _ilu.find_spec

    def fake_find_spec(name, *args, **kwargs):
        if name == "hmmlearn":
            return None
        return real_find_spec(name, *args, **kwargs)

    with (
        patch("app.routers.regime.fetch_intraday_candles", return_value=_make_bars(500)),
        # create=True: regime.py only gains find_spec with the status-label fix —
        # pre-fix this patch is inert; the RED comes from the mocked compute below.
        patch("app.routers.regime.find_spec", side_effect=fake_find_spec, create=True),
        patch("app.routers.regime.compute_intraday_hmm", return_value=None) as mock_hmm,
        patch("app.routers.regime.fetch_candles", return_value=_make_bars(300)),
        patch("app.routers.regime.fetch_price", return_value=None),
    ):
        client = TestClient(app)
        resp = client.get("/api/regime")

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("intraday_hmm_status") == "unavailable", data
    mock_hmm.assert_not_called()   # hmmlearn "missing" → fit must not be attempted
    assert data.get("intraday_omm") is not None, "OMM fallback must still run"


def test_intraday_status_insufficient_when_few_bars():
    """Fewer than MIN_BARS 15-min bars → 'insufficient_data' (a real data shortage)."""
    from app.main import app

    with (
        patch("app.routers.regime.fetch_intraday_candles", return_value=_make_bars(100)),
        patch("app.routers.regime.fetch_candles", return_value=_make_bars(300)),
        patch("app.routers.regime.fetch_price", return_value=None),
    ):
        client = TestClient(app)
        resp = client.get("/api/regime")

    assert resp.status_code == 200, resp.text
    assert resp.json().get("intraday_hmm_status") == "insufficient_data"


def test_intraday_status_unavailable_when_fetch_empty():
    """Zero intraday bars → 'unavailable'."""
    from app.main import app

    with (
        patch("app.routers.regime.fetch_intraday_candles", return_value=[]),
        patch("app.routers.regime.fetch_candles", return_value=_make_bars(300)),
        patch("app.routers.regime.fetch_price", return_value=None),
    ):
        client = TestClient(app)
        resp = client.get("/api/regime")

    assert resp.status_code == 200, resp.text
    assert resp.json().get("intraday_hmm_status") == "unavailable"


def test_intraday_status_unavailable_when_fit_returns_none():
    """hmmlearn present + enough bars + fit returns None → 'unavailable' (fit/env failure)."""
    from app.main import app

    with (
        patch("app.routers.regime.fetch_intraday_candles", return_value=_make_bars(500)),
        patch("app.routers.regime.compute_intraday_hmm", return_value=None),
        patch("app.routers.regime.fetch_candles", return_value=_make_bars(300)),
        patch("app.routers.regime.fetch_price", return_value=None),
    ):
        client = TestClient(app)
        resp = client.get("/api/regime")

    assert resp.status_code == 200, resp.text
    assert resp.json().get("intraday_hmm_status") == "unavailable"


def test_intraday_status_ok_when_hmm_succeeds():
    """Fit succeeds → 'ok' and intraday_hmm payload populated."""
    from app.main import app
    from app.services.regime_hmm import HmmResult

    fake_hmm = HmmResult(state="Trending", p_stay=0.9,
                         p_transition=[{"to": "Choppy", "prob": 0.1}])
    with (
        patch("app.routers.regime.fetch_intraday_candles", return_value=_make_bars(500)),
        patch("app.routers.regime.compute_intraday_hmm", return_value=fake_hmm),
        patch("app.routers.regime.fetch_candles", return_value=_make_bars(300)),
        patch("app.routers.regime.fetch_price", return_value=None),
    ):
        client = TestClient(app)
        resp = client.get("/api/regime")

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("intraday_hmm_status") == "ok"
    assert data["intraday_hmm"]["state"] == "Trending"
