#!/usr/bin/env python3
"""Score calibration (TRADING-REVIEW-PHASE-C T11, review H2).

Replays ``score_stock`` bar by bar exactly as ``signal_confidence.compute_confidence``
does (warm-up 60, the horizon's ``history_years`` window, one score per bar on the bars
up to and including it). Each bar falls in its status bucket (PASS / CAUTION / REJECT),
and its forward outcome is measured in R with ``evaluate_fire``'s barriers (the
horizon's ``atr_mult_target`` / ``atr_mult_stop`` and ``n_days``):
win = +target/stop R, loss = -1 R, flat = the close-to-close move at the window end
divided by the stop distance.

Distinct setups only: after a counted bar i in a bucket, the next counted bar in that
bucket is at least i + n_days, so forward windows never overlap. Per bucket: n, mean R
and a bootstrap 95% CI (2,000 resamples, seed 7), plus the all-bars base rate (every
bar, same non-overlap rule).

It also reports, per horizon and direction, the confidence replay's sample size both
ways, overlapping (today's ``compute_confidence`` rule) and non-overlapping, against
``min_samples`` (the C4 decision T8's withdrawal deferred).

Read-only. Run from the repo root with the backend venv (Python 3.11):
    python scripts/evidence/score_calibration.py --symbols AAPL MSFT --horizons Swing
"""
from __future__ import annotations

import asyncio
import random
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO / "backend", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app.scoring.signal_confidence import evaluate_fire, load_backtest_cfg  # noqa: E402
from app.scoring.stock_scorer import _atr, score_stock  # noqa: E402
from evidence._bars import (  # noqa: E402
    common_parser, emit, load_bars, loaded_range, report_header, stored_symbols,
)

WARMUP = 60            # compute_confidence's warm-up
BUCKETS = ("PASS", "CAUTION", "REJECT")
ALL = "ALL"
BOOTSTRAP_RESAMPLES = 2_000
BOOTSTRAP_SEED = 7
COST_MODEL = "gross: barrier R from evaluate_fire; no fees or slippage"


@dataclass(frozen=True)
class Fire:
    """One replayed bar: its index in the replay window, status and forward outcome."""
    i: int
    status: str
    outcome: str          # win | loss | flat, as evaluate_fire returns it
    r: float | None       # forward R; None when the stop distance is zero (ATR 0)


@dataclass(frozen=True)
class BucketStat:
    horizon: str
    direction: str
    bucket: str           # PASS | CAUTION | REJECT | ALL
    n: int                # distinct, non-overlapping setups pooled across symbols
    wins: int
    losses: int
    flats: int
    mean_r: float | None
    ci_low: float | None
    ci_high: float | None


@dataclass(frozen=True)
class SampleCount:
    symbol: str
    horizon: str
    direction: str
    overlapping: int      # compute_confidence's sample_size: decisive PASS fires
    non_overlapping: int  # decisive PASS fires with non-overlapping forward windows
    min_samples: int

    @property
    def meets_overlapping(self) -> bool:
        return self.overlapping >= self.min_samples

    @property
    def meets_non_overlapping(self) -> bool:
        return self.non_overlapping >= self.min_samples


# ── Pure core ────────────────────────────────────────────────────────────────

def _barriers(horizon: str) -> tuple[int, int, float, float, int, float | None]:
    bt = load_backtest_cfg(horizon)
    return (int(bt["n_days"]), int(bt["atr_period"]), float(bt["atr_mult_target"]),
            float(bt["atr_mult_stop"]), int(bt["min_samples"]), bt.get("history_years"))


def forward_r(
    outcome: str, window: list[dict], forward: list[dict], *, direction: str, atr: float,
    atr_mult_target: float, atr_mult_stop: float,
) -> float | None:
    """The forward outcome in R (1 R = the stop distance, ``atr_mult_stop * atr``)."""
    stop_dist = atr_mult_stop * atr
    if stop_dist <= 0 or not forward:
        return None
    if outcome == "win":
        return atr_mult_target / atr_mult_stop
    if outcome == "loss":
        return -1.0
    move = forward[-1]["close"] - window[-1]["close"]
    return (move if direction == "Bullish" else -move) / stop_dist


def replay(
    bars: list[dict], horizon: str, direction: str,
    scorer: Callable = score_stock, *, scoring_mode: str = "options",
) -> list[Fire]:
    """Score every bar as compute_confidence does and attach its forward outcome."""
    n_days, atr_period, mult_target, mult_stop, _, history_years = _barriers(horizon)
    if history_years:
        max_bars = int(float(history_years) * 252) + n_days
        if len(bars) > max_bars:
            bars = bars[-max_bars:]
    fires: list[Fire] = []
    for i in range(WARMUP, len(bars) - n_days):
        window = bars[: i + 1]
        card = scorer(symbol="_bt", direction=direction, horizon=horizon, bars=window,
                      scoring_mode=scoring_mode)
        atr = _atr(window, atr_period)
        forward = bars[i + 1: i + 1 + n_days]
        outcome = evaluate_fire(window, forward, direction=direction, atr=atr,
                                atr_mult_target=mult_target, atr_mult_stop=mult_stop)
        r = forward_r(outcome, window, forward, direction=direction, atr=atr,
                      atr_mult_target=mult_target, atr_mult_stop=mult_stop)
        fires.append(Fire(i, card.status, outcome, r))
    return fires


def distinct(fires: list[Fire], gap: int) -> list[Fire]:
    """Greedy non-overlap: each kept fire is at least ``gap`` bars after the last kept."""
    kept: list[Fire] = []
    for f in fires:
        if not kept or f.i >= kept[-1].i + gap:
            kept.append(f)
    return kept


def bootstrap_ci(
    values: list[float], resamples: int = BOOTSTRAP_RESAMPLES, seed: int = BOOTSTRAP_SEED,
) -> tuple[float | None, float | None]:
    """Percentile bootstrap 95% CI of the mean, with a fixed seed."""
    if not values:
        return None, None
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(rng.choices(values, k=n)) / n for _ in range(resamples))
    return means[round(0.025 * (resamples - 1))], means[round(0.975 * (resamples - 1))]


def _stat(horizon: str, direction: str, bucket: str, picked: list[Fire]) -> BucketStat:
    rs = [f.r for f in picked]
    lo, hi = bootstrap_ci(rs)
    return BucketStat(
        horizon=horizon, direction=direction, bucket=bucket, n=len(picked),
        wins=sum(f.outcome == "win" for f in picked),
        losses=sum(f.outcome == "loss" for f in picked),
        flats=sum(f.outcome == "flat" for f in picked),
        mean_r=(sum(rs) / len(rs)) if rs else None, ci_low=lo, ci_high=hi,
    )


def bucket_stats(
    replays_by_symbol: dict[str, list[Fire]], horizon: str, direction: str,
) -> list[BucketStat]:
    """Per status bucket and for all bars: distinct setups pooled across symbols.
    Bars without a defined R (ATR 0) are not counted."""
    n_days = _barriers(horizon)[0]
    statuses = list(BUCKETS) + sorted(
        {f.status for fires in replays_by_symbol.values() for f in fires} - set(BUCKETS)
    )
    out: list[BucketStat] = []
    for bucket in statuses + [ALL]:
        picked: list[Fire] = []
        for symbol in sorted(replays_by_symbol):
            usable = [f for f in replays_by_symbol[symbol]
                      if f.r is not None and (bucket == ALL or f.status == bucket)]
            picked.extend(distinct(usable, n_days))
        out.append(_stat(horizon, direction, bucket, picked))
    return out


def confidence_counts(
    replays_by_symbol: dict[str, list[Fire]], horizon: str, direction: str = "",
) -> list[SampleCount]:
    """Per symbol, the confidence replay's decisive sample size both ways.

    Overlapping is today's rule: every PASS bar is a fire and ``aggregate`` counts
    wins + losses. Non-overlapping keeps PASS fires at least ``n_days`` apart (a flat
    fire still occupies its window) and counts the decisive ones."""
    n_days, _, _, _, min_samples, _ = _barriers(horizon)
    out: list[SampleCount] = []
    for symbol in sorted(replays_by_symbol):
        passes = [f for f in replays_by_symbol[symbol] if f.status == "PASS"]
        decisive = lambda fs: sum(f.outcome in ("win", "loss") for f in fs)  # noqa: E731
        out.append(SampleCount(
            symbol=symbol, horizon=horizon, direction=direction,
            overlapping=decisive(passes),
            non_overlapping=decisive(distinct(passes, n_days)),
            min_samples=min_samples,
        ))
    return out


def calibrate(
    bars_by_symbol: dict[str, list[dict]], horizon: str, direction: str,
    scorer: Callable = score_stock, *, scoring_mode: str = "options",
) -> list[BucketStat]:
    """Replay every symbol and return the per-bucket distinct-setup statistics."""
    replays = {s: replay(b, horizon, direction, scorer, scoring_mode=scoring_mode)
               for s, b in bars_by_symbol.items()}
    return bucket_stats(replays, horizon, direction)


# ── Report ───────────────────────────────────────────────────────────────────

def _fmt(x: float | None) -> str:
    return "-" if x is None else f"{x:+.3f}"


def section(horizon: str, direction: str, stats: list[BucketStat],
            counts: list[SampleCount]) -> str:
    n_days, _, mult_target, mult_stop, min_samples, _ = _barriers(horizon)
    lines = [
        f"## {horizon} / {direction}", "",
        f"Barriers: target {mult_target:g} ATR, stop {mult_stop:g} ATR, window {n_days} bars; "
        f"win = {mult_target / mult_stop:+.3f} R, loss = -1 R.", "",
        "| Bucket | n (distinct) | Wins | Losses | Flats | Mean R | 95% CI |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for s in stats:
        name = "ALL (base rate)" if s.bucket == ALL else s.bucket
        ci = "-" if s.ci_low is None else f"[{_fmt(s.ci_low)}, {_fmt(s.ci_high)}]"
        lines.append(f"| {name} | {s.n} | {s.wins} | {s.losses} | {s.flats} "
                     f"| {_fmt(s.mean_r)} | {ci} |")
    ov = [c.overlapping for c in counts]
    nov = [c.non_overlapping for c in counts]
    lines += [
        "", f"### Confidence replay sample size vs min_samples ({min_samples})", "",
        f"- Symbols: {len(counts)}",
        f"- Meeting min_samples, overlapping (today): "
        f"{sum(c.meets_overlapping for c in counts)}",
        f"- Meeting min_samples, non-overlapping: "
        f"{sum(c.meets_non_overlapping for c in counts)}",
        f"- Median decisive fires: overlapping {statistics.median(ov) if ov else 0}, "
        f"non-overlapping {statistics.median(nov) if nov else 0}",
        "", "| Symbol | Overlapping | Non-overlapping | min_samples |",
        "|---|---:|---:|---:|",
    ]
    for c in counts:
        lines.append(f"| {c.symbol} | {c.overlapping} | {c.non_overlapping} | {c.min_samples} |")
    lines.append("")
    return "\n".join(lines)


async def _main(args) -> str:
    symbols = args.symbols or await stored_symbols()
    bars = await load_bars(symbols, args.start, args.end)
    header = report_header(
        "Score calibration", symbols=symbols, start=args.start, end=args.end,
        cost_model=COST_MODEL, loaded=loaded_range(bars),
        extra={
            "Scoring mode": args.mode,
            "Replay": f"as compute_confidence: warm-up {WARMUP}, horizon history_years window",
            "Bootstrap": f"{BOOTSTRAP_RESAMPLES} resamples, seed {BOOTSTRAP_SEED}",
        },
    )
    parts = [header]
    for horizon in args.horizons:
        for direction in args.directions:
            replays = {s: replay(b, horizon, direction, scoring_mode=args.mode)
                       for s, b in bars.items()}
            counts = confidence_counts(replays, horizon, direction)
            parts.append(section(horizon, direction,
                                 bucket_stats(replays, horizon, direction), counts))
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> None:
    parser = common_parser(__doc__.splitlines()[0])
    parser.add_argument("--horizons", nargs="+", default=["Swing"],
                        choices=["Intraday", "Swing", "Position"],
                        help="horizons to replay (default Swing)")
    parser.add_argument("--directions", nargs="+", default=["Bullish", "Bearish"],
                        choices=["Bullish", "Bearish"],
                        help="directions to replay (default both)")
    parser.add_argument("--mode", default="options", choices=["options", "stock"],
                        help="score_stock scoring_mode (default options, as compute_confidence)")
    args = parser.parse_args(argv)
    emit(asyncio.run(_main(args)), args.out)


if __name__ == "__main__":
    main()
