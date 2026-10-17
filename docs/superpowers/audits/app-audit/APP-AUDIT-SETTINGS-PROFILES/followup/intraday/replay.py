"""Offline SPY 15-minute audit; run with backend/.venv/bin/python (3.11).

Default never fetches. Optional --fetch only permits the fixed Tradier market-data
GET; it writes a NEW capture directory and never replaces this audit's fixture.
"""
from __future__ import annotations

import argparse
import asyncio
import faulthandler
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import socket
import sys
from unittest.mock import patch
from zoneinfo import ZoneInfo

# Pin thread count before importing numerical libraries; no optimizer changes.
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[6]
SOURCE = "4b1f6b86e8137f499da0c4c430f23b9c250fd8de"
sys.path.insert(0, str(ROOT / "backend"))
STATES = ["Bull", "Bear", "Choppy"]
QUERY = dict(symbol="SPY", interval="15min", start="2026-09-01",
             end="2026-10-15", session_filter="all")
ENDPOINT = "https://api.tradier.com/v1/markets/timesales"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(values):
    """Compact complete-array comparison; original bar values remain in fixture."""
    encoded = json.dumps(values, separators=(",", ":"), sort_keys=True, allow_nan=False).encode()
    return dict(count=len(values), sha256=hashlib.sha256(encoded).hexdigest(), first=values[0], last=values[-1])


def fetch_new(destination):
    """Explicit opt-in read-only request. No app boot or credential-store use."""
    from urllib.parse import urlencode
    from urllib.request import Request, build_opener, HTTPRedirectHandler
    token = os.environ.get("TRADIER_API_TOKEN")
    if not token:
        raise SystemExit("--fetch requires the configured runtime TRADIER_API_TOKEN binding")
    destination.mkdir(parents=True, exist_ok=False)
    requested = datetime.now(timezone.utc).isoformat()
    request = Request(ENDPOINT + "?" + urlencode(QUERY),
                      headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                      method="GET")
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    # Never log request headers or exceptions that may carry transport details.
    try:
        # Default urllib handlers retain configured proxy and CA trust settings.
        with build_opener(NoRedirect).open(request, timeout=30) as response:
            payload = response.read()
            receipt = datetime.now(timezone.utc).isoformat()
            headers = dict(http_status=response.status, response_date=response.headers.get("Date"),
                           content_type=response.headers.get("Content-Type"))
    except Exception:
        raise SystemExit("Read-only market-data capture failed; no credentials logged") from None
    data = json.loads(payload)["series"]["data"]
    if not isinstance(data, list) or not data:
        raise SystemExit("Read-only response contained no bar array")
    (destination / "spy-15min-response.json").write_bytes(payload)
    provenance = dict(provider="Tradier", endpoint=ENDPOINT, query=QUERY,
                      requested_at_utc=requested, received_at_utc=receipt, **headers,
                      kind="read-only market data; no app backend, account, order or notification call",
                      response_sha256=hashlib.sha256(payload).hexdigest(), bar_count=len(data),
                      first_time=data[0]["time"], last_time=data[-1]["time"], status="captured")
    (destination / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print("Captured fixed SPY market-data query in new destination; committed offline fixture unchanged.")


def independent_parse(raw):
    bars, mismatches, bad = [], [], []
    for i, row in enumerate(raw):
        dt = datetime.fromisoformat(row["time"])
        assert dt.tzinfo is None, "Fixture contract is Eastern-naive provider time"
        epoch = int(dt.replace(tzinfo=ZoneInfo("America/New_York")).timestamp())
        if epoch != row["timestamp"]:
            mismatches.append(i)
        values = [row[k] for k in ("open", "high", "low", "close", "price", "volume", "vwap")]
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values):
            bad.append(i)
        if not (0 < row["low"] <= min(row["open"], row["close"]) <= max(row["open"], row["close"]) <= row["high"]
                and row["volume"] >= 0):
            bad.append(i)
        bars.append(dict(time=epoch, **{k: round(float(row[k]), 4) for k in ("open", "high", "low", "close")},
                         volume=int(row["volume"])))
    times = [b["time"] for b in bars]
    validation = dict(bar_count=len(raw), duplicate_timestamps=len(times)-len(set(times)),
                      strictly_ascending=all(a < b for a, b in zip(times, times[1:])),
                      eastern_vs_provider_epoch_mismatch_indices=mismatches,
                      invalid_finite_ohlc_volume_indices=sorted(set(bad)),
                      aligned_to_15min=all(t % 900 == 0 for t in times),
                      first_epoch=times[0], last_epoch=times[-1],
                      per_eastern_date=dict(Counter(row["time"][:10] for row in raw)))
    assert not mismatches and not bad and validation["duplicate_timestamps"] == 0
    assert validation["strictly_ascending"] and validation["aligned_to_15min"]
    return bars, validation


def expected_omm(closes, *, lookback=26, window=500, min_obs=100, threshold=.002, smoothing=.2):
    """Independent scalar labels/stride counts/units; no production helper use."""
    labels, signal = [], 0.0
    for i, close in enumerate(closes):
        if i < lookback:
            labels.append("Choppy")
            continue
        delta = (close - closes[i-lookback]) / closes[i-lookback]
        signal = smoothing * signal + (1-smoothing) * delta if smoothing else delta
        labels.append("Bull" if signal > threshold else "Bear" if signal < -threshold else "Choppy")
    if len(closes) < lookback + 2:
        return None, dict(labels=labels, reason="fewer than lookback+2 bars")
    current = labels[-1]
    recent = labels[-window:]
    sampled = recent[::lookback]
    pairs = Counter(zip(sampled[:-1], sampled[1:]))
    counts = [[pairs[a, b] for b in STATES] for a in STATES]
    details = dict(labels=labels, current_observations=recent.count(current),
                   sampled_labels=sampled, transition_counts=counts)
    if recent.count(current) < min_obs:
        return None, dict(**details, reason="current-state observations below min_obs")
    row_counts = counts[STATES.index(current)]
    total = sum(row_counts)
    row = [n / total if total else 1/3 for n in row_counts]
    stay = row[STATES.index(current)]
    age = 0
    for label in reversed(labels):
        if label != current:
            break
        age += 1
    conv = round(100 * (row[0] - row[1]))
    return dict(state=current, p_stay=round(stay, 4),
                transition_row=[round(p, 4) for p in row], state_order=STATES,
                regime_age_days=age, avg_regime_duration=round(min(1/(1-stay) if 1-stay > 1e-9 else math.inf, 9999), 1),
                stability="Stable" if stay >= .75 else "Fragile", conviction_pct=conv), details


def forward(returns, parameters):
    """Scalar, scaled causal recursion using captured fitted emissions."""
    probs = parameters["start"][:]
    for t, value in enumerate(returns):
        prior = probs if t == 0 else [sum(probs[i] * parameters["trans"][i][j] for i in range(3)) for j in range(3)]
        weighted = [prior[j] * math.exp(-.5 * (value-parameters["means"][j])**2 / parameters["variances"][j])
                    / math.sqrt(2 * math.pi * parameters["variances"][j]) for j in range(3)]
        mass = sum(weighted)
        assert mass > 0 and math.isfinite(mass)
        probs = [p/mass for p in weighted]
    return probs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", type=Path, metavar="NEW_DIRECTORY")
    parser.add_argument("--output", type=Path, default=HERE / "output.json")
    args = parser.parse_args()
    if args.fetch:
        fetch_new(args.fetch)
        return
    faulthandler.dump_traceback_later(45, repeat=True)
    # asyncio.to_thread needs local wakeup sockets on this runtime. Permit
    # loopback/Unix sockets while making external outbound I/O fail closed.
    original_connect, original_connect_ex = socket.socket.connect, socket.socket.connect_ex
    original_getaddrinfo = socket.getaddrinfo
    def local_address(address):
        return not isinstance(address, tuple) or address[0] in ("127.0.0.1", "::1", "localhost")
    def connect(sock, address):
        if not local_address(address):
            raise RuntimeError("Offline replay blocked outbound socket")
        return original_connect(sock, address)
    def connect_ex(sock, address):
        if not local_address(address):
            raise RuntimeError("Offline replay blocked outbound socket")
        return original_connect_ex(sock, address)
    def getaddrinfo(host, *args, **kwargs):
        if host not in (None, "127.0.0.1", "::1", "localhost"):
            raise RuntimeError("Offline replay blocked outbound DNS")
        return original_getaddrinfo(host, *args, **kwargs)
    socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = connect, connect_ex, getaddrinfo
    assert sys.version_info[:2] == (3, 11), "Backend audit requires Python 3.11"
    from app.data import market
    from app.services import regime_hmm, regime_omm
    from app.routers import regime as router
    from hmmlearn.hmm import GaussianHMM

    raw_path = HERE / "spy-15min-response.json"
    provenance = json.loads((HERE / "provenance.json").read_text())
    assert sha(raw_path) == provenance["response_sha256"]
    assert provenance["query"] == QUERY and provenance["endpoint"] == ENDPOINT
    payload = json.loads(raw_path.read_text())
    raw = payload["series"]["data"]
    bars, validation = independent_parse(raw)
    assert len(bars) == provenance["bar_count"]
    assert provenance["first_time"] == raw[0]["time"] and provenance["last_time"] == raw[-1]["time"]
    frozen_now = datetime.fromisoformat(provenance["received_at_utc"]).timestamp()
    expected_complete = [b for b in bars if b["time"] + 900 <= frozen_now]
    actual_complete = market.completed_intraday_bars(bars, now=frozen_now, feed_lag=0)
    checks = []

    def check(name, expected, actual):
        item = dict(name=name, expected=expected, actual=actual, passed=expected == actual)
        checks.append(item)
        return item

    check("frozen_completed_bar_filter", fingerprint([b["time"] for b in expected_complete]), fingerprint([b["time"] for b in actual_complete]))
    # Exercise actual adapter parsing/normalization, keeping every provider offline.
    class Response:
        def raise_for_status(self):
            return None
        def json(self):
            return payload
    with patch.object(market, "get_tradier_creds", return_value=("offline-fixture", "https://api.tradier.com")), \
         patch.object(market, "_tradier_get", return_value=Response()) as get, \
         patch.object(market, "_fetch_intraday_yf", return_value=[]), \
         patch.object(market, "_now", return_value=frozen_now):
        parsed_actual = market.fetch_intraday_candles("SPY", interval="15min", days=55)
        check("actual_adapter_single_mocked_marketdata_call", 1, get.call_count)
        check("actual_adapter_session_filter", "all", get.call_args.kwargs["params"]["session_filter"])
    check("actual_adapter_parse", fingerprint(bars), fingerprint(parsed_actual))
    # Exact completion boundary, one second either side, live and delayed feeds.
    boundary = []
    for lag in (0, 900):
        end = bars[-1]["time"] + 900 + lag
        for delta in (-1, 0, 1):
            actual = market.completed_intraday_bars([bars[-1]], now=end+delta, feed_lag=lag)
            boundary.append(check(f"completion_lag_{lag}_delta_{delta}", delta >= 0, bool(actual)))
    cutoff_record = dict(frozen_utc=datetime.fromtimestamp(frozen_now, timezone.utc).isoformat(),
                         feed_lag_seconds=0, bar_seconds=900, completed=len(actual_complete),
                         dropped=len(bars)-len(actual_complete), last_bar_utc=datetime.fromtimestamp(bars[-1]["time"], timezone.utc).isoformat())
    models, fitted_inputs = [], []
    def capture_model(**kwargs):
        model = GaussianHMM(**kwargs)
        original = model.fit
        def fitted(X, *args, **kwargs):
            fitted_inputs.append(X.copy())
            return original(X, *args, **kwargs)
        model.fit = fitted
        models.append(model)
        return model
    with patch("hmmlearn.hmm.GaussianHMM", capture_model):
        actual_hmm = regime_hmm.compute_intraday_hmm(actual_complete)
    assert len(models) == 1 and actual_hmm is not None
    model = models[0]
    capped = expected_complete[-800:]
    expected_returns = [(capped[i]["close"] - capped[i-1]["close"]) / capped[i-1]["close"] for i in range(1, len(capped))]
    check("hmm_fit_inputs_cap_800_bars_799_returns", fingerprint(expected_returns), fingerprint(fitted_inputs[0].reshape(-1).tolist()))
    params = dict(start=model.startprob_.tolist(), trans=model.transmat_.tolist(),
                  means=model.means_.reshape(-1).tolist(), variances=[float(v.reshape(-1)[0]) for v in model.covars_])
    probs = forward(expected_returns[-30:], params)
    actual_probs = model.predict_proba(fitted_inputs[0][-30:])[-1].tolist()
    error = max(abs(a-b) for a, b in zip(probs, actual_probs))
    check("scalar_forward_terminal_posterior_error_below_1e-12", True, error < 1e-12)
    ratios = [abs(m) / (math.sqrt(v)+1e-10) for m, v in zip(params["means"], params["variances"])]
    assert len(set(ratios)) == 3, "Label ties require explicit tie audit"
    trending = max(range(3), key=lambda i: ratios[i])
    quiet, noisy = sorted([i for i in range(3) if i != trending], key=lambda i: params["variances"][i])
    labels = {trending: "Trending", quiet: "Choppy", noisy: "Mean-reverting"}
    current = max(range(3), key=lambda i: probs[i])
    expected_hmm = dict(state=labels[current], p_stay=round(params["trans"][current][current], 4),
                        p_transition=sorted([dict(to=labels[j], prob=round(params["trans"][current][j], 4)) for j in range(3)
                                             if j != current and params["trans"][current][j] > .05], key=lambda x: -x["prob"]))
    check("hmm_actual_fit_scalar_inference_and_transition_diagonal", expected_hmm, asdict(actual_hmm))
    check("hmm_199_bar_minimum", None, regime_hmm.compute_intraday_hmm(actual_complete[-199:]))
    closes = [b["close"] for b in actual_complete]
    expected, details = expected_omm(closes)
    actual_omm = regime_omm.compute_omm(closes, lookback=26, threshold=.002, smoothing=.2)
    check("omm_scalar_labels", fingerprint(details["labels"]), fingerprint(regime_omm.label_daily_states(closes, lookback=26, threshold=.002, smoothing=.2)))
    check("omm_current_row_age_duration_stability_conviction", expected,
          {k: asdict(actual_omm)[k] for k in expected} if expected else (asdict(actual_omm) if actual_omm else None))
    # Minimum current-state observations on this REAL input, boundary exactly met.
    for minimum in (details["current_observations"], details["current_observations"]+1):
        expected_min, _ = expected_omm(closes, min_obs=minimum)
        actual_min = regime_omm.compute_omm(closes, lookback=26, threshold=.002, smoothing=.2, min_obs=minimum)
        check(f"omm_min_obs_{minimum}", expected_min is not None, actual_min is not None)
    min_obs_prefixes = {}
    for size in range(28, len(closes)+1):
        prefix_expected, prefix_details = expected_omm(closes[:size])
        count = prefix_details.get("current_observations")
        if count in (99, 100) and count not in min_obs_prefixes:
            actual_prefix = regime_omm.compute_omm(closes[:size], lookback=26, threshold=.002, smoothing=.2)
            min_obs_prefixes[count] = dict(input_bars=size, last_epoch=actual_complete[size-1]["time"], current_observations=count)
            check(f"omm_real_prefix_default_min_obs_count_{count}", prefix_expected is not None, actual_prefix is not None)
        if len(min_obs_prefixes) == 2:
            break
    assert len(min_obs_prefixes) == 2
    # Integer differences /1000 equal the .002 threshold exactly in binary
    # floating arithmetic; supplemental bars are not provider observations.
    threshold_cases = []
    for close, label in ((1002., "Choppy"), (998., "Choppy"), (1002.00001, "Bull"), (997.99999, "Bear")):
        threshold_cases.append(check(f"supplemental_threshold_{close}", label,
                                    regime_omm.label_daily_states([1000., close], lookback=1, threshold=.002)[-1]))

    # Minimal router: no app.main, jobs, credentials or DB. All data providers
    # are fixture stubs. HMM is the captured real-fit result; fallback executes
    # actual OMM on the same real bars with only dependency availability changed.
    async def route(library_available):
        with patch.object(router, "fetch_candles", return_value=[]), \
             patch.object(router, "fetch_price", return_value=18.), \
             patch.object(router, "fetch_intraday_candles", return_value=parsed_actual) as provider, \
             patch.object(router, "completed_intraday_bars", side_effect=lambda data: market.completed_intraday_bars(data, now=frozen_now, feed_lag=0)), \
             patch.object(router, "find_spec", return_value=object() if library_available else None), \
             patch.object(router, "compute_intraday_hmm", return_value=actual_hmm):
            result = (await router.get_regime(horizon="intraday", lookback=20, threshold=.02, smoothing=0)).model_dump()
            return result, dict(symbol=provider.call_args.args[0], **provider.call_args.kwargs)
    route_hmm, request_hmm = asyncio.run(route(True))
    route_fallback, request_fallback = asyncio.run(route(False))
    for name, request in (("hmm", request_hmm), ("fallback", request_fallback)):
        check(f"route_{name}_provider_arguments", dict(symbol="SPY", interval="15min", days=55), request)
    check("route_hmm_state_probabilities", expected_hmm, route_hmm["intraday_hmm"])
    check("route_hmm_status", "ok", route_hmm["intraday_hmm_status"])
    check("route_fallback_status", "unavailable", route_fallback["intraday_hmm_status"])
    expected_route = {k: expected[k] for k in ("state", "p_stay", "stability", "regime_age_days", "avg_regime_duration", "transition_row", "state_order")} if expected else None
    if expected_route:
        expected_route.update(duration_stride_bars=26, conviction_pct=None, conviction_label=None)
    check("route_fallback_scalar_values_and_stride", expected_route, route_fallback["intraday_omm"])
    # 26 observations represent a transition stride, not one regular session.
    spans = [actual_complete[i]["time"]-actual_complete[i-26]["time"] for i in range(26, len(actual_complete))]
    age = expected["regime_age_days"] if expected else None
    units = dict(age_unit="consecutive 15-minute input bars", average_duration_unit="26-input-bar transition strides",
                 stride_bars=26, nominal_stride_hours=26*15/60,
                 observed_26_bar_elapsed_hours_min=min(spans)/3600, observed_26_bar_elapsed_hours_max=max(spans)/3600,
                 sampled_regular_session_bars=sum("09:30:00" <= row["time"][11:] < "16:00:00" for row in raw),
                 all_session_bar_count=len(raw),
                 current_age_bars=age, current_age_nominal_minutes=age*15 if age is not None else None,
                 caveat="All-session input includes overnight bars and gaps. 26 bars is not one trading day/session; no calendar/session conversion is certified.")
    sources = ["backend/app/data/market.py", "backend/app/services/regime_hmm.py", "backend/app/services/regime_omm.py",
               "backend/app/routers/regime.py", "backend/app/schemas/__init__.py", "backend/config/scoring_rules.yaml",
               "backend/requirements.txt", "frontend/lib/regimeDuration.ts"]
    dependencies = {}
    for name in ("numpy", "scipy", "scikit-learn", "hmmlearn", "fastapi", "pydantic"):
        dist = importlib.metadata.distribution(name)
        record = next((p for p in dist.files or [] if str(p).endswith(".dist-info/RECORD")), None)
        dependencies[name] = dict(version=dist.version, record_sha256=sha(Path(dist.locate_file(record))) if record else None)
    output = dict(source_commit=SOURCE, runtime=platform.python_version(), harness_sha256=sha(Path(__file__)), fixture_sha256=sha(raw_path),
                  provenance_sha256=sha(HERE / "provenance.json"),
                  fixture_encoding="Sanitized, pretty-printed provider JSON containing every returned bar field/value; SHA covers these normalized fixture bytes, not verbatim HTTP transport bytes.",
                  validation=validation, cutoff=cutoff_record,
                  source_config_hashes={p: sha(ROOT/p) for p in sources}, dependencies=dependencies,
                  hmm=dict(fit_bars=len(capped), fit_returns=len(expected_returns), inference_tail_returns=30,
                           parameters=params, inference_tail_values=expected_returns[-30:], scalar_terminal_posterior=probs, actual_terminal_posterior=actual_probs,
                           posterior_max_absolute_error=error, model_monitor_converged=bool(model.monitor_.converged),
                           iterations=model.monitor_.iter, log_likelihood_history=list(model.monitor_.history),
                           scope="Actual unchanged seed=42/n_iter=100 fit. Scalar inference reproduces fitted-model output; optimizer correctness, calibration and predictive accuracy are not independently established."),
                  omm=dict(parameters=dict(lookback=26, threshold=.002, smoothing=.2, window=500, min_obs=100),
                           current_observations=details["current_observations"], transition_counts=details["transition_counts"],
                           sampled_labels=details["sampled_labels"], min_obs_real_prefix_boundaries=min_obs_prefixes, units=units), checks=checks,
                  summary=dict(checks=len(checks), passed=sum(c["passed"] for c in checks), failed=[c["name"] for c in checks if not c["passed"]]),
                  limits=["Configured-provider response provenance only; no independent certification of exchange-feed accuracy.",
                          "Fixture is September 1 to October 15, 2026; Step 1 requests 55 days. It exceeds the HMM 800-bar cap but does not certify every missing historical day.",
                          "Default offline replay mocks all network/provider calls; production merged yfinance/Tradier live coverage is not exercised.",
                          "Router HMM wiring uses captured real-fit output; only standalone helper performs actual optimizer fit.",
                          "No application boot, persistent settings, account, order, notification or recalibration action."])
    args.output.write_text(json.dumps(output, indent=2, allow_nan=False) + "\n")
    print(json.dumps(output["summary"]))
    faulthandler.cancel_dump_traceback_later()
    if output["summary"]["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
