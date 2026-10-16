"""Offline numerical audit. Run from repo root with backend/.venv/bin/python.

Independent expectations use scalar arithmetic, Counter and dynamic programming;
production functions are called only on the actual side. No provider is called.
"""
from __future__ import annotations

import asyncio
import faulthandler
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import sys
from unittest.mock import patch

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"

ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT / "backend"))
from app.services import regime_omm as omm
from app.services.regime_hmm import compute_intraday_hmm
from app.services.regime_hmm_daily import compute_directional_hmm
from app.routers import regime as router
from app.data.market import completed_intraday_bars
from app.scoring.stock_scorer import _regime_cap

OUT = Path(__file__).parent
STATES = ["Bull", "Bear", "Choppy"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_omm(closes, lookback=20, window=500, min_obs=100,
                 threshold=.02, smoothing=0, direction="Bullish"):
    # A separate scalar implementation; no production helper supplies labels,
    # probabilities, current state, age, duration or conviction expectations.
    if len(closes) < lookback + 2:
        return None
    labels, smoothed = [], 0.0
    for i, value in enumerate(closes):
        if i < lookback:
            labels.append("Choppy")
            continue
        delta = value / closes[i - lookback] - 1
        smoothed = smoothing * smoothed + (1 - smoothing) * delta
        signal = smoothed if smoothing else delta
        labels.append("Bull" if signal > threshold else "Bear" if signal < -threshold else "Choppy")
    current = labels[-1]
    recent = labels[-window:]
    if recent.count(current) < min_obs:
        return None
    sampled = recent[::lookback]
    pairs = Counter(zip(sampled[:-1], sampled[1:]))
    denominator = sum(pairs[current, s] for s in STATES)
    row = [pairs[current, s] / denominator if denominator else 1 / 3 for s in STATES]
    stay = row[STATES.index(current)]
    age = 0
    for state in labels[::-1]:
        if state != current:
            break
        age += 1
    return dict(state=current, p_stay=round(stay, 4),
                transition_row=[round(v, 4) for v in row],
                regime_age_days=age,
                avg_regime_duration=round(min(1 / (1 - stay) if stay < 1 else math.inf, 9999), 1),
                stability="Stable" if stay >= .75 else "Fragile",
                conviction_pct=round(100 * (row[0] - row[1]) * (1 if direction == "Bullish" else -1)))


def omm_case(closes, **params):
    expected = expected_omm(closes, **params)
    result = omm.compute_omm(closes, **params)
    actual = {k: getattr(result, k) for k in expected} if expected is not None and result else (asdict(result) if result else None)
    return dict(params=params, expected=expected, actual=actual, passed=expected == actual)


def closes_from_returns(values):
    closes = [100.0]
    for value in values:
        closes.append(closes[-1] * (1 + value))
    return closes


def independent_hmm(returns, start, trans, means, variances):
    # Scaled forward recursion and log-domain Viterbi. Scaled recursion avoids
    # underflow without importing any hmmlearn or production inference helper.
    logp = lambda p: math.log(p) if p > 0 else -math.inf
    posterior, viterbi = start[:], [logp(p) for p in start]
    for t, value in enumerate(returns):
        densities = [math.exp(-.5 * (value - m)**2 / v) / math.sqrt(2 * math.pi * v)
                     for m, v in zip(means, variances)]
        prior = posterior if t == 0 else [sum(posterior[i] * trans[i][j] for i in range(3)) for j in range(3)]
        unscaled = [p * density for p, density in zip(prior, densities)]
        posterior = [v / sum(unscaled) for v in unscaled]
        viterbi = [(viterbi[j] if t == 0 else max(viterbi[i] + logp(trans[i][j]) for i in range(3))) + math.log(densities[j]) for j in range(3)]
    return posterior, max(range(3), key=lambda i: viterbi[i])


def main():
    faulthandler.dump_traceback_later(15, repeat=True)
    fixture_path = ROOT / "backend/tests/fixtures/SPY_candles.json"
    fixture = json.loads(fixture_path.read_text())
    synthetic = closes_from_returns(([.012] * 45 + [-.013] * 35 + [.0001] * 25) * 5 + [.012] * 37)
    fixture_blob = dict(synthetic_closes=synthetic,
                        boundary_closes=[100, 102, 98, 100],
                        hmm_closes=closes_from_returns([.003, -.002, .0001, -.001, .002] * 44))
    fixture_file = OUT / "deterministic-fixtures.json"
    fixture_file.write_text(json.dumps(fixture_blob, indent=2) + "\n")
    result = dict(runtime=platform.python_version(), source_sha="880c8441841cc22d5090cdc5f984e4cf7e3d9a8d",
                  fixture=dict(path=str(fixture_path.relative_to(ROOT)), sha256=sha(fixture_path),
                               first=fixture[0]["time"], last=fixture[-1]["time"], bars=len(fixture),
                               provenance="Committed SPY OHLCV fixture; provider/retrieval timestamp not recorded in the fixture. No new real-provider fetch."),
                  deterministic_fixture_sha256=sha(fixture_file))
    result["omm"] = {"committed_spy": omm_case([x["close"] for x in fixture], min_obs=10),
                      "synthetic_bullish": omm_case(synthetic, min_obs=10, lookback=5, window=400),
                      "synthetic_bearish": omm_case(synthetic, min_obs=10, lookback=5, window=400, direction="Bearish"),
                      "synthetic_smoothing": omm_case(synthetic, min_obs=10, lookback=5, window=400, smoothing=.2),
                      "short": omm_case([100]*21),
                      "current_underobserved": omm_case([100]*100 + [200, 201], min_obs=100),
                      "absorbing_duration_cap": omm_case([100]*300)}
    result["threshold_boundaries"] = {str(x): dict(expected="Choppy", actual=omm.label_daily_states([100, x], lookback=1)[-1]) for x in (98, 102)}
    result["zero_observation_row"] = dict(expected=[1/3]*3, actual=omm.build_transition_matrix_stride(["Bull"]*60, lookback=20)[1].tolist())
    result["transition_normalization"] = dict(expected=[1.0]*3, actual=omm.build_transition_matrix_stride(["Bull", "Bear", "Choppy"]*200, lookback=5).sum(axis=1).tolist())
    # HMM inference: real hmmlearn inference against a supplied, frozen model.
    # Fitting is replaced with a no-op, and is explicitly a separate coverage item.
    from hmmlearn.hmm import GaussianHMM
    import hmmlearn, numpy as np
    start, trans = [.2, .5, .3], [[.8, .15, .05], [.2, .65, .15], [.1, .2, .7]]
    means, variances = [.004, -.003, .0], [.000004, .000009, .000001]
    bars = [{"close": c, "time": i*900} for i, c in enumerate(fixture_blob["hmm_closes"])]
    returns = [bars[i]["close"]/bars[i-1]["close"]-1 for i in range(1, len(bars))]
    forward, viterbi_idx = independent_hmm(returns[-30:], start, trans, means, variances)
    filtered_idx = max(range(3), key=lambda i: forward[i])
    models = []
    def supplied_model(**kwargs):
        model = GaussianHMM(**kwargs, init_params="")
        model.n_features = 1
        model.startprob_, model.transmat_, model.means_ = np.array(start), np.array(trans), np.array(means).reshape(-1, 1)
        model.covars_ = np.array(variances).reshape(-1, 1, 1) if kwargs["covariance_type"] == "full" else np.array(variances).reshape(-1, 1)
        model.fit = lambda X: model
        models.append(model)
        return model
    with patch("hmmlearn.hmm.GaussianHMM", supplied_model):
        intraday = compute_intraday_hmm(bars)
        directional = compute_directional_hmm(bars)
    session_labels = ["Trending", "Mean-reverting", "Choppy"]
    daily_labels = ["Bull", "Bear", "Sideways"]
    expected_intraday = dict(state=session_labels[filtered_idx], p_stay=trans[filtered_idx][filtered_idx],
                            p_transition=sorted([dict(to=session_labels[j], prob=trans[filtered_idx][j]) for j in range(3) if j != filtered_idx and trans[filtered_idx][j] > .05], key=lambda x: -x["prob"]))
    expected_daily = dict(state=daily_labels[viterbi_idx], p_stay=trans[viterbi_idx][viterbi_idx], transition_row=trans[viterbi_idx])
    actual_posterior = models[0].predict_proba(np.array(returns[-30:]).reshape(-1, 1))[-1].tolist()
    result["hmm_supplied_model"] = dict(model=dict(start=start, trans=trans, means=means, variances=variances), hmmlearn=hmmlearn.__version__,
        tail_returns=returns[-30:], expected_forward_probabilities=forward, actual_forward_probabilities=actual_posterior,
        forward_max_absolute_error=max(abs(a-b) for a,b in zip(forward, actual_posterior)),
        expected_intraday=expected_intraday, actual_intraday=asdict(intraday),
        expected_directional=expected_daily, actual_directional=asdict(directional),
        passed=expected_intraday == asdict(intraday) and expected_daily == asdict(directional),
        scope="Fixed emission/transition inference only; fit replaced. p_stay is a transition probability, not posterior confidence.")
    # The committed real-price fixture is fitted separately, with no claim that
    # the fitted parameters were independently optimized or calibrated.
    fitted_models = []
    def capture_fit_model(**kwargs):
        model = GaussianHMM(**kwargs)
        fitted_models.append(model)
        return model
    with patch("hmmlearn.hmm.GaussianHMM", capture_fit_model):
        real_intraday = compute_intraday_hmm(fixture)
        real_daily = compute_directional_hmm(fixture)
    fitted_audit = []
    fixture_returns = [fixture[i]["close"]/fixture[i-1]["close"]-1 for i in range(1,len(fixture))]
    for kind, model, actual in zip(("intraday_algorithm_on_daily_fixture", "directional_daily"), fitted_models, (real_intraday, real_daily)):
        means_fit = model.means_.reshape(-1).tolist()
        vars_fit = [float(model.covars_[j].reshape(-1)[0]) for j in range(3)]
        start_fit, trans_fit = model.startprob_.tolist(), model.transmat_.tolist()
        posterior_fit, viterbi_fit = independent_hmm(fixture_returns[-30:],start_fit,trans_fit,means_fit,vars_fit)
        if kind.startswith("intraday"):
            idx = max(range(3), key=lambda j: posterior_fit[j])
            trending = max(range(3), key=lambda j: abs(means_fit[j])/math.sqrt(vars_fit[j]))
            rest = sorted([j for j in range(3) if j != trending],key=lambda j:vars_fit[j])
            labels = {trending:"Trending",rest[0]:"Choppy",rest[1]:"Mean-reverting"}
            expected_fit = dict(state=labels[idx],p_stay=round(trans_fit[idx][idx],4),p_transition=sorted([dict(to=labels[j],prob=round(trans_fit[idx][j],4)) for j in range(3) if j != idx and trans_fit[idx][j] > .05],key=lambda x:-x["prob"]))
        else:
            idx = viterbi_fit
            order_fit = sorted(range(3),key=lambda j:means_fit[j])
            labels = dict(zip(order_fit,["Bear","Sideways","Bull"]))
            expected_fit = dict(state=labels[idx],p_stay=round(trans_fit[idx][idx],4),transition_row=[round(v,4) for v in trans_fit[idx]])
        fitted_audit.append(dict(kind=kind,model=dict(start=start_fit,trans=trans_fit,means=means_fit,variances=vars_fit),expected_posterior=posterior_fit,expected=expected_fit,actual=asdict(actual),passed=expected_fit==asdict(actual)))
    result["hmm_real_fixture_fit"] = dict(cases=fitted_audit,scope="Actual seed=42 hmmlearn fits on committed daily OHLCV, captured fitted parameters; independent scalar emission/forward/Viterbi evaluation reproduces returned state and probabilities. Optimizer correctness and calibration are not independently established. Intraday algorithm receives DAILY bars only as an algorithm smoke check; no real intraday provider fixture is available.")
    result["hmm_insufficient"] = dict(expected=None, actual=compute_intraday_hmm(bars[:199]))
    result["vix_ties_boundaries"] = [dict(history=h, current=v, expected=e, actual=router._vix_percentile(h,v)) for h,v,e in [([],20,50),([20,20],20,0),([10,20,20,30],20,25),([10,20],9,0),([10,20],21,100)]]
    def get_candles(symbol, bars):
        return [{"close":c} for c in ([1]*7 + [100]*252 + [50] if symbol == "VIX" else [100]*600)]
    async def route_case(intra, library_present):
        with patch.object(router,"fetch_candles",get_candles), patch.object(router,"fetch_price",return_value=50), patch.object(router,"fetch_intraday_candles",return_value=intra), patch.object(router,"find_spec",return_value=object() if library_present else None), patch.object(router,"_compute_directional_hmm",return_value=None):
            return (await router.get_regime(horizon="intraday",lookback=20,threshold=.02,smoothing=0)).model_dump()
    response = asyncio.run(route_case([], True))
    result["vix_252_window"] = dict(input_prior_observations=259, expected_window_bars=252, actual_window_bars=259,
        expected=0.0, actual=response["vix_pct_252d"], passed=response["vix_pct_252d"] == 0,
        explanation="7 excluded-old closes=1; latest 252 prior closes=100; current=50. 252-day rank=0%; actual uses all 259 prior closes=7/259=2.7%.")
    done_bars=[{"time":i*900,"close":100} for i in range(220)]
    insufficient=asyncio.run(route_case(done_bars[:199],True))
    fallback=asyncio.run(route_case(done_bars,False))
    result["fallback"] = dict(no_bars_status=response["intraday_hmm_status"], insufficient_status=insufficient["intraday_hmm_status"],
        insufficient_omm=insufficient["intraday_omm"], missing_library_status=fallback["intraday_hmm_status"], missing_library_omm=fallback["intraday_omm"])
    times=[{"time":99},{"time":100},{"time":101},{"time":True},{"time":"100"},{}]
    result["completed_15min"] = dict(now=1000, bar_seconds=900, feed_lag=0, expected=[{"time":99},{"time":100}], actual=completed_intraday_bars(times,now=1000,feed_lag=0))
    result["backend_gate_boundaries"] = [dict(conviction=c,stability=s,expected=e,actual=_regime_cap(c,s,dict(enabled=True,headwind_caution_pct=-15,headwind_reject_pct=-40,require_stable_for_reject=True))) for c,s,e in [(-40,"Stable","REJECT"),(-40,"Fragile","CAUTION"),(-15,"Stable","CAUTION"),(-14,"Stable","PASS")]]
    result["source_hashes"] = {str(p.relative_to(ROOT)):sha(p) for p in [ROOT/"backend/app/services/regime_omm.py",ROOT/"backend/app/services/regime_hmm.py",ROOT/"backend/app/services/regime_hmm_daily.py",ROOT/"backend/app/routers/regime.py",ROOT/"backend/app/data/market.py",ROOT/"backend/config/scoring_rules.yaml",ROOT/"frontend/lib/regimeDuration.ts",ROOT/"frontend/components/organisms/RunScanButton/index.tsx",ROOT/"frontend/components/organisms/StepNavBar/index.tsx"]}
    (OUT/"output.json").write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"output":"regime/output.json","omm_passed":all(x["passed"] for x in result["omm"].values()),"hmm_supplied_passed":result["hmm_supplied_model"]["passed"],"vix_252_passed":result["vix_252_window"]["passed"]}))
    faulthandler.cancel_dump_traceback_later()


if __name__ == "__main__":
    main()
