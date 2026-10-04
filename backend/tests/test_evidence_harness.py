"""TRADING-REVIEW-PHASE-C T11: the read-only evidence harness under scripts/evidence/.

Pure cores only; no database. The scripts are added to sys.path the same way
tests/test_retune_archived_basket.py does it.
"""
from datetime import date, timedelta
from pathlib import Path
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / "scripts" / "evidence"
sys.path.insert(0, str(REPO / "scripts"))

from app.scoring.signal_confidence import load_backtest_cfg  # noqa: E402

HARNESS_MODULES = ("__init__.py", "_bars.py", "bar_basis_check.py", "score_calibration.py")


def _bar(i, o, h, l, c, v=1_000):
    return {"time": (date(2020, 1, 1) + timedelta(days=i)).isoformat(),
            "open": o, "high": h, "low": l, "close": c, "volume": v}


def test_basis_violations_counts_close_outside_range():
    from evidence.bar_basis_check import basis_violations

    bars = [
        _bar(0, 10.0, 11.0, 9.0, 10.5),
        _bar(1, 10.5, 11.5, 10.0, 12.0),   # close above high: the H1 mixed-basis signature
        _bar(2, 12.0, 12.5, 11.5, 12.2),
    ]
    out = basis_violations(bars)
    assert out["n"] == 3
    assert out["close_outside"] == 1
    assert out["open_outside"] == 0
    assert out["any_outside"] == 1
    assert out["share"] == pytest.approx(1 / 3)


def test_big_jumps_flags_split_sized_step_and_ignores_small_move():
    from evidence.bar_basis_check import big_jumps

    bars = [
        _bar(0, 10.0, 10.0, 10.0, 10.0),
        _bar(1, 10.3, 10.3, 10.3, 10.3),            # +3%: a real move
        _bar(2, 79.928, 79.928, 79.928, 79.928),    # x7.76: a missed reverse split
    ]
    jumps = big_jumps(bars, 0.40)
    assert len(jumps) == 1
    assert jumps[0]["time"] == bars[2]["time"]
    assert jumps[0]["ratio"] == pytest.approx(7.76)


class _Card:
    def __init__(self, status):
        self.status = status


def _even_pass_scorer(*, symbol, direction, horizon, bars, scoring_mode="options", **_):
    i = len(bars) - 1
    return _Card("PASS" if i % 2 == 0 else "REJECT")


def _uptrend(n=200):
    return [_bar(i, 100.0 + i, 100.5 + i, 99.5 + i, 100.0 + i) for i in range(n)]


def _greedy(candidates, gap):
    taken = []
    for i in candidates:
        if not taken or i >= taken[-1] + gap:
            taken.append(i)
    return taken


def test_calibrate_buckets_distinct_setups_with_reproducible_ci():
    from evidence.score_calibration import calibrate, confidence_counts, replay

    bars = {"UP": _uptrend()}
    cfg = load_backtest_cfg("Swing")
    n_days, min_samples = int(cfg["n_days"]), int(cfg["min_samples"])
    warmup, last = 60, len(bars["UP"]) - n_days

    first = calibrate(bars, "Swing", "Bullish", scorer=_even_pass_scorer)
    second = calibrate(bars, "Swing", "Bullish", scorer=_even_pass_scorer)
    assert first == second

    by_bucket = {s.bucket: s for s in first}
    expected_pass = _greedy([i for i in range(warmup, last) if i % 2 == 0], n_days)
    expected_reject = _greedy([i for i in range(warmup, last) if i % 2 == 1], n_days)
    assert by_bucket["PASS"].n == len(expected_pass)
    assert by_bucket["REJECT"].n == len(expected_reject)
    assert by_bucket["CAUTION"].n == 0
    assert by_bucket["ALL"].n == len(_greedy(list(range(warmup, last)), n_days))

    # Every bar of a steady up-trend reaches the +target barrier before the stop.
    win_r = float(cfg["atr_mult_target"]) / float(cfg["atr_mult_stop"])
    assert by_bucket["PASS"].mean_r > 0
    assert by_bucket["PASS"].mean_r == pytest.approx(win_r)
    assert by_bucket["PASS"].ci_low <= by_bucket["PASS"].mean_r <= by_bucket["PASS"].ci_high

    # The confidence replay's sample size both ways, against min_samples.
    counts = confidence_counts(
        {"UP": replay(bars["UP"], "Swing", "Bullish", scorer=_even_pass_scorer)}, "Swing",
    )
    assert len(counts) == 1
    c = counts[0]
    assert c.overlapping == len([i for i in range(warmup, last) if i % 2 == 0])
    assert c.non_overlapping == len(expected_pass)
    assert c.min_samples == min_samples


def test_no_harness_module_mentions_get_bars():
    present = {p.name for p in EVIDENCE.glob("*.py")}
    assert set(HARNESS_MODULES) <= present
    for path in sorted(EVIDENCE.glob("*.py")):
        assert "get_bars" not in path.read_text(encoding="utf-8"), path.name
