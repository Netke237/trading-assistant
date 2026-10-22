"""scripts/tradier_chain_raw_sample.py -- NO-LIVE-QUOTE Step 0 measurement script.

Loaded by path (like tests/test_p3c_data_checks.py). Tradier is mocked with
respx; nothing here touches the network.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
import respx

BACKEND = Path(__file__).resolve().parent.parent
_PATH = BACKEND / "scripts" / "tradier_chain_raw_sample.py"

PROD = "https://api.tradier.com"
TOKEN = "test-token-abc123"
# Monday 2026-10-05 20:30 UTC = 16:30 EDT: after the close.
NOW = datetime(2026, 10, 5, 20, 30, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("tradier_chain_raw_sample_under_test", _PATH)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def env(mod, monkeypatch, tmp_path):
    monkeypatch.setenv("TRADIER_API_TOKEN", TOKEN)
    monkeypatch.setattr(mod, "_utcnow", lambda: NOW)
    return tmp_path


def _opt(strike, otype, bid, ask, last, *, bid_age=None, ask_age=None, trade_age=None, **extra):
    def stamp(age):
        return 0 if age is None else NOW_MS - int(age * 1000)
    row = {
        "symbol": f"AAPL261016{otype[0].upper()}{int(strike * 1000):08d}",
        "option_type": otype, "strike": strike, "expiration_date": "2026-10-16",
        "bid": bid, "ask": ask, "last": last, "close": last, "prevclose": None,
        "volume": 3, "open_interest": 120, "bidsize": 1, "asksize": 2,
        "bid_date": stamp(bid_age), "ask_date": stamp(ask_age), "trade_date": stamp(trade_age),
        "greeks": {"delta": 0.4, "updated_at": "2026-10-05 20:29:00"},
    }
    row.update(extra)
    return row


CHAIN_A = [
    _opt(200, "call", 1.00, 1.20, 1.10, bid_age=30, ask_age=40, trade_age=600),   # two-sided, live
    _opt(205, "call", 0, 0, 2.50, trade_age=3 * 3600),                            # app fabricates 0% spread
    _opt(210, "call", 0, 0, 0),                                                   # app drops this row
    _opt(215, "put", 0, 0.05, None, ask_age=2 * 86400),                           # bid 0, ask > 0
    _opt(220, "put", None, None, None, bid_date=None, ask_date=None, trade_date=None),  # nulls
]
# Second expiry: Tradier collapses a one-row chain to a bare dict.
CHAIN_B_SINGLE = _opt(200, "call", 3.0, 3.4, 3.1, bid_age=5 * 86400, ask_age=5 * 86400,
                      expiration_date="2026-11-06")


def _mock_ok(router, chain_b=None):
    router.get(f"{PROD}/v1/markets/clock").mock(return_value=httpx.Response(
        200, json={"clock": {"state": "postmarket", "description": "Market is in post-hours"}}))
    router.get(f"{PROD}/v1/markets/options/expirations").mock(return_value=httpx.Response(
        200, json={"expirations": {"date": ["2026-10-07", "2026-10-16", "2026-11-06", "2026-12-18"]}}))

    def chain(request):
        exp = request.url.params["expiration"]
        if exp == "2026-10-16":
            return httpx.Response(200, json={"options": {"option": CHAIN_A}})
        if chain_b is not None:
            return chain_b
        return httpx.Response(200, json={"options": {"option": CHAIN_B_SINGLE}})
    return router.get(f"{PROD}/v1/markets/options/chains").mock(side_effect=chain)


def _run_dir(out: Path) -> Path:
    dirs = list(out.iterdir())
    assert len(dirs) == 1
    return dirs[0]


# ── the run ──────────────────────────────────────────────────────────────────

def test_full_run_records_every_row_including_the_ones_the_app_drops(mod, env, capsys):
    with respx.mock(assert_all_called=True) as router:
        chains = _mock_ok(router)
        rc = mod.main(["--symbols", "aapl", "--out-dir", str(env), "--label", "after-close"])
    assert rc == 0

    # Production base, bearer token, greeks requested, both picked expiries fetched.
    reqs = [c.request for c in chains.calls]
    assert {r.url.params["expiration"] for r in reqs} == {"2026-10-16", "2026-11-06"}
    for r in reqs:
        assert str(r.url).startswith(PROD + "/")
        assert r.url.params["greeks"] == "true"
        assert r.url.params["symbol"] == "AAPL"
        assert r.headers["Authorization"] == f"Bearer {TOKEN}"

    run = _run_dir(env)
    assert run.name == "20261005T203000Z_after-close"

    with open(run / "rows.csv", newline="", encoding="utf-8") as fh:
        csv_rows = list(csv.DictReader(fh))
    assert len(csv_rows) == 6  # 5 + the collapsed single-dict chain
    by_strike = {(r["expiry"], r["strike"], r["option_type"]): r for r in csv_rows}
    dropped = by_strike[("2026-10-16", "210", "call")]
    assert (dropped["bid"], dropped["ask"], dropped["last"]) == ("0", "0", "0")
    assert dropped["app_drops_row"] == "True"
    fabricated = by_strike[("2026-10-16", "205", "call")]
    assert fabricated["app_fabricates_zero_spread"] == "True" and fabricated["two_sided"] == "False"
    live = by_strike[("2026-10-16", "200", "call")]
    assert float(live["bid_date_age_s"]) == pytest.approx(30)
    assert float(live["ask_date_age_s"]) == pytest.approx(40)
    assert float(live["trade_date_age_s"]) == pytest.approx(600)
    assert live["base_url"] == PROD
    assert live["capture_utc"] == "2026-10-05T20:30:00+00:00"
    assert live["capture_et"] == "2026-10-05T16:30:00-04:00"
    assert live["greeks_updated_at"] == "2026-10-05 20:29:00"
    assert live["dte"] == "11"
    # A zero stamp is "absent", not 56 years old.
    assert by_strike[("2026-10-16", "205", "call")]["bid_date_age_s"] == ""

    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    c = summary["counts"]
    assert c == {
        "rows": 6, "bid_0": 4, "ask_0": 3, "both_0": 3, "ask_0_last_gt_0": 1,
        "bid_0_ask_gt_0": 1, "two_sided": 2, "crossed_ask_lt_bid": 0,
        "both_0_last_0": 2, "bid_null": 1, "ask_null": 1,
    }
    assert summary["per_symbol"]["AAPL"]["rows"] == 6
    ages = summary["quote_age_two_sided_rows"]["bid_date"]
    assert ages["n"] == 2 and ages["missing_or_zero"] == 0
    assert ages["buckets"]["<1m"] == 1 and ages["buckets"][">=3d"] == 1
    assert summary["quote_age_all_rows"]["ask_date"]["missing_or_zero"] == 3

    meta = summary["meta"]
    assert meta["session_phase"] == "after-close" and meta["label"] == "after-close"
    assert meta["sandbox"] is False and meta["base_url"] == PROD
    assert meta["tradier_clock"]["state"] == "postmarket"
    assert meta["expiries"] == {"AAPL": ["2026-10-16", "2026-11-06"]}

    # Raw Tradier rows kept in full in rows.json.
    full = json.loads((run / "rows.json").read_text(encoding="utf-8"))
    assert full["rows"][0]["raw"]["greeks"]["delta"] == 0.4

    # The token is never written anywhere.
    for f in run.iterdir():
        assert TOKEN not in f.read_text(encoding="utf-8")
    out = capsys.readouterr().out
    assert "ask_0_last_gt_0" in out and TOKEN not in out


def test_a_failing_chain_is_recorded_and_the_rest_still_written(mod, env):
    with respx.mock() as router:
        _mock_ok(router, chain_b=httpx.Response(500, json={}))
        rc = mod.main(["--symbols", "AAPL", "--out-dir", str(env)])
    assert rc == 0
    summary = json.loads((_run_dir(env) / "summary.json").read_text(encoding="utf-8"))
    assert summary["counts"]["rows"] == 5
    assert any("2026-11-06 chain" in e for e in summary["meta"]["errors"])


def test_clock_failure_is_not_fatal(mod, env):
    with respx.mock() as router:
        _mock_ok(router)
        router.get(f"{PROD}/v1/markets/clock").mock(return_value=httpx.Response(503))
        rc = mod.main(["--symbols", "AAPL", "--out-dir", str(env), "--expiries-per-symbol", "1"])
    assert rc == 0
    meta = json.loads((_run_dir(env) / "summary.json").read_text(encoding="utf-8"))["meta"]
    assert meta["tradier_clock"] is None and "503" in meta["tradier_clock_error"]
    assert meta["expiries"] == {"AAPL": ["2026-10-16"]}


def test_no_rows_exits_1(mod, env):
    with respx.mock() as router:
        router.get(f"{PROD}/v1/markets/clock").mock(return_value=httpx.Response(200, json={}))
        router.get(f"{PROD}/v1/markets/options/expirations").mock(
            return_value=httpx.Response(200, json={"expirations": None}))
        assert mod.main(["--symbols", "AAPL", "--out-dir", str(env)]) == 1


# ── refusals ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("base", ["https://sandbox.tradier.com", "https://sandbox.tradier.com/"])
def test_sandbox_base_is_refused_without_the_flag(mod, env, base, capsys):
    with respx.mock(assert_all_mocked=True) as router:
        assert mod.main(["--base-url", base, "--out-dir", str(env)]) == 2
        assert not router.calls
    assert "REFUSED" in capsys.readouterr().err
    assert not any(env.iterdir())


def test_sandbox_with_flag_runs_and_is_marked(mod, env):
    sb = "https://sandbox.tradier.com"
    with respx.mock() as router:
        router.get(f"{sb}/v1/markets/clock").mock(return_value=httpx.Response(200, json={}))
        router.get(f"{sb}/v1/markets/options/expirations").mock(return_value=httpx.Response(
            200, json={"expirations": {"date": "2026-10-16"}}))  # collapsed to a bare string
        router.get(f"{sb}/v1/markets/options/chains").mock(return_value=httpx.Response(
            200, json={"options": {"option": [CHAIN_B_SINGLE]}}))
        assert mod.main(["--base-url", sb, "--allow-sandbox", "--symbols", "AAPL",
                         "--out-dir", str(env)]) == 0
    meta = json.loads((_run_dir(env) / "summary.json").read_text(encoding="utf-8"))["meta"]
    assert meta["sandbox"] is True and meta["base_url"] == sb


def test_tradier_base_url_env_is_ignored(mod, env, monkeypatch):
    """An app .env pointing at the sandbox must not redirect the measurement."""
    monkeypatch.setenv("TRADIER_BASE_URL", "https://sandbox.tradier.com")
    with respx.mock() as router:
        _mock_ok(router)
        assert mod.main(["--symbols", "AAPL", "--out-dir", str(env)]) == 0


def test_missing_token_is_refused(mod, env, monkeypatch, capsys):
    monkeypatch.delenv("TRADIER_API_TOKEN", raising=False)
    # No automatic prompt: on Windows isatty() is True for NUL, so one would hang.
    monkeypatch.setattr(mod.getpass, "getpass", lambda *a, **k: pytest.fail("prompted"))
    with respx.mock(assert_all_mocked=True) as router:
        assert mod.main(["--out-dir", str(env)]) == 2
        assert not router.calls
    assert "TRADIER_API_TOKEN" in capsys.readouterr().err


def test_token_env_name_is_configurable(mod, env, monkeypatch):
    monkeypatch.delenv("TRADIER_API_TOKEN", raising=False)
    monkeypatch.setenv("MY_TRADIER_PROD", TOKEN)
    with respx.mock() as router:
        chains = _mock_ok(router)
        assert mod.main(["--token-env", "MY_TRADIER_PROD", "--symbols", "AAPL",
                         "--out-dir", str(env)]) == 0
    assert chains.calls[0].request.headers["Authorization"] == f"Bearer {TOKEN}"


# ── helpers ──────────────────────────────────────────────────────────────────

def test_sandbox_rule_matches_the_app(mod):
    from app.data.market import _is_sandbox_base
    for base in ["https://sandbox.tradier.com", "https://sandbox.tradier.com/",
                 "https://api.tradier.com", "", "http://localhost:1234"]:
        assert mod.is_sandbox_base(base) == _is_sandbox_base(base), base


@pytest.mark.parametrize("utc, phase", [
    (datetime(2026, 10, 5, 13, 29, tzinfo=timezone.utc), "pre-market"),    # 09:29 EDT
    (datetime(2026, 10, 5, 13, 30, tzinfo=timezone.utc), "in-session"),    # 09:30 EDT
    (datetime(2026, 10, 5, 19, 59, tzinfo=timezone.utc), "in-session"),    # 15:59 EDT
    (datetime(2026, 10, 5, 20, 0, tzinfo=timezone.utc), "after-close"),    # 16:00 EDT
    (datetime(2026, 12, 7, 14, 0, tzinfo=timezone.utc), "pre-market"),     # 09:00 EST
    (datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc), "weekend"),        # Saturday
    (datetime(2026, 10, 6, 1, 0, tzinfo=timezone.utc), "after-close"),     # Mon 21:00 EDT
])
def test_session_phase(mod, utc, phase):
    assert mod.session_phase(utc) == phase


def test_pick_expiries(mod):
    today = date(2026, 10, 5)
    dates = ["2026-10-07", "2026-10-09", "2026-10-16", "2026-11-06", "2026-12-18", "bad"]
    # nearest at/after 5 DTE is 10-16 (11 DTE); closest to 30 DTE is 11-06 (32 DTE)
    assert mod.pick_expiries(dates, today, 2, 5, 30) == ["2026-10-16", "2026-11-06"]
    assert mod.pick_expiries(dates, today, 1, 5, 30) == ["2026-10-16"]
    # both rules land on the same expiry -> one pick, not a duplicate
    assert mod.pick_expiries(dates, today, 2, 5, 10) == ["2026-10-16"]
    assert mod.pick_expiries(dates, today, 2, 100, 30) == []


def test_prompt_token_reads_getpass_not_the_env(mod, env, monkeypatch):
    monkeypatch.setenv("TRADIER_API_TOKEN", "env-token-must-not-be-used")
    monkeypatch.setattr(mod.getpass, "getpass", lambda *a, **k: f"  {TOKEN}  ")
    with respx.mock() as router:
        chains = _mock_ok(router)
        assert mod.main(["--prompt-token", "--symbols", "AAPL", "--out-dir", str(env)]) == 0
    assert chains.calls[0].request.headers["Authorization"] == f"Bearer {TOKEN}"
