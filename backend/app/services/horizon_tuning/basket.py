"""The tuner's universes, sector sample and fire-rate scaling — STOCKS-HORIZON-T1 H8.

* **Union** = S&P 500 (``sp500.csv``) ∪ NDX 100 (``universe_presets.NDX100``).
* **Trade universe** = the union minus ``universe_exclusions.yaml`` BOTH scopes
  (the evidence scope means "skipped by tuning"). Every simulated trade comes
  from it, so no trade is taken on evidence-scope bars.
* **Fire-rate universe** = the union minus the SCAN scope only (live scans
  still scan evidence-scope names); used only to count fires.
* **Sample** = top ``per_sector`` names per sector stratum of the trade
  universe by mean daily dollar volume (close x volume over stored bars before
  ``heldout_start``; the CSV ``liquidity`` column is not used), via
  ``strategy_basket.build_basket``. Strata = ``sector_for_symbol`` (H0a); a
  name still without a sector is listed and left out.
* **Fire rate** (sample-scaled, per day):
  ``sum_s (fires_s / scan_days) * (N_universe_s / N_sample_s)``.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from app.data import universe_exclusions
from app.data.sector_map import sector_for_symbol
from app.data.universe_presets import expand_universe
from app.services.strategy_basket import build_basket

SAMPLE_LABEL = "liquidity-selected (dollar volume), equal count per sector"


def universe_union() -> list[str]:
    """S&P 500 ∪ NDX 100, de-duplicated, in preset order."""
    return expand_universe(["SP500", "NDX100"])


def trade_universe(symbols: list[str]) -> list[str]:
    """``symbols`` minus both exclusion scopes."""
    return universe_exclusions.filter_symbols(symbols, purpose="evidence")[0]


def fire_rate_universe(symbols: list[str]) -> list[str]:
    """``symbols`` minus the scan-scope exclusions only."""
    return universe_exclusions.filter_symbols(symbols, purpose="scan")[0]


def _bar_date(bar: dict) -> date:
    t = bar["time"]
    return date.fromisoformat(t[:10]) if isinstance(t, str) else t


def dollar_volume(bars: list[dict], heldout_start: date) -> float | None:
    """Mean of close x volume over the bars dated before ``heldout_start``;
    ``None`` when there are none."""
    vals = [float(b["close"]) * float(b["volume"]) for b in bars if _bar_date(b) < heldout_start]
    return sum(vals) / len(vals) if vals else None


def sector_of(symbol: str) -> str | None:
    return sector_for_symbol(symbol)[0]


def sector_counts(symbols: list[str]) -> dict[str, int]:
    """Names per sector stratum; names without a sector are not counted."""
    out: dict[str, int] = defaultdict(int)
    for s in symbols:
        sec = sector_of(s)
        if sec:
            out[sec] += 1
    return dict(out)


@dataclass
class BasketSample:
    symbols: list[str]
    by_sector: dict[str, list[str]] = field(default_factory=dict)
    unsectored: list[str] = field(default_factory=list)
    label: str = SAMPLE_LABEL


def sample_basket(symbols: list[str], liquidity: dict[str, float | None], *, per_sector: int) -> BasketSample:
    """Top ``per_sector`` names per sector by ``liquidity`` (dollar volume).

    ``symbols`` is the trade universe. Names without a sector are listed in
    ``unsectored``; names without a liquidity figure (no bars) are left out.
    """
    rows: list[dict] = []
    unsectored: list[str] = []
    for s in symbols:
        sec = sector_of(s)
        if not sec:
            unsectored.append(s)
            continue
        liq = liquidity.get(s)
        if liq is None:
            continue
        rows.append({"symbol": s, "sector": sec, "liquidity": float(liq)})
    chosen = build_basket(rows, per_sector=per_sector)
    sector_by_symbol = {r["symbol"]: r["sector"] for r in rows}
    by_sector: dict[str, list[str]] = defaultdict(list)
    for s in chosen:
        by_sector[sector_by_symbol[s]].append(s)
    return BasketSample(symbols=chosen, by_sector=dict(by_sector), unsectored=unsectored)


def scaled_fire_rate(
    fires_by_sector: dict[str, int],
    scan_days: int,
    n_universe_by_sector: dict[str, int],
    n_sample_by_sector: dict[str, int],
) -> float:
    """Candidates per scan day across the fire-rate universe, scaled from the
    sample per sector: ``sum_s (fires_s / scan_days) * (N_universe_s / N_sample_s)``.
    A sector with no sample names contributes nothing (it has no fires)."""
    if scan_days <= 0:
        raise ValueError(f"scan_days must be > 0, got {scan_days}")
    rate = 0.0
    for sec, fires in fires_by_sector.items():
        n_sample = n_sample_by_sector.get(sec, 0)
        if n_sample <= 0:
            if fires:
                raise ValueError(f"{fires} fires in sector {sec!r} with no sample names")
            continue
        rate += (fires / scan_days) * (n_universe_by_sector.get(sec, 0) / n_sample)
    return rate
