"""REGIME-SERIES-LENGTH T1 measurement probe (Issue #538 / #534).

Plan: docs/superpowers/plans/2026-10-24-regime-series-length-plan.md, Task 1 (T1).
Measures:
  - Window A: Short / 304 bars (int(1.75 * 252) calendar days, matching Options Scan and Fire path)
  - Window B: Window + lookback (Swing: 520 bars, Position: 800 bars)
  - Window C: Full history (5 years, ~1,260 bars, matching Stock Scan)
Across all 540 symbols in the local DB for swing and position, Bullish and Bearish.

Outputs:
  - docs/superpowers/measurements/2026-10-24-regime-series-length/m1_coverage.json
  - docs/superpowers/measurements/2026-10-24-regime-series-length/m2_gate_flips.json
  - docs/superpowers/measurements/2026-10-24-regime-series-length/examples.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import yaml
from sqlalchemy import select

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.database import AsyncSessionLocal
from app.models.ohlcv_daily import OhlcvDailyModel
from app.services.regime_omm import (
    OmmResult,
    compute_omm,
    label_daily_states,
)

CONFIG_PATH = BACKEND_DIR / "config" / "scoring_rules.yaml"
OUTPUT_DIR = REPO_ROOT / "docs" / "superpowers" / "measurements" / "2026-10-24-regime-series-length"

WINDOW_A_CALENDAR_DAYS = int(1.75 * 252)  # 441 calendar days
WINDOW_A_BARS = 304
WINDOW_B_BARS = {"swing": 520, "position": 800}
WINDOW_C_YEARS = 5
WINDOW_C_BARS = 1260


@dataclass
class GateInput:
    conviction_pct: int
    stability: str


def load_scoring_rules(path: Path = CONFIG_PATH) -> dict:
    """Load scoring_rules.yaml from backend/config."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def classify_gate(
    omm_res: Optional[OmmResult | GateInput],
    gate_cfg: dict,
) -> str:
    """Classify regime gate status ('PASS' | 'CAUTION' | 'REJECT' | 'UNMEASURED').

    Demote-only logic matching backend/app/scoring/stock_scorer.py:_regime_cap.
    When omm_res is None, gate is bypassed / unmeasured.
    """
    if omm_res is None:
        return "UNMEASURED"
    if not gate_cfg.get("enabled", True):
        return "PASS"

    conv = omm_res.conviction_pct
    stab = omm_res.stability
    reject_thresh = gate_cfg.get("headwind_reject_pct", -40)
    caution_thresh = gate_cfg.get("headwind_caution_pct", -15)
    req_stable = gate_cfg.get("require_stable_for_reject", True)

    if conv <= reject_thresh and (not req_stable or stab == "Stable"):
        return "REJECT"
    if conv <= caution_thresh:
        return "CAUTION"
    return "PASS"


def is_silent_bypass(
    status_a: str,
    status_target: str,
    conviction_target: int,
) -> bool:
    """True if cell was unmeasured in Window A but demoted (CAUTION/REJECT) in target window."""
    return status_a == "UNMEASURED" and status_target in ("CAUTION", "REJECT")


def slice_bars(series: list[Any], window: str, horizon: str = "swing") -> list[Any]:
    """Slice a series of bars or closes by bar count.

    - Window A: last 304 bars
    - Window B: last 520 bars (swing) or 800 bars (position)
    - Window C: all bars (or last 1260 bars)
    """
    win = window.upper()
    if win == "A":
        return series[-WINDOW_A_BARS:]
    elif win == "B":
        n_bars = WINDOW_B_BARS.get(horizon.lower(), 520)
        return series[-n_bars:]
    elif win == "C":
        return series
    else:
        raise ValueError(f"Unknown window: {window}")


def slice_bars_date(
    bars: list[dict],
    window: str,
    horizon: str = "swing",
    as_of: Optional[date] = None,
) -> list[dict]:
    """Slice a series of candle dicts by calendar dates matching app scanners.

    - Window A: date >= as_of - int(1.75 * 252) days (matching scan.py / auto_trader.py)
    - Window B: last 520 bars (swing) or 800 bars (position)
    - Window C: date >= as_of - 5 * 365 days (matching stock_scan.py)
    """
    if not bars:
        return []
    if as_of is None:
        dates = [b.get("date") for b in bars if b.get("date")]
        as_of = max(dates) if dates else date.today()

    win = window.upper()
    if win == "A":
        cutoff = as_of - timedelta(days=WINDOW_A_CALENDAR_DAYS)
        return [b for b in bars if b.get("date") is not None and b["date"] >= cutoff]
    elif win == "B":
        n_bars = WINDOW_B_BARS.get(horizon.lower(), 520)
        return bars[-n_bars:]
    elif win == "C":
        cutoff = as_of - timedelta(days=WINDOW_C_YEARS * 365)
        return [b for b in bars if b.get("date") is not None and b["date"] >= cutoff]
    else:
        raise ValueError(f"Unknown window: {window}")


def compute_delta_stats(deltas: list[int | float]) -> dict[str, Any]:
    """Compute summary statistics for conviction deltas."""
    if not deltas:
        return {
            "count": 0,
            "min": 0,
            "max": 0,
            "median": 0.0,
            "mean": 0.0,
            "std_dev": 0.0,
        }
    f_deltas = [float(d) for d in deltas]
    return {
        "count": len(f_deltas),
        "min": int(min(f_deltas)),
        "max": int(max(f_deltas)),
        "median": round(float(statistics.median(f_deltas)), 2),
        "mean": round(float(statistics.mean(f_deltas)), 2),
        "std_dev": round(float(statistics.stdev(f_deltas)) if len(f_deltas) > 1 else 0.0, 4),
    }


async def fetch_universe_bars(
    as_of: date,
) -> tuple[list[str], dict[str, list[dict]]]:
    """Load daily OHLCV bars from local Postgres for all 540 universe symbols.

    Returns:
      (all_symbols, bars_by_symbol)
    """
    cutoff_5y = as_of - timedelta(days=WINDOW_C_YEARS * 365)
    async with AsyncSessionLocal() as session:
        # 1. Distinct universe symbols
        res_syms = await session.execute(
            select(OhlcvDailyModel.symbol).distinct().order_by(OhlcvDailyModel.symbol)
        )
        all_symbols = [str(r[0]) for r in res_syms.all()]

        # 2. Fetch all daily bars within 5-year history window
        stmt = (
            select(
                OhlcvDailyModel.symbol,
                OhlcvDailyModel.date,
                OhlcvDailyModel.close,
                OhlcvDailyModel.adj_factor,
            )
            .where(
                OhlcvDailyModel.date >= cutoff_5y,
                OhlcvDailyModel.date <= as_of,
            )
            .order_by(OhlcvDailyModel.symbol, OhlcvDailyModel.date)
        )
        res_bars = await session.execute(stmt)
        rows = res_bars.all()

    bars_by_symbol: dict[str, list[dict]] = {sym: [] for sym in all_symbols}
    for sym, bar_date, raw_close, adj_factor in rows:
        adj = float(adj_factor) if adj_factor is not None else None
        px = round(float(raw_close) * adj, 6) if adj is not None else float(raw_close)
        bars_by_symbol[sym].append({"date": bar_date, "close": px})

    return all_symbols, bars_by_symbol


def evaluate_omm_with_reason(
    closes: list[float],
    *,
    direction: str,
    lookback: int,
    window: int,
    min_obs: int,
) -> tuple[Optional[OmmResult], str, int]:
    """Evaluate compute_omm and determine unmeasured reason and obs count."""
    if len(closes) < lookback + 2:
        return None, "insufficient_series_length", 0

    labels = label_daily_states(closes, lookback=lookback)
    current = labels[-1]
    window_labels = labels[-window:] if len(labels) > window else labels
    obs = window_labels.count(current)

    omm_res = compute_omm(
        closes,
        direction=direction,
        lookback=lookback,
        window=window,
        min_obs=min_obs,
    )
    if omm_res is None:
        return None, "insufficient_observations_below_min_obs", obs
    return omm_res, "ok", obs


def run_measurements(
    all_symbols: list[str],
    bars_by_symbol: dict[str, list[dict]],
    scoring_cfg: dict,
    as_of: date,
) -> tuple[dict, dict, dict]:
    """Execute M1 coverage, M2 gate flips, and M3 examples measurements."""
    regime_cfg = scoring_cfg["regime"]
    gate_cfg = scoring_cfg["regime_gate"]

    horizons = ["swing", "position"]
    directions = ["Bullish", "Bearish"]

    # Tracking M1 coverage
    # Window keys: 'A' (date-based), 'A_304' (bar count), 'B' (520/800 bars), 'C' (5-year)
    window_keys = ["A", "A_304", "B", "C"]
    m1_data: dict[str, Any] = {
        w: {
            "total_cells": 0,
            "measured": 0,
            "unmeasured": 0,
            "unmeasured_rate_pct": 0.0,
            "by_horizon": {
                h: {
                    "total_cells": 0,
                    "measured": 0,
                    "unmeasured": 0,
                    "unmeasured_rate_pct": 0.0,
                    "reasons": {
                        "insufficient_observations_below_min_obs": 0,
                        "insufficient_series_length": 0,
                    },
                }
                for h in horizons
            },
            "reasons": {
                "insufficient_observations_below_min_obs": 0,
                "insufficient_series_length": 0,
            },
        }
        for w in window_keys
    }

    # Tracking M2 flips and transitions
    m2_transitions = {
        "A_to_B": {},
        "A_to_C": {},
        "B_to_C": {},
        "A304_to_B": {},
        "A304_to_C": {},
    }
    silent_bypasses = {
        "A_to_B": {"total": 0, "caution": 0, "reject": 0, "raw_headwind_15": 0, "raw_headwind_40": 0},
        "A_to_C": {"total": 0, "caution": 0, "reject": 0, "raw_headwind_15": 0, "raw_headwind_40": 0},
        "A304_to_B": {"total": 0, "caution": 0, "reject": 0, "raw_headwind_15": 0, "raw_headwind_40": 0},
        "A304_to_C": {"total": 0, "caution": 0, "reject": 0, "raw_headwind_15": 0, "raw_headwind_40": 0},
    }
    conviction_deltas = {
        "C_minus_A": [],
        "B_minus_A": [],
        "C_minus_B": [],
        "C_minus_A304": [],
    }

    # Representative symbols for M3 examples
    example_symbols = ["WMT", "CPRT", "TSCO", "SRE", "LYB", "SPY"]
    examples_data: dict[str, Any] = {sym: {} for sym in example_symbols}

    for sym in all_symbols:
        raw_bars = bars_by_symbol.get(sym, [])
        all_closes = [b["close"] for b in raw_bars]

        for horizon in horizons:
            h_cfg = regime_cfg[horizon]
            lookback = h_cfg["lookback"]
            window_size = h_cfg["window"]
            min_obs = h_cfg["min_obs"]

            # Pre-slice bars for this horizon
            bars_a_date = slice_bars_date(raw_bars, "A", horizon=horizon, as_of=as_of)
            closes_a_date = [b["close"] for b in bars_a_date]

            closes_a_304 = slice_bars(all_closes, "A", horizon=horizon)
            closes_b = slice_bars(all_closes, "B", horizon=horizon)
            closes_c = slice_bars(all_closes, "C", horizon=horizon)

            series_dict = {
                "A": closes_a_date,
                "A_304": closes_a_304,
                "B": closes_b,
                "C": closes_c,
            }

            for direction in directions:
                # Cell key: (sym, horizon, direction)
                cell_res: dict[str, Optional[OmmResult]] = {}
                cell_status: dict[str, str] = {}
                cell_obs: dict[str, int] = {}
                cell_reason: dict[str, str] = {}

                for w_key in window_keys:
                    closes = series_dict[w_key]
                    omm_res, reason, obs = evaluate_omm_with_reason(
                        closes,
                        direction=direction,
                        lookback=lookback,
                        window=window_size,
                        min_obs=min_obs,
                    )
                    status = classify_gate(omm_res, gate_cfg)

                    cell_res[w_key] = omm_res
                    cell_status[w_key] = status
                    cell_obs[w_key] = obs
                    cell_reason[w_key] = reason

                    # M1 record
                    m1_w = m1_data[w_key]
                    m1_w["total_cells"] += 1
                    m1_w["by_horizon"][horizon]["total_cells"] += 1

                    if omm_res is not None:
                        m1_w["measured"] += 1
                        m1_w["by_horizon"][horizon]["measured"] += 1
                    else:
                        m1_w["unmeasured"] += 1
                        m1_w["by_horizon"][horizon]["unmeasured"] += 1
                        if reason in m1_w["reasons"]:
                            m1_w["reasons"][reason] += 1
                            m1_w["by_horizon"][horizon]["reasons"][reason] += 1

                # M2 record flips & deltas
                pairs = [
                    ("A_to_B", "A", "B"),
                    ("A_to_C", "A", "C"),
                    ("B_to_C", "B", "C"),
                    ("A304_to_B", "A_304", "B"),
                    ("A304_to_C", "A_304", "C"),
                ]
                for p_name, from_k, to_k in pairs:
                    st_from = cell_status[from_k]
                    st_to = cell_status[to_k]
                    trans_key = f"{st_from} -> {st_to}"
                    m2_transitions[p_name][trans_key] = m2_transitions[p_name].get(trans_key, 0) + 1

                    # Silent bypass tracking
                    if p_name in silent_bypasses:
                        res_to = cell_res[to_k]
                        conv_to = res_to.conviction_pct if res_to is not None else 0
                        if st_from == "UNMEASURED":
                            if st_to in ("CAUTION", "REJECT"):
                                silent_bypasses[p_name]["total"] += 1
                                if st_to == "CAUTION":
                                    silent_bypasses[p_name]["caution"] += 1
                                elif st_to == "REJECT":
                                    silent_bypasses[p_name]["reject"] += 1
                            if res_to is not None:
                                if conv_to <= -15:
                                    silent_bypasses[p_name]["raw_headwind_15"] += 1
                                if conv_to <= -40:
                                    silent_bypasses[p_name]["raw_headwind_40"] += 1

                # Conviction deltas when both windows measured
                if cell_res["A"] and cell_res["C"]:
                    conviction_deltas["C_minus_A"].append(cell_res["C"].conviction_pct - cell_res["A"].conviction_pct)
                if cell_res["A"] and cell_res["B"]:
                    conviction_deltas["B_minus_A"].append(cell_res["B"].conviction_pct - cell_res["A"].conviction_pct)
                if cell_res["B"] and cell_res["C"]:
                    conviction_deltas["C_minus_B"].append(cell_res["C"].conviction_pct - cell_res["B"].conviction_pct)
                if cell_res["A_304"] and cell_res["C"]:
                    conviction_deltas["C_minus_A304"].append(cell_res["C"].conviction_pct - cell_res["A_304"].conviction_pct)

                # M3 record for example symbols
                if sym in examples_data:
                    if horizon not in examples_data[sym]:
                        examples_data[sym][horizon] = {}
                    if direction not in examples_data[sym][horizon]:
                        examples_data[sym][horizon][direction] = {}

                    dir_entry = examples_data[sym][horizon][direction]
                    for w_key in ["A", "B", "C"]:
                        omm_res = cell_res[w_key]
                        bar_count = len(series_dict[w_key])
                        if omm_res is not None:
                            dir_entry[w_key] = {
                                "bar_count": bar_count,
                                "measured": True,
                                "state": omm_res.state,
                                "current_state_obs": cell_obs[w_key],
                                "min_obs_required": min_obs,
                                "p_stay": omm_res.p_stay,
                                "stability": omm_res.stability,
                                "regime_age_days": omm_res.regime_age_days,
                                "avg_regime_duration": omm_res.avg_regime_duration,
                                "transition_row": omm_res.transition_row,
                                "conviction_pct": omm_res.conviction_pct,
                                "conviction_label": omm_res.conviction_label,
                                "gate_status": cell_status[w_key],
                                "score_card_impact": (
                                    "No cap (PASS)" if cell_status[w_key] == "PASS"
                                    else f"Demote-only cap to {cell_status[w_key]}"
                                ),
                            }
                        else:
                            dir_entry[w_key] = {
                                "bar_count": bar_count,
                                "measured": False,
                                "reason": cell_reason[w_key],
                                "current_state_obs": cell_obs[w_key],
                                "min_obs_required": min_obs,
                                "gate_status": "UNMEASURED",
                                "score_card_impact": "Gate bypassed (fails open / unmeasured)",
                            }

    # Finalize M1 percentages
    for w_key, w_data in m1_data.items():
        tot = w_data["total_cells"]
        w_data["unmeasured_rate_pct"] = round((w_data["unmeasured"] / tot * 100), 2) if tot > 0 else 0.0
        for h, h_data in w_data["by_horizon"].items():
            h_tot = h_data["total_cells"]
            h_data["unmeasured_rate_pct"] = round((h_data["unmeasured"] / h_tot * 100), 2) if h_tot > 0 else 0.0

    # Finalize M1 output structure
    m1_output = {
        "metadata": {
            "title": "M1 Universe Coverage & Unmeasured Rate Sweep",
            "as_of_date": as_of.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_universe_symbols": len(all_symbols),
            "total_cells": len(all_symbols) * len(horizons) * len(directions),
            "horizons": horizons,
            "directions": directions,
        },
        "windows": m1_data,
    }

    # Finalize M2 output structure
    m2_output = {
        "metadata": {
            "title": "M2 Gate Threshold Impacts & Status Flips",
            "as_of_date": as_of.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "gate_thresholds": {
                "caution_pct": gate_cfg.get("headwind_caution_pct", -15),
                "reject_pct": gate_cfg.get("headwind_reject_pct", -40),
                "require_stable_for_reject": gate_cfg.get("require_stable_for_reject", True),
            },
        },
        "silent_bypasses": silent_bypasses,
        "gate_transitions": m2_transitions,
        "conviction_deltas": {
            pair: compute_delta_stats(deltas)
            for pair, deltas in conviction_deltas.items()
        },
    }

    # Finalize M3 output structure
    examples_output = {
        "metadata": {
            "title": "M3 Concrete In-Depth Symbol Cases",
            "as_of_date": as_of.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "symbols": example_symbols,
        },
        "examples": examples_data,
    }

    return m1_output, m2_output, examples_output


def save_json_outputs(
    m1_out: dict,
    m2_out: dict,
    examples_out: dict,
    out_dir: Path = OUTPUT_DIR,
) -> None:
    """Save formatted JSON files to the measurements directory."""
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "m1_coverage.json").write_text(
        json.dumps(m1_out, indent=2), encoding="utf-8"
    )
    (out_dir / "m2_gate_flips.json").write_text(
        json.dumps(m2_out, indent=2), encoding="utf-8"
    )
    (out_dir / "examples.json").write_text(
        json.dumps(examples_out, indent=2), encoding="utf-8"
    )


async def main_async(as_of: Optional[date] = None) -> int:
    """Run probe measurement and write output files."""
    if as_of is None:
        as_of = date(2026, 10, 24)

    print(f"Loading scoring configuration from {CONFIG_PATH}...")
    scoring_cfg = load_scoring_rules()

    print(f"Fetching daily bars for all universe symbols from Postgres (as_of={as_of})...")
    all_symbols, bars_by_symbol = await fetch_universe_bars(as_of=as_of)
    print(f"Loaded {len(all_symbols)} universe symbols.")

    print("Running M1/M2/M3 measurements...")
    m1_out, m2_out, examples_out = run_measurements(
        all_symbols,
        bars_by_symbol,
        scoring_cfg,
        as_of,
    )

    print(f"Saving outputs to {OUTPUT_DIR}...")
    save_json_outputs(m1_out, m2_out, examples_out)

    # Print summary highlights
    print("\n--- M1 UNMEASURED RATE SUMMARY ---")
    for w_name, w_info in m1_out["windows"].items():
        print(f"  Window {w_name:6s}: {w_info['unmeasured']}/{w_info['total_cells']} unmeasured ({w_info['unmeasured_rate_pct']}%)")

    print("\n--- M2 SILENT BYPASS SUMMARY ---")
    sb_c = m2_out["silent_bypasses"]["A_to_C"]
    print(f"  Window A -> Window C: {sb_c['total']} cells unmeasured in A were demoted in C ({sb_c['caution']} CAUTION, {sb_c['reject']} REJECT)")
    sb_b = m2_out["silent_bypasses"]["A_to_B"]
    print(f"  Window A -> Window B: {sb_b['total']} cells unmeasured in A were demoted in B ({sb_b['caution']} CAUTION, {sb_b['reject']} REJECT)")

    print("\nProbe complete.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="REGIME-SERIES-LENGTH Measurement Probe")
    parser.add_argument(
        "--as-of",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        default=None,
        help="Anchor date (YYYY-MM-DD), default 2026-10-24",
    )
    args = parser.parse_args()
    asyncio.run(main_async(as_of=args.as_of))


if __name__ == "__main__":
    main()
