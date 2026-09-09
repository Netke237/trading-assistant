"""Pairing rules in scripts/iv_basis_analysis.py's HTTP source.

The instrument's whole value is that it never reports a number it did not
measure. `read_url` now takes the IV cut-offs off /api/scan/last-run, and those
are only meaningful if the SAME scan produced the rows they will be stamped
onto — /scan/last and /scan/last-run are two GETs and a scan can land between
them. These tests pin that: stamp when paired, stay silent when the backend
cannot pair, and refuse rather than mis-measure when the pairing keeps failing.

The script is not importable as a package module (it lives under scripts/ and
is run directly), so it is loaded by path.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "iv_basis_analysis.py"


def _load():
    spec = importlib.util.spec_from_file_location("iv_basis_analysis_under_test", _PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load()


def _stub_http(monkeypatch, mod, responses: dict[str, list]):
    """Serve a queued list of bodies per path; the last one repeats."""
    calls: list[str] = []

    @contextmanager
    def _fake_urlopen(url, timeout=None):
        path = url.split("://", 1)[-1].split("/", 1)[1]
        path = "/" + path
        calls.append(path)
        queue = responses[path]
        body = queue.pop(0) if len(queue) > 1 else queue[0]

        class _R:
            def read(self_inner):
                return json.dumps(body).encode() if body is not None else b""
        yield _R()

    # This patches the stdlib module the script imported, so it is global for
    # the duration -- monkeypatch restores it at teardown and pytest runs these
    # sequentially, but nothing else in this file may rely on real HTTP.
    monkeypatch.setattr(mod.urllib.request, "urlopen", _fake_urlopen)
    return calls


def test_thresholds_are_recorded_when_the_scan_ids_agree(mod, monkeypatch):
    _stub_http(monkeypatch, mod, {
        "/api/scan/last": [{"scan_id": "REC-A", "candidates": [], "rejected": []}],
        "/api/scan/last-run": [{
            "status": "complete", "direction": "Bearish", "horizon": "Swing",
            "universe": ["AAPL"], "scan_id": "REC-A",
            "iv_abs_threshold": 62.5, "iv_rank_threshold": 44.0,
        }],
    })
    result, request, src = mod.read_url("http://localhost:8000")
    assert result["scan_id"] == "REC-A"
    assert request["iv_abs_threshold"] == 62.5
    assert request["iv_rank_threshold"] == 44.0
    assert request["direction"] == "Bearish"
    assert "REC-A" in request["_threshold_source"]


def test_no_scan_id_leaves_the_thresholds_absent(mod, monkeypatch):
    """An older backend answers without scan_id. Absent, not 50: observations()
    records None and the report says the line is ASSUMED."""
    _stub_http(monkeypatch, mod, {
        "/api/scan/last": [{"scan_id": "REC-A", "candidates": [], "rejected": []}],
        "/api/scan/last-run": [{"status": "complete", "direction": "Bearish",
                                "horizon": "Swing", "universe": ["AAPL"]}],
    })
    _, request, _ = mod.read_url("http://localhost:8000")
    assert "iv_abs_threshold" not in request
    assert mod._num(request.get("iv_abs_threshold")) is None
    assert "not recorded" in request["_threshold_source"]


def test_a_scan_landing_between_the_two_gets_is_settled_by_one_reread(mod, monkeypatch):
    calls = _stub_http(monkeypatch, mod, {
        # First read is the old scan; by the time /scan/last-run answers, REC-B
        # has completed, and the second read of /scan/last sees it.
        "/api/scan/last": [
            {"scan_id": "REC-A", "candidates": [], "rejected": []},
            {"scan_id": "REC-B", "candidates": [], "rejected": []},
        ],
        "/api/scan/last-run": [{"status": "complete", "scan_id": "REC-B",
                                "iv_abs_threshold": 30.0, "iv_rank_threshold": 30.0}],
    })
    result, request, _ = mod.read_url("http://localhost:8000")
    assert calls.count("/api/scan/last") == 2
    assert result["scan_id"] == "REC-B"
    assert request["iv_abs_threshold"] == 30.0


def test_a_pairing_that_never_settles_is_refused_not_measured(mod, monkeypatch):
    _stub_http(monkeypatch, mod, {
        "/api/scan/last": [{"scan_id": "REC-A", "candidates": [], "rejected": []}],
        "/api/scan/last-run": [{"status": "complete", "scan_id": "REC-B",
                                "iv_abs_threshold": 30.0}],
    })
    with pytest.raises(SystemExit) as exc:
        mod.read_url("http://localhost:8000")
    assert "Nothing was written" in str(exc.value)


def test_no_scan_at_all_is_not_a_mismatch(mod, monkeypatch):
    """Empty backend: /scan/last is null and /scan/last-run pairs nothing. That
    is idle, not a race — it must not raise."""
    _stub_http(monkeypatch, mod, {
        "/api/scan/last": [None],
        "/api/scan/last-run": [{"status": "idle", "updated_at": None,
                                "scan_id": None, "iv_abs_threshold": None}],
    })
    result, request, _ = mod.read_url("http://localhost:8000")
    assert result is None
    assert "not recorded" in request["_threshold_source"]


def test_a_paired_scan_with_no_recorded_threshold_says_so(mod, monkeypatch):
    """The backend can hold a result whose request it lost (a scan_sessions row
    with last_result_json and no last_request_json survives a restart that
    way). scan_id then pairs but there is no threshold behind it — the
    provenance line must not claim one."""
    _stub_http(monkeypatch, mod, {
        "/api/scan/last": [{"scan_id": "REC-A", "candidates": [], "rejected": []}],
        "/api/scan/last-run": [{"status": "complete", "scan_id": "REC-A",
                                "iv_abs_threshold": None, "iv_rank_threshold": None}],
    })
    _, request, _ = mod.read_url("http://localhost:8000")
    assert request["iv_abs_threshold"] is None
    assert request["_threshold_source"].startswith("not recorded")


def test_the_endpoint_and_the_instrument_actually_agree(mod, client, monkeypatch):
    """End-to-end over the real router: run a scan with a non-default credit/
    debit line, then let read_url collect through the live endpoints. This is
    the contract the three ScanSessionStatus fields exist for — a unit test of
    either half would have kept passing while the pair drifted."""
    r = client.post("/api/scan", json={
        "universe": [], "direction": "Bearish", "horizon": "Swing",
        "overrides": {}, "iv_abs_threshold": 62.5, "iv_rank_threshold": 44.0,
    })
    assert r.status_code == 200
    scan_id = r.json()["scan_id"]

    @contextmanager
    def _via_testclient(url, timeout=None):
        path = "/" + url.split("://", 1)[-1].split("/", 1)[1]
        body = client.get(path).content

        class _R:
            def read(self_inner):
                return body
        yield _R()

    monkeypatch.setattr(mod.urllib.request, "urlopen", _via_testclient)
    result, request, src = mod.read_url("http://testserver")
    assert result["scan_id"] == scan_id
    assert request["iv_abs_threshold"] == 62.5
    assert request["iv_rank_threshold"] == 44.0
    assert request["direction"] == "Bearish"

    # And the value survives into the row shape the store keeps.
    meta_row = mod.observations(
        {**result, "candidates": [{"symbol": "ZZZ"}]}, request, "test",
    )
    assert meta_row[0]["iv_abs_threshold"] == 62.5


# ── Section 4: the credit/debit line is TWO lines, split by basis ────────────
#
# choose_primary reads `threshold = rank_threshold if iv_basis == "rank" else
# abs_threshold`, and scan.py sets the basis to "rank" whenever the ATM contract
# carried a vendor ivRank. So a rank source's COVERAGE decides which line each
# symbol exercises. A sample can therefore measure one line thoroughly and the
# other not at all -- and before these tests the report said nothing when a half
# was empty: it skipped the split silently under a heading naming ivAbsThreshold,
# then printed a green "all N checkable rows match" underneath. That is a report
# that looks healthy while answering nothing about the number it is named after.

class _Args:
    def __init__(self, **kw):
        self.horizon = kw.get("horizon")
        self.direction = kw.get("direction")
        self.store = kw.get("store", "<test>")
        self.include_alternatives = kw.get("include_alternatives", False)


def _row(symbol, figure, basis, *, spread_type=None, abs_thr=50.0, rank_thr=50.0):
    return {
        "scan_id": "s1",
        "scan_timestamp": "2026-09-09T14:00:00Z",
        "collected_at": "test",
        "direction": "Bearish",
        "horizon": "Swing",
        "row": "primary",
        "symbol": symbol,
        "stock_iv": figure,
        "stock_basis": basis,
        "contract_iv": figure,
        "contract_basis": basis,
        "iv_abs_threshold": abs_thr,
        "iv_rank_threshold": rank_thr,
        "spread_type": spread_type,
        "scan_rejected_iv_too_high": 0,
        "scan_rejected_iv_rank_too_high": 0,
    }


def _report(mod, rows, capsys, **kw):
    mod.report(rows, mod.load_thresholds(), _Args(**kw))
    return capsys.readouterr().out


def test_an_all_rank_bearish_sample_declares_ivabsthreshold_unmeasured(mod, capsys):
    """The tastytrade case: every symbol has a percentile, so the ABSOLUTE line
    never ran. Saying so is the whole finding -- it must not be silence."""
    out = _report(mod, [_row("AAPL", 62.0, "rank"), _row("MSFT", 41.0, "rank")], capsys)

    assert "ivAbsThreshold" in out
    assert "NO ROWS ON THIS BASIS -- ivAbsThreshold IS UNMEASURED BY THIS SAMPLE." in out
    # and the basis split is stated in counts, before either line is reported
    assert "rows by basis" in out
    assert out.index("rows by basis") < out.index("ivAbsThreshold  (rows on the absolute basis)")


def test_an_all_rank_sample_still_measures_the_rank_line(mod, capsys):
    """The other half of the same run: ivRankThreshold IS measurable here, and
    used to have no sensitivity table anywhere in the report."""
    out = _report(mod, [_row("AAPL", 62.0, "rank"), _row("MSFT", 41.0, "rank")], capsys)

    assert "ivRankThreshold" in out
    assert "NO ROWS ON THIS BASIS -- ivRankThreshold" not in out
    assert "at 50.0: bearish rank rows, n=2" in out
    assert "SENSITIVITY" in out


def test_an_all_absolute_bearish_sample_declares_ivrankthreshold_unmeasured(mod, capsys):
    """The mirror image -- the 2026-09-07 shape, with no rank source connected."""
    out = _report(mod, [_row("KO", 48.0, "absolute"), _row("XOM", 51.0, "absolute")], capsys)

    assert "NO ROWS ON THIS BASIS -- ivRankThreshold IS UNMEASURED BY THIS SAMPLE." in out
    assert "at 50.0: bearish absolute rows, n=2" in out


def test_each_basis_is_cut_by_its_own_recorded_threshold(mod, capsys):
    """The pairing itself. The two thresholds are given DIFFERENT values and the
    rows sit between them, so the printed split can only come out right if each
    basis was judged against the line choose_primary would actually apply to it.

    abs=40, rank=70. The absolute row at 55 is credit under 40 and would be debit
    under 70; the rank row at 55 is debit under 70 and would be credit under 40.
    Swapping the two thresholds inverts both counts.
    """
    rows = [_row("KO", 55.0, "absolute", abs_thr=40.0, rank_thr=70.0),
            _row("AAPL", 55.0, "rank", abs_thr=40.0, rank_thr=70.0)]
    out = _report(mod, rows, capsys)

    assert "at 40.0: bearish absolute rows, n=1" in out
    assert "at 70.0: bearish rank rows, n=1" in out
    # 55 >= 40 -> the absolute row sells premium; 55 < 70 -> the rank row buys it
    assert ">= 40.0  -> bear_call (SELL premium)      1 (100.0%)" in out
    assert ">= 70.0  -> bear_call (SELL premium)      0 (  0.0%)" in out
    assert "<  70.0  -> bear_put  (BUY  premium)      1 (100.0%)" in out


def test_a_basis_with_no_vol_reading_is_counted_not_judged(mod, capsys):
    """basis 'none' takes choose_primary's deliberate bear_put default without
    consulting either threshold, so it belongs in the counts and in neither
    line's sample."""
    rows = [_row("KO", 48.0, "absolute"), _row("PG", None, "none", spread_type="bear_put")]
    out = _report(mod, rows, capsys)

    assert "none          1" in out
    assert "judging no threshold" in out
    assert "at 50.0: bearish absolute rows, n=1" in out  # the 'none' row is excluded


def test_an_empty_basis_asserts_a_cause_only_when_there_were_bearish_rows(mod, capsys):
    """With no bearish rows, choose_primary never ran, so the basis mix is not
    evidence about which branch it would have taken. Naming a cause off an empty
    pool would be the same error the section exists to catch."""
    bullish = dict(_row("AAPL", 62.0, "rank"), direction="Bullish")
    out = _report(mod, [bullish], capsys)

    assert "NO ROWS ON THIS BASIS -- ivAbsThreshold IS UNMEASURED BY THIS SAMPLE." in out
    assert "choose_primary never ran" in out
    assert "took the RANK branch on" not in out
