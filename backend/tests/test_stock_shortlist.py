"""Shortlist cap ranking in POST /api/stock-scan.

The Stocks twin of test_shortlist.py. `candidates` is assembled from
asyncio.gather results in universe-file order, so a bare slice kept whichever
names come first in the file. Every test here therefore puts the names that
SHOULD win at the END of the universe: with the sort removed they are the ones
cut, and each test fails.

`_process_stock` is patched to hand back finished PositionCardOut objects:
what is under test is the assembly after gather (rank, cut, record, count),
not the per-symbol gates, which test_stock_scan_funnel.py covers.
"""
from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import patch, AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.routers.stock_scan import router as stock_scan_router
from app.schemas.stock_scan import PositionCardOut, StrategySignalOut, BacktestOut
from tests.conftest import _override_get_db

_PREFIX = "Shortlist cap:"


@pytest.fixture
def stock_client():
    app = FastAPI()
    app.include_router(stock_scan_router)
    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def _pc(symbol: str, score: int, status: str = "PASS", confidence: int | None = 60) -> PositionCardOut:
    return PositionCardOut(
        symbol=symbol, company=symbol, price=100.0, direction="Bullish",
        strategy=StrategySignalOut(
            strategy="pullback_ema", entry_price=100.0, stop_price=95.0,
            target_price=110.0, targets=[110.0], rr_ratio=2.0, atr=2.0, detail={},
        ),
        backtest=BacktestOut(
            n_trades=10, win_rate=0.6, total_return_pct=10.0, max_drawdown_pct=5.0,
            expectancy=1.0, sharpe=1.0, confidence=confidence, passes_gate=True,
            summary_text="",
        ),
        stock_score=score, stock_status=status, shares=10, dollar_risk=50.0,
        dollar_size=1000.0, confidence=confidence,
    )


def _run(stock_client, cards: list, cap: int, extra_rejects: dict | None = None) -> dict:
    """Scan `cards` (in this universe order) with the given cap. `extra_rejects`
    maps a symbol to a rejection dict its _process_stock returns instead."""
    by_symbol = {c.symbol: c for c in cards}
    extra_rejects = extra_rejects or {}
    symbols = [c.symbol for c in cards] + list(extra_rejects)

    async def fake_process(symbol, *_a, **_kw):
        if symbol in extra_rejects:
            return {"symbol": symbol, "reason": extra_rejects[symbol]}
        return by_symbol[symbol]

    with ExitStack() as stack:
        stack.enter_context(patch("app.routers.stock_scan._process_stock", fake_process))
        stack.enter_context(patch("app.routers.stock_scan.fetch_quotes", return_value={}))
        stack.enter_context(patch(
            "app.routers.stock_scan.get_historical_bars", AsyncMock(return_value=[])))
        r = stock_client.post("/api/stock-scan", json={
            "symbols": symbols, "universe": [], "direction": "Bullish",
            "horizon": "Swing", "strategy": "pullback_ema",
            "shortlist_max_candidates": cap,
        })
    assert r.status_code == 200, r.text
    return r.json()


def _kept(body) -> list[str]:
    return [c["symbol"] for c in body["candidates"]]


def _trimmed(body) -> dict[str, str]:
    return {r["symbol"]: r["reason"] for r in body["rejected"]
            if r["reason"].startswith(_PREFIX)}


def test_the_best_scorers_survive_even_when_they_come_last_in_the_universe(stock_client):
    cards = [_pc(f"LOW{i}", 50 + i) for i in range(5)] + [_pc("TOP1", 95), _pc("TOP2", 90)]
    body = _run(stock_client, cards, cap=3)

    assert _kept(body) == ["TOP1", "TOP2", "LOW4"]
    trimmed = _trimmed(body)
    assert set(trimmed) == {"LOW0", "LOW1", "LOW2", "LOW3"}
    assert trimmed["LOW3"] == (
        "Shortlist cap: PASS score 53 confidence 60% ranked 4 of 7 (cap 3)")
    assert trimmed["LOW0"].endswith("ranked 7 of 7 (cap 3)")
    assert body["shortlist_truncated"] is True
    assert body["original_count"] == 7


def test_a_pass_outranks_a_higher_scoring_caution(stock_client):
    # CAUTION 88 came from a confidence-gate downgrade; a PASS 70 is the
    # cleaner setup and must be kept over it.
    cards = [_pc("CAUT", 88, status="CAUTION"), _pc("PASS", 70)]
    body = _run(stock_client, cards, cap=1)

    assert _kept(body) == ["PASS"]
    assert _trimmed(body)["CAUT"].startswith("Shortlist cap: CAUTION score 88 ")


def test_confidence_breaks_a_score_tie_and_unmeasured_sorts_last(stock_client):
    cards = [
        _pc("NOCONF", 80, confidence=None),
        _pc("LOWCONF", 80, confidence=40),
        _pc("HICONF", 80, confidence=75),
    ]
    body = _run(stock_client, cards, cap=2)

    assert _kept(body) == ["HICONF", "LOWCONF"]
    assert _trimmed(body)["NOCONF"] == (
        "Shortlist cap: PASS score 80 confidence n/a ranked 3 of 3 (cap 2)")


def test_a_measured_zero_confidence_outranks_an_unmeasured_one(stock_client):
    # Pins None-last against `-(c.confidence or 0)`, which would tie them.
    cards = [_pc("NONE", 80, confidence=None), _pc("ZERO", 80, confidence=0)]
    body = _run(stock_client, cards, cap=1)

    assert _kept(body) == ["ZERO"]


def test_an_exact_tie_keeps_universe_order(stock_client):
    cards = [_pc(s, 80) for s in ("AAA", "BBB", "CCC", "DDD")]
    body = _run(stock_client, cards, cap=2)

    assert _kept(body) == ["AAA", "BBB"]
    assert set(_trimmed(body)) == {"CCC", "DDD"}


def test_candidates_are_ranked_even_when_nothing_is_cut(stock_client):
    # Rank deltas on Step 4 read list position, so the order matters with no cap hit.
    cards = [_pc("C", 60), _pc("B", 70, status="CAUTION"), _pc("A", 90)]
    body = _run(stock_client, cards, cap=10)

    assert _kept(body) == ["A", "C", "B"]
    assert _trimmed(body) == {}
    assert body["shortlist_truncated"] is False
    assert body["pipeline"]["failed_shortlist"] == 0


def test_trimmed_names_count_as_shortlist_not_residual_and_the_funnel_reconciles(stock_client):
    cards = [_pc(f"S{i}", 50 + i) for i in range(6)]
    body = _run(stock_client, cards, cap=2, extra_rejects={
        "ERR": "unknown strategy wat",
        "SIG": "no pullback_ema setup",
    })
    p = body["pipeline"]

    assert p["failed_shortlist"] == 4 == len(_trimmed(body))
    assert p["other_rejected"] == 1        # only ERR: the trimmed names are not in the residual
    assert p["failed_signal"] == 1
    assert p["candidates"] == 2 == len(body["candidates"])
    accounted = sum(p[k] or 0 for k in (
        "candidates", "failed_history", "failed_score", "failed_signal",
        "failed_backtest", "failed_regime", "failed_direction",
        "failed_direction_unmeasured", "failed_shortlist", "other_rejected"))
    assert accounted == p["scanned"] == 8


def test_the_frontend_prefix_matches_the_backend_constant():
    """Both backend prefixes equal the ONE frontend constant, and no other
    frontend source file spells the literal itself (so the options scan log
    and the stock over-cap split cannot drift apart)."""
    from app.routers.stock_scan import _SHORTLIST_REASON_PREFIX, classify_stock_rejection
    from app.routers.scan import _SHORTLIST_REASON_PREFIX as _OPTIONS_PREFIX
    import pathlib, re

    assert _SHORTLIST_REASON_PREFIX == _PREFIX
    assert _OPTIONS_PREFIX == _PREFIX
    assert classify_stock_rejection(_PREFIX + " PASS score 1") == "failed_shortlist"
    frontend = pathlib.Path(__file__).resolve().parents[2] / "frontend"
    ts = (frontend / "lib" / "shortlistCap.ts").read_text(encoding="utf-8")
    m = re.search(r"export const SHORTLIST_REASON_PREFIX\s*=\s*'([^']*)'", ts)
    assert m and m.group(1) == _PREFIX

    # One source: no other non-test file under app/components/lib/types may
    # carry the prefix inside a string literal (comments may name it), and the
    # two consumers must import it. Scanned with a string-aware pass so a '//'
    # inside a URL string does not hide the rest of the line as a "comment".
    # Not caught: a literal split by concatenation ('Shortlist ' + 'cap:').
    spelled = sorted(
        f.relative_to(frontend).as_posix()
        for d in ("app", "components", "lib", "types")
        for f in (frontend / d).rglob("*.ts*")
        if "__tests__" not in f.parts and f.name != "shortlistCap.ts"
        and not re.search(r"\.(test|spec)\.tsx?$", f.name)
        and any(_PREFIX in lit for lit in _ts_string_literals(f.read_text(encoding="utf-8")))
    )
    assert spelled == []
    imports = re.compile(r"""from\s+['"](?:@/lib/|(?:\.{1,2}/)+(?:[\w()\-]+/)*)shortlistCap['"]""")
    for rel in ("lib/stockShortlist.ts",
                "app/(frame)/screener/step-3-direction/scanLogTotals.ts"):
        assert imports.search((frontend / rel).read_text(encoding="utf-8")), rel


def _ts_string_literals(src: str) -> list[str]:
    """String-literal bodies ('..', "..", `..`) of TS source, comments skipped.
    A tokenizer just good enough for the pin above: it tracks string and
    comment state so neither can hide the other."""
    out, i, n = [], 0, len(src)
    while i < n:
        ch = src[i]
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif ch in "'\"`":
            j, buf = i + 1, []
            while j < n and src[j] != ch:
                if src[j] == "\\":
                    buf.append(src[j:j + 2]); j += 2
                    continue
                if ch != "`" and src[j] == "\n":
                    break
                buf.append(src[j]); j += 1
            out.append("".join(buf))
            i = j + 1
        else:
            i += 1
    return out


def test_the_ts_literal_scanner_is_not_fooled_by_urls_or_globs():
    lits = _ts_string_literals(
        "const u='http://x'; const p='Shortlist cap:';\n"
        "const g='src/*'; const q=\"Over: Shortlist cap: y\";\n"
        "// 'Shortlist cap: in a comment'\n/* \"Shortlist cap: block\" */ const t=`a ${b} c`;")
    assert "Shortlist cap:" in lits
    assert "Over: Shortlist cap: y" in lits
    assert not any("comment" in l or "block" in l for l in lits)
