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
