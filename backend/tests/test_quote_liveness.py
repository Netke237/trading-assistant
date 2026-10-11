"""NO-LIVE-QUOTE NLQ-1: the quote classifier (plan 3a; tests T1, T2).

T1 is classify_quote's truth table. T2 replays the five raw Tradier samples
measured in Step 0 (plan section 1). The fixtures under
tests/fixtures/tradier_chain_raw/ are trimmed copies of
backend/scripts/out/tradier_chain_raw/<sample>/rows.csv, keeping only the four
columns the classifier reads (bid, ask, bid_date, ask_date; the dates are
Tradier's epoch milliseconds). Each file is named after its sample folder, whose
first token is the capture instant in UTC -- the `now` every row of that sample
is classified at.
"""
from __future__ import annotations

import csv
import logging
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.data.quote_liveness import classify_quote
from app.scoring import contract_validator
from app.services.market_session import MARKET_TZ, _market_session_open

NOW = 1_791_216_001.0          # 2026-10-05 12:00:01 ET, the in-session capture
MAX = 1800.0                   # 30 minutes, the shipped max_age_minutes


def _ms(age_s: float) -> int:
    """A Tradier stamp `age_s` seconds before NOW."""
    return int((NOW - age_s) * 1000)


def _c(bid=1.0, ask=1.2, bd=None, ad=None, *, session_open=True, lag=0.0, max_age=MAX, now=NOW):
    return classify_quote(bid, ask, bd, ad, now_s=now, session_open=session_open,
                          feed_lag_s=lag, max_age_s=max_age)


# ── T1: truth table ──────────────────────────────────────────────────────────

def test_two_sided_young_in_session_is_live():
    assert _c(bd=_ms(4), ad=_ms(9)) == ("live", 4.0)


def test_bid_zero_is_one_sided_whatever_else_holds():
    # Rule 1 comes first: closed session, stale stamps and no stamps all lose to it.
    assert _c(bid=0.0, bd=_ms(5), ad=_ms(5))[0] == "one_sided"
    assert _c(bid=0.0, bd=_ms(5), ad=_ms(5), session_open=False)[0] == "one_sided"
    assert _c(bid=0.0, bd=_ms(86_400), ad=_ms(86_400))[0] == "one_sided"
    assert _c(bid=0.0)[0] == "one_sided"
    assert _c(bid=-0.01, bd=_ms(5), ad=_ms(5))[0] == "one_sided"


def test_session_closed_beats_the_age_rules():
    # Rule 2 before rules 3-4: no stamps and old stamps read session_closed, not stale.
    assert _c(session_open=False) == ("session_closed", None)
    assert _c(bd=_ms(86_400), ad=_ms(86_400), session_open=False)[0] == "session_closed"


def test_1605_with_five_minute_old_stamps_is_session_closed():
    """The closing quotes are young from 16:00 to 16:15: no row field catches
    them, only the session test (plan section 1, point 6). The after-close
    sample in T2 is 45 minutes old and would not catch a missing session clause."""
    at_1605 = datetime(2026, 10, 5, 16, 5, tzinfo=MARKET_TZ)
    session_open = _market_session_open(at_1605)
    assert session_open is False
    state, age = classify_quote(2.0, 2.1, int((at_1605.timestamp() - 300) * 1000),
                                int((at_1605.timestamp() - 300) * 1000),
                                now_s=at_1605.timestamp(), session_open=session_open,
                                feed_lag_s=0.0, max_age_s=MAX)
    assert state == "session_closed"
    assert age == pytest.approx(300.0)


@pytest.mark.parametrize("absent", [None, 0, -5, "1791216001000", True, False, math.nan, math.inf, 10 ** 400],
                         ids=["none", "zero", "negative", "string", "true", "false", "nan", "inf", "huge-int"])
def test_both_stamps_absent_is_stale_with_no_age(absent):
    assert _c(bd=absent, ad=absent) == ("stale", None)


def test_one_absent_stamp_falls_back_to_the_other():
    assert _c(bd=0, ad=_ms(12)) == ("live", 12.0)
    assert _c(bd=_ms(12), ad="x") == ("live", 12.0)
    assert _c(bd=None, ad=_ms(MAX + 60)) == ("stale", MAX + 60)


def test_the_fresher_side_is_judged_not_the_older():
    # A quiet far-OTM strike: one side an hour old, the other seconds old.
    assert _c(bd=_ms(3600), ad=_ms(6)) == ("live", 6.0)
    assert _c(bd=_ms(6), ad=_ms(3600)) == ("live", 6.0)


def test_negative_age_is_live():
    # The host clock ran ~5 s behind Tradier (plan section 1, point 7).
    state, age = _c(bd=_ms(-5.3), ad=_ms(-5.3))
    assert state == "live"
    assert age == pytest.approx(-5.3, abs=1e-3)


def test_max_age_boundary_is_inclusive():
    assert _c(bd=_ms(MAX), ad=_ms(MAX))[0] == "live"
    assert _c(bd=_ms(MAX + 1), ad=_ms(MAX + 1))[0] == "stale"


def test_feed_lag_is_subtracted_from_the_age():
    # The sandbox serves 15-minute-delayed quotes: 40 minutes on the wall clock
    # is 25 minutes old in the feed's own clock.
    assert _c(bd=_ms(2400), ad=_ms(2400), lag=900.0) == ("live", 1500.0)
    assert _c(bd=_ms(2400), ad=_ms(2400)) == ("stale", 2400.0)


def test_age_is_reported_with_every_state():
    assert _c(bid=0.0, bd=_ms(70), ad=_ms(40)) == ("one_sided", 40.0)
    assert _c(bd=_ms(70), ad=_ms(40), session_open=False) == ("session_closed", 40.0)


# ── T2: replay of the five Step 0 samples ────────────────────────────────────

FIXTURES = Path(__file__).parent / "fixtures" / "tradier_chain_raw"

# (sample, rows in the file, expected counts at 30 minutes). Every row of every
# sample has ask > 0 (plan section 1), so none is dropped before the classifier.
SAMPLES = [
    ("20261003T210145Z_weekend", 980, {"session_closed": 731, "one_sided": 249}),
    ("20261005T060215Z_overnight-check", 972, {"session_closed": 748, "one_sided": 224}),
    ("20261005T123001Z_pre-market", 972, {"session_closed": 748, "one_sided": 224}),
    ("20261005T160001Z_in-session", 972, {"live": 741, "one_sided": 231}),
    ("20261005T204500Z_after-close", 972, {"session_closed": 737, "one_sided": 235}),
]


def _num(raw: str):
    try:
        return int(raw)
    except ValueError:
        try:
            return float(raw)
        except ValueError:
            return None


def _replay(sample: str) -> tuple[int, Counter]:
    captured = datetime.strptime(sample.split("_")[0], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    session_open = _market_session_open(captured.astimezone(MARKET_TZ))
    counts: Counter = Counter()
    with open(FIXTURES / f"{sample}.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        bid, ask = float(r["bid"] or 0), float(r["ask"] or 0)
        if not ask > 0:   # the chain builders drop these before classifying
            counts["dropped"] += 1
            continue
        state, _ = classify_quote(bid, ask, _num(r["bid_date"]), _num(r["ask_date"]),
                                  now_s=captured.timestamp(), session_open=session_open,
                                  feed_lag_s=0.0,   # production base: no feed lag
                                  max_age_s=MAX)
        counts[state] += 1
    return len(rows), counts


@pytest.mark.parametrize("sample,n_rows,expected", SAMPLES, ids=[s[0].split("_", 1)[1] for s in SAMPLES])
def test_replay_of_the_step0_samples(sample, n_rows, expected):
    n, counts = _replay(sample)
    assert n == n_rows
    assert dict(counts) == expected


def test_replay_off_hours_samples_have_no_live_row():
    for sample, _, _ in SAMPLES:
        if "in-session" not in sample:
            assert _replay(sample)[1]["live"] == 0, sample


def test_the_replay_runs_at_the_shipped_threshold():
    assert contract_validator.max_quote_age_seconds() == MAX


# ── The config key ───────────────────────────────────────────────────────────

def _with_cfg(monkeypatch, cfg):
    monkeypatch.setattr(contract_validator, "_load_config", lambda: cfg)
    monkeypatch.setattr(contract_validator, "_warned_quote_age", set())


def test_shipped_yaml_sets_30_minutes():
    assert contract_validator._load_config()["quote_liveness"] == {"max_age_minutes": 30}


def test_a_valid_value_is_read_in_minutes(monkeypatch):
    _with_cfg(monkeypatch, {"quote_liveness": {"max_age_minutes": 45}})
    assert contract_validator.max_quote_age_seconds() == 2700.0
    _with_cfg(monkeypatch, {"quote_liveness": {"max_age_minutes": 2.5}})
    assert contract_validator.max_quote_age_seconds() == 150.0


@pytest.mark.parametrize("cfg", [
    {}, {"quote_liveness": None}, {"quote_liveness": {}}, {"quote_liveness": {"max_age_minutes": None}},
    {"quote_liveness": {"max_age_minutes": "30"}}, {"quote_liveness": {"max_age_minutes": True}},
    {"quote_liveness": {"max_age_minutes": 0}}, {"quote_liveness": {"max_age_minutes": -5}},
    {"quote_liveness": {"max_age_minutes": math.nan}}, {"quote_liveness": {"max_age_minutes": math.inf}},
], ids=["no-block", "null-block", "empty-block", "null", "string", "bool", "zero", "negative", "nan", "inf"])
def test_an_unusable_value_falls_back_to_30_and_warns_once(monkeypatch, caplog, cfg):
    _with_cfg(monkeypatch, cfg)
    with caplog.at_level(logging.WARNING, logger="app.scoring.contract_validator"):
        assert contract_validator.max_quote_age_seconds() == 1800.0
        assert contract_validator.max_quote_age_seconds() == 1800.0
    warnings = [r for r in caplog.records if "max_age_minutes" in r.getMessage()]
    assert len(warnings) == 1
