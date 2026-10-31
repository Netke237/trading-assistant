"""STOCKS-HORIZON-P0A A4: the confidence replay counts each setup once.

compute_confidence used to score every bar and count each PASS bar as a fire,
so a setup that stayed PASS for eight bars counted eight times with overlapping
forward windows. The replay now keeps fires greedily non-overlapping, exactly
like scripts/evidence/score_calibration.py::distinct: after a fire at bar i
(any outcome, flat included) the next bar that may fire is i + n_days, and the
bars in between are not scored. The confidence cache basis moves to b3 so no
overlapping-era value is served again.

The evidence scripts are added to sys.path the same way
tests/test_evidence_harness.py does it.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(REPO / "scripts"))

from app.scoring import signal_confidence as sc  # noqa: E402
from app.scoring.signal_confidence import load_backtest_cfg  # noqa: E402

N_DAYS = int(load_backtest_cfg("Swing")["n_days"])


class _Card:
    def __init__(self, status):
        self.status = status


def _bars(n=130):
    out = []
    price = 50.0
    for _ in range(n):
        price *= 1.001
        out.append({"open": price, "high": price * 1.01, "low": price * 0.99,
                    "close": price, "volume": 1000})
    return out


def _patch_replay(monkeypatch, pass_bars, outcome="win"):
    """score_stock returns PASS on `pass_bars`; evaluate_fire records the bar it
    is asked about and returns `outcome`. Returns (scored, fired) bar lists."""
    import app.scoring.stock_scorer as stock_scorer_mod

    scored: list[int] = []
    fired: list[int] = []

    def _fake_score_stock(*, bars, **_):
        i = len(bars) - 1
        scored.append(i)
        return _Card("PASS" if i in pass_bars else "REJECT")

    def _fake_evaluate_fire(history, forward, **_):
        fired.append(len(history) - 1)
        return outcome

    monkeypatch.setattr(stock_scorer_mod, "score_stock", _fake_score_stock)
    monkeypatch.setattr(sc, "evaluate_fire", _fake_evaluate_fire)
    return scored, fired


def test_overlapping_pass_bars_fire_once_per_window(monkeypatch):
    assert N_DAYS == 10  # the plan's worked example: Swing n_days
    pass_bars = set(range(70, 78)) | {100}
    scored, fired = _patch_replay(monkeypatch, pass_bars, outcome="win")

    res = sc.compute_confidence(_bars(), direction="Bullish", horizon="Swing")

    assert fired == [70, 100]
    assert res.sample_size == 2
    # Bars inside the open window after a fire are not scored at all.
    assert not set(range(71, 80)) & set(scored)
    assert 80 in scored


def test_flat_fire_still_blocks_its_window(monkeypatch):
    pass_bars = set(range(70, 81))
    scored, fired = _patch_replay(monkeypatch, pass_bars, outcome="flat")

    res = sc.compute_confidence(_bars(), direction="Bullish", horizon="Swing")

    assert fired == [70, 80]
    assert not set(range(71, 80)) & set(scored)
    assert res.sample_size == 0
    assert res.flats == 2


def test_sample_size_matches_harness_non_overlapping_count():
    from evidence.score_calibration import confidence_counts, replay

    bars = json.loads((FIXTURES / "AAPL_candles.json").read_text(encoding="utf-8"))
    direction, horizon = "Bullish", "Swing"

    counts = confidence_counts({"AAPL": replay(bars, horizon, direction)}, horizon, direction)
    assert len(counts) == 1
    c = counts[0]
    # The fixture must actually discriminate the two rules.
    assert c.overlapping != c.non_overlapping

    res = sc.compute_confidence(bars, direction=direction, horizon=horizon)
    assert res.sample_size == c.non_overlapping


def test_cache_key_carries_basis_b4():
    # b3 was this item's bump; b4 (PROVIDER-FALLBACK-FORMING-BAR, #536) supersedes
    # it, and an overlapping-era b3 value still misses.
    from app.data.confidence_cache import cache_key

    key = cache_key("AAPL", "Bullish", "Swing", None, None, scoring_mode="stock")
    assert key.endswith("|b4")
