#!/usr/bin/env python3
"""Bar-basis check (TRADING-REVIEW-PHASE-C T11, review H1).

Per symbol, on the bars the app actually reads (``_read_bars``, fully adjusted OHLC):
the share of bars whose close or open lies outside its own [low, high], close-to-close
jumps above 40%, and T3's ``stale_reasons`` over the full stored row set (read with a
SELECT), plus the documented dividend-only residual T3 cannot detect.

Read-only. Run from the repo root with the backend venv (Python 3.11):
    python scripts/evidence/bar_basis_check.py --symbols AAPL GE --out basis.md
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO / "backend", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from evidence._bars import (  # noqa: E402
    common_parser, emit, load_basis_rows, load_bars, load_history_states, loaded_range, report_header,
    stored_symbols,
)

JUMP_THRESHOLD = 0.40

# T3's documented residual (historical_store.py, "Stale adjustment factors"): a
# dividend-only staleness on a yfinance-only or Alpaca-sourced series between nightly
# refreshes leaves no detectable signature; its effect is about one dividend (< 1%).
RESIDUAL_NOTE = (
    "Residual (not detectable): a dividend-only staleness on a yfinance-only or "
    "Alpaca-sourced series between nightly refreshes leaves no signature. Its effect is "
    "about one dividend (usually < 1%). Symbols marked `exposed` have only such sources."
)
_RESIDUAL_SOURCES = {"yfinance", "alpaca"}


# ── Pure core ────────────────────────────────────────────────────────────────

def basis_violations(bars: list[dict]) -> dict:
    """Count bars whose close or open lies outside the bar's own [low, high]."""
    close_out = open_out = any_out = 0
    for b in bars:
        lo, hi = b["low"], b["high"]
        c_bad = not (lo <= b["close"] <= hi)
        o_bad = not (lo <= b["open"] <= hi)
        close_out += c_bad
        open_out += o_bad
        any_out += c_bad or o_bad
    n = len(bars)
    return {
        "n": n,
        "close_outside": close_out,
        "open_outside": open_out,
        "any_outside": any_out,
        "share": (any_out / n) if n else 0.0,
    }


def big_jumps(bars: list[dict], threshold: float = JUMP_THRESHOLD) -> list[dict]:
    """Close-to-close moves larger than ``threshold`` (0.40 = 40%), in either direction."""
    out = []
    for prev, cur in zip(bars, bars[1:]):
        p, c = prev["close"], cur["close"]
        if p > 0 and abs(c / p - 1.0) > threshold:
            out.append({"time": cur["time"], "prev_close": p, "close": c, "ratio": c / p})
    return out


def residual_exposed(rows: list[tuple]) -> bool:
    """True when every stored row's source is yfinance or Alpaca (T3's residual case)."""
    sources = {r[5] for r in rows if r[5] is not None}
    return bool(sources) and sources <= _RESIDUAL_SOURCES


def build_report(
    bars_by_symbol: dict[str, list[dict]],
    rows_by_symbol: dict[str, list[tuple]],
    header: str,
    states_by_symbol: dict[str, dict] | None = None,
) -> str:
    from app.services.historical_store import stale_reasons

    lines = [header, "## Per symbol", "",
             "| Symbol | Bars | Close outside | Open outside | Share outside | Jumps > 40% "
             "| Stale reasons | Earliest stale | Residual |",
             "|---|---:|---:|---:|---:|---:|---|---|---|"]
    tot_n = tot_any = flagged = 0
    jump_lines: list[str] = []
    for symbol in sorted(bars_by_symbol):
        bars = bars_by_symbol[symbol]
        rows = rows_by_symbol.get(symbol, [])
        v = basis_violations(bars)
        jumps = big_jumps(bars, JUMP_THRESHOLD)
        report = stale_reasons(rows, (states_by_symbol or {}).get(symbol))
        tot_n += v["n"]
        tot_any += v["any_outside"]
        flagged += report is not None
        lines.append(
            f"| {symbol} | {v['n']} | {v['close_outside']} | {v['open_outside']} "
            f"| {v['share']:.2%} | {len(jumps)} "
            f"| {', '.join(report.reasons) if report else '-'} "
            f"| {report.earliest.isoformat() if report else '-'} "
            f"| {'exposed' if residual_exposed(rows) else '-'} |"
        )
        for j in jumps:
            jump_lines.append(
                f"| {symbol} | {j['time']} | {j['prev_close']:.4f} | {j['close']:.4f} "
                f"| x{j['ratio']:.4f} |"
            )
    lines += ["", "## Totals", "",
              f"- Bars: {tot_n}; outside own range: {tot_any} "
              f"({(tot_any / tot_n if tot_n else 0.0):.2%})",
              f"- Symbols flagged by `stale_reasons`: {flagged} of {len(bars_by_symbol)}",
              "", f"> {RESIDUAL_NOTE}", "", "## Close-to-close jumps above 40%", ""]
    if jump_lines:
        lines += ["| Symbol | Date | Prev close | Close | Ratio |", "|---|---|---:|---:|---:|"]
        lines += jump_lines
    else:
        lines.append("None.")
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────────

async def _main(args) -> str:
    symbols = args.symbols or await stored_symbols()
    bars = await load_bars(symbols, args.start, args.end)
    rows = await load_basis_rows(symbols)
    states = await load_history_states(symbols)
    header = report_header(
        "Bar-basis check", symbols=symbols, start=args.start, end=args.end,
        cost_model="n/a (no trades simulated)", loaded=loaded_range(bars),
        extra={"Stale-reason rows": "full stored row set per symbol (not date-bounded)"},
    )
    return build_report(bars, rows, header, states_by_symbol=states)


def main(argv: list[str] | None = None) -> None:
    args = common_parser(__doc__.splitlines()[0]).parse_args(argv)
    emit(asyncio.run(_main(args)), args.out)


if __name__ == "__main__":
    main()
