# Trading Review Fixes (Phase A: the six Highs) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the six High findings in `TRADING_REVIEW.md` (2026-10-02, overall REJECT) so that areas 2, 3 and 4 can be re-graded: the WFO tuner grades the right direction and really runs out-of-sample, an earnings date inside the reject window vetoes an options trade, an option position can never put more than the per-trade loss limit at risk, the basket stops claiming it sent orders, and `pullback_ema` stops emitting signals whose first target is a fraction of its risk.

**Architecture:** Six independent backend/frontend fixes, each in its own TDD task and commit. No new modules: every fix lands in the file that owns the behaviour today. The Medium/Low items (#7–#16) are listed in Phase B at the end as a backlog that needs its own plan. Several depend on Phase A (re-tuning needs #1/#2; the account-value fix changes #4's base).

**Tech Stack:** FastAPI + Pydantic v2, pytest; `backtesting.py` engine; Next.js 15 / TypeScript 5.7 strict, Zustand, Jest.

**Spec:** `TRADING_REVIEW.md` (repo root). Read its "Fix list", "Cross-parameter table" and "The Chair" sections. Each task below cites the fix-list number it closes.

## Global Constraints

- Every task is TDD: a failing test first, then the code. Backend tests run from `backend/` with `./.venv/Scripts/python.exe -m pytest`. Frontend runs from `frontend/` with `npm run test` and `npm run typecheck`.
- `npm run typecheck` must be clean before every commit that touches `frontend/`.
- Do not change any score threshold, weight or strategy parameter value except the ones a task names.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- `risk_rules.yaml` is rewritten (comments dropped) by Settings → Risk on save. Put any new explanation in code comments or `SCORING_RULES.md`, not in a YAML comment, except in the header lines.
- The repo rule from `CLAUDE.md` applies: nothing is done until an adversarial round comes back clean (Task 9).

## Decisions this plan takes (Kenneth can override before execution)

| ID | Decision | Alternative rejected |
|---|---|---|
| D1 | Direction is normalised **inside** `run_strategy_backtest` and at the store/adopt boundary, not only in config | Fixing only the YAML to `Bullish` leaves the trap for the next caller |
| D2 | WFO folds get a warm-up prefix (260 bars), and only entries dated inside the fold are scored | Raising `test_months` to 5 keeps the 200-period indicators cold at the start of every fold |
| D3 | Only **earnings** inside the reject window vetoes. A dividend stays a score penalty | A dividend inside a long-option hold is not an IV-crush event |
| D4 | An unknown earnings date does **not** change the score (SPY and other ETFs have none). It shows as CAUTION on the Step-7 checklist | Scoring unknown as CAUTION would penalise every ETF |
| D5 | For options, the effective single-position cap is `min(max_single_position_pct, max_loss_per_trade_pct)`. Today that is 3.75%, not 5%. Long premium with no protective order can lose 100% | Keeping 5% and making the loss check advisory is the defect itself |
| D6 | Basket sends are honestly labelled "tracked, no broker order" and stored as `source: 'manual'`. Real basket routing is Phase B | Routing the basket through the direct-send path is a large change to a heavily audited flow |
| D7 | `pullback_ema` skips (does not clamp) a signal whose first target is below `min_signal_rr` R. **Amended 2026-10-03 (Kenneth):** the mechanism stays but ships **disabled** (`min_signal_rr: 0.0`) until the Phase B multi-year re-tune. On the fixtures 1.0 made pullback_ema worse per trade (AAPL +0.08 → −4.35 %, NVDA +0.415 → −2.34 %, SPY −0.52 → −3.78 %, n ≤ 11) | Clamping manufactures a target the strategy never claimed (the Chair's ruling). Shipping 1.0 now: the fixture evidence went the wrong way |

## Task 0: Branch, claim, carry the review

The current branch `claude/pipeline-inspector-fixes` holds Kenneth's uncommitted pipeline-inspector work. Do not touch it. Work in a separate worktree off `main`.

- [ ] **Step 1: Create the worktree and branch**

```bash
cd C:/GitHub/trading-assistant
git fetch origin main
git worktree add ../trading-assistant-review-fixes -b claude/trading-review-fixes origin/main
cp TRADING_REVIEW.md ../trading-assistant-review-fixes/TRADING_REVIEW.md
```

- [ ] **Step 2: Claim the task**

```bash
cd ../trading-assistant-review-fixes
python3 scripts/claim.py take TRADING-REVIEW-FIXES -m "Phase A: six High findings from TRADING_REVIEW.md"
```
Expected: exit 0. Exit 1 means someone holds it, so stop and ask Kenneth.

- [ ] **Step 3: Baseline**

```bash
python3 scripts/state.py
cd backend && ./.venv/Scripts/python.exe -m pytest -q tests/test_strategy_backtest.py tests/test_walk_forward.py tests/test_strategy_param_optimizer.py tests/test_strategy_param_store_direction.py tests/test_strategy_tuning_router.py tests/test_stock_scorer_events.py tests/test_portfolio_risk_contract_cap.py tests/test_auto_trader.py
```
Record the pass count. The session-start hook reported STATE DRIFT, so record what `state.py` prints but do not fix it here. It is not this plan's scope.

- [ ] **Step 4: Commit the review**

```bash
git add TRADING_REVIEW.md docs/superpowers/plans/2026-10-03-trading-review-fixes-plan.md
git commit -m "docs: trading review 2026-10-02 and Phase A fix plan

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push -u origin claude/trading-review-fixes
```

---

### Task 1: WFO direction normalisation (fix #1, High)

**Files:**
- Modify: `backend/app/services/strategy_backtest.py:15-22` (add `normalize_direction`, use it in `run_strategy_backtest`)
- Modify: `backend/app/services/strategy_param_store.py:111-113` (`get_direction`)
- Modify: `backend/app/services/strategy_param_optimizer.py` (`build_proposal` carries `direction`; `run_optimization` normalises)
- Modify: `backend/app/routers/strategy_tuning.py:23-27, 183-188` (`AdoptRequest.direction` required + normalised)
- Modify: `frontend/lib/api.ts:1118-1127, 1157-1158`; `frontend/app/(frame)/settings/page.tsx:2552-2555` and the call site that passes params to `handleAdopt`
- Test: `backend/tests/test_strategy_direction_normalise.py` (new)

**Interfaces:**
- Produces: `normalize_direction(direction: str) -> Literal["Bullish", "Bearish"]` in `app.services.strategy_backtest`. It raises `ValueError` on anything else. Task 2 relies on `run_strategy_backtest` calling it first.
- Produces: the proposal dict gains `"direction": "Bullish" | "Bearish"`. `WfoProposal.direction` in TS.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_strategy_direction_normalise.py
"""Fix #1 (TRADING_REVIEW.md): lowercase 'bullish' ran the BEARISH branch."""
import json
from pathlib import Path

import pytest

from app.services.strategy_backtest import normalize_direction, run_strategy_backtest

FIX = Path(__file__).parent / "fixtures" / "SPY_candles.json"


def _spy():
    return json.loads(FIX.read_text())


@pytest.mark.parametrize("raw,expected", [
    ("bullish", "Bullish"), ("Bullish", "Bullish"), (" BULLISH ", "Bullish"),
    ("bearish", "Bearish"), ("Bearish", "Bearish"),
])
def test_normalize_direction(raw, expected):
    assert normalize_direction(raw) == expected


@pytest.mark.parametrize("raw", ["", "long", "neutral", None])
def test_normalize_direction_rejects_unknown(raw):
    with pytest.raises(ValueError):
        normalize_direction(raw)


def test_lowercase_bullish_backtest_equals_capitalised():
    bars = _spy()
    lower = run_strategy_backtest(bars, strategy="pullback_ema", direction="bullish")
    upper = run_strategy_backtest(bars, strategy="pullback_ema", direction="Bullish")
    assert lower.n_trades == upper.n_trades
    assert lower.expectancy == upper.expectancy
    assert lower.direction == "Bullish"


def test_get_direction_is_normalised(monkeypatch):
    from app.services import strategy_param_store as store
    monkeypatch.setattr(store, "_load", lambda: {"direction": "bullish"})
    assert store.get_direction() == "Bullish"


def test_build_proposal_carries_direction():
    from app.services.strategy_param_optimizer import build_proposal
    p = build_proposal(
        strategy="pullback_ema", direction="Bearish",
        fold_winners=[{"ema_period": 20}], fold_test_returns=[1.0],
        in_sample_return=2.0, walk_forward_return=1.0,
        oos_metrics={"sharpe": 1, "expectancy": 0.1, "win_rate": 0.5,
                     "total_return": 1.0, "max_drawdown": -1.0, "n_trades": 30},
        min_trades=20,
    )
    assert p["direction"] == "Bearish"


def test_adopt_requires_direction_and_normalises():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    r = client.post("/api/strategy-tuning/adopt",
                    json={"strategy": "pullback_ema", "params": {"ema_period": 20}})
    assert r.status_code == 422
```

The last test only proves the 422 path. It must not write to the real `strategy_params.yaml`. Check `tests/test_strategy_tuning_router.py` for how it isolates the store (a monkeypatched `store.adopt`), and reuse that fixture for a positive case that asserts `store.adopt` received `direction="Bearish"` for input `"bearish"`.

- [ ] **Step 2: Run and confirm failure**

Run: `./.venv/Scripts/python.exe -m pytest -q tests/test_strategy_direction_normalise.py`
Expected: ImportError on `normalize_direction`.

- [ ] **Step 3: Implement**

In `strategy_backtest.py`, below `Strategy = ...`:

```python
def normalize_direction(direction: str | None) -> Literal["Bullish", "Bearish"]:
    """The one spelling the signal functions compare against.

    Every branch in strategy_engine and `_entry_side` tests ``== "Bullish"``
    and treats anything else as bearish, so a config value ``bullish`` silently
    ran the BEARISH branch in the WFO tuner (TRADING_REVIEW.md fix #1).
    Unknown values raise instead of falling through to bearish.
    """
    d = str(direction or "").strip().lower()
    if d == "bullish":
        return "Bullish"
    if d == "bearish":
        return "Bearish"
    raise ValueError(f"direction must be bullish|bearish, got {direction!r}")
```

First line of `run_strategy_backtest` body (before the imports):

```python
    direction = normalize_direction(direction)
```

`strategy_param_store.get_direction`:

```python
def get_direction() -> str:
    """Optimization direction, normalised to 'Bullish' | 'Bearish' (fix #1)."""
    from app.services.strategy_backtest import normalize_direction
    return normalize_direction(_load().get("direction", "bullish"))
```

`strategy_param_optimizer.build_proposal`: add a keyword `direction: str` parameter and `"direction": direction,` in the returned dict. Pass `direction=direction` from `_optimize_strategy_sync`. In `run_optimization`, first line of the body: `direction = normalize_direction(direction)` (import from `strategy_backtest`).

`strategy_tuning.AdoptRequest`:

```python
    direction: Literal["Bullish", "Bearish"]   # REQUIRED -- fix #1: the old
    # "Bullish" default wrote bearish-tuned params into active.bullish.

    @field_validator("direction", mode="before")
    @classmethod
    def _norm_direction(cls, v):
        from app.services.strategy_backtest import normalize_direction
        return normalize_direction(v)
```

Frontend: add `direction: 'Bullish' | 'Bearish';` to `WfoProposal`. Change `adoptStrategyParams(strategy, params, direction)` to post `{ strategy, params, direction }`. Change `handleAdopt` to take the proposal's `direction` and pass it through. Update its caller (search `onAdopt` / `handleAdopt(` in `settings/page.tsx`).

- [ ] **Step 4: Run tests and typecheck**

```bash
./.venv/Scripts/python.exe -m pytest -q tests/test_strategy_direction_normalise.py tests/test_strategy_tuning_router.py tests/test_strategy_param_store_direction.py tests/test_strategy_backtest.py tests/test_strategy_backtest_bearish.py
cd ../frontend && npm run typecheck && npm run test -- --testPathPattern=settings
```
Expected: all pass. Any existing test that posts `/adopt` without `direction` must be updated to send it. That is the intended breaking change.

- [ ] **Step 5: Commit**

```bash
git add -A backend/app/services/strategy_backtest.py backend/app/services/strategy_param_store.py backend/app/services/strategy_param_optimizer.py backend/app/routers/strategy_tuning.py backend/tests frontend/lib/api.ts "frontend/app/(frame)/settings/page.tsx"
git commit -m "fix(wfo): normalise direction so bullish tuning runs the bullish branch (review #1)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: WFO folds with warm-up, scored only inside the fold (fix #2, High)

**Files:**
- Modify: `backend/app/services/strategy_backtest.py` (`run_strategy_backtest` gains `entry_start`; new `_window_stats`)
- Modify: `backend/app/services/walk_forward.py` (new `WARMUP_BARS`, `MIN_SCORED_BARS`, `slice_with_warmup`; `train_fold` uses it)
- Modify: `backend/app/services/strategy_param_optimizer.py:118-122` (OOS loop uses it)
- Modify: `backend/tests/test_strategy_param_optimizer.py:34` (fake accepts `**kwargs`)
- Test: `backend/tests/test_walk_forward_warmup.py` (new)

**Interfaces:**
- Consumes: `normalize_direction` (Task 1) is already applied inside `run_strategy_backtest`.
- Produces: `run_strategy_backtest(..., entry_start: date | None = None)`. With it set, no entry is placed on a bar dated before `entry_start`, and `total_return_pct`, `max_drawdown_pct` and `sharpe` are computed only over the equity curve from `entry_start` onward.
- Produces: `slice_with_warmup(bars, start, end, warmup=WARMUP_BARS) -> tuple[list[dict], int]`. It returns the window (warm-up prefix + `[start, end)`) and the count of bars inside `[start, end)`. Bars must be sorted ascending with `_date` precomputed.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_walk_forward_warmup.py
"""Fix #2: on trading-day bars a 3-month test fold is ~62 bars, under the
100-bar engine minimum, so every OOS fold was skipped."""
from datetime import date, timedelta

from app.services.walk_forward import (
    build_folds, precompute_bar_dates, slice_with_warmup, WARMUP_BARS, MIN_SCORED_BARS,
)


def _weekday_bars(years=3, start=date(2021, 1, 4)):
    bars, d, px, i = [], start, 100.0, 0
    end = start + timedelta(days=365 * years)
    while d < end:
        if d.weekday() < 5:
            px *= 1.0015 if i % 7 else 0.985
            bars.append({"time": d.isoformat(), "open": px * 0.998, "high": px * 1.01,
                         "low": px * 0.99, "close": px, "volume": 1_000_000})
            i += 1
        d += timedelta(days=1)
    precompute_bar_dates(bars)
    return bars


def test_trading_day_test_fold_is_short_but_scored_with_warmup():
    bars = _weekday_bars()
    folds = build_folds(bars[0]["_date"], bars[-1]["_date"], train_months=12, test_months=3)
    assert folds
    f = folds[1]
    window, scored = slice_with_warmup(bars, f.test_start, f.test_end)
    assert 55 <= scored <= 70              # the review's 61-62 bars
    assert scored >= MIN_SCORED_BARS
    assert len(window) == scored + WARMUP_BARS
    assert window[WARMUP_BARS]["_date"] >= f.test_start
    assert window[WARMUP_BARS - 1]["_date"] < f.test_start


def test_entry_start_blocks_entries_before_it():
    from app.services.strategy_backtest import run_strategy_backtest
    import json
    from pathlib import Path
    bars = json.loads((Path(__file__).parent / "fixtures" / "SPY_candles.json").read_text())
    cut = date.fromisoformat(str(bars[180]["time"])[:10])
    full = run_strategy_backtest(bars, strategy="pullback_ema", direction="Bullish")
    late = run_strategy_backtest(bars, strategy="pullback_ema", direction="Bullish", entry_start=cut)
    assert late.n_trades <= full.n_trades


def test_oos_backtest_runs_on_trading_day_folds(monkeypatch):
    """Before the fix the OOS call count was 0 on trading-day bars."""
    from app.services.strategy_backtest import BacktestResult
    from app.services.strategy_param_optimizer import _optimize_strategy_sync
    import app.services.walk_forward as wf
    import app.services.strategy_backtest as sb

    calls = []

    def fake(bars, *, strategy, direction, params=None, entry_start=None, **kw):
        calls.append((len(bars), entry_start))
        return BacktestResult(strategy=strategy, direction=direction, n_trades=3, win_rate=0.6,
                              total_return_pct=1.0, max_drawdown_pct=-1.0, expectancy=0.3,
                              sharpe=0.8, confidence=None, passes_gate=False, summary_text="")

    monkeypatch.setattr(wf, "run_strategy_backtest", fake)
    monkeypatch.setattr(sb, "run_strategy_backtest", fake)
    bars = _weekday_bars()
    folds = build_folds(bars[0]["_date"], bars[-1]["_date"], train_months=12, test_months=3)
    _optimize_strategy_sync("pullback_ema", "Bullish", {"SPY": bars}, folds,
                            {"ema_period": [20]}, {"fee_pct": 0.001, "slippage_pct": 0.001},
                            min_trades=1, min_consistency=0.0)
    oos = [c for c in calls if c[1] is not None and any(c[1] == f.test_start for f in folds)]
    assert len(oos) == len(folds)
```

- [ ] **Step 2: Run and confirm failure**

Run: `./.venv/Scripts/python.exe -m pytest -q tests/test_walk_forward_warmup.py`
Expected: ImportError on `slice_with_warmup`.

- [ ] **Step 3: Implement `walk_forward.py`**

```python
# Largest indicator look-back any strategy uses (trend_sma 200 + BB/RSI period
# headroom; mean_reversion_bb needs ~225) plus margin. Fix #2: test folds used
# to start with cold indicators AND were dropped below 100 bars.
WARMUP_BARS = 260
# Fewest bars inside [start, end) worth scoring. A 3-month fold is ~62 trading
# bars; 40 tolerates holidays and a short final fold.
MIN_SCORED_BARS = 40


def slice_with_warmup(
    bars: list[dict], start: date, end: date, warmup: int = WARMUP_BARS,
) -> tuple[list[dict], int]:
    """Warm-up prefix + [start, end). Bars must be ascending with `_date` set.

    Returns (window, n_scored), where n_scored counts the bars inside [start, end).
    The prefix is shorter than `warmup` only when the data starts later.
    """
    first = next((i for i, b in enumerate(bars) if b["_date"] >= start), len(bars))
    lo = max(0, first - warmup)
    window = [b for b in bars[lo:] if b["_date"] < end]
    return window, len(window) - (first - lo)
```

In `train_fold`, replace the slice and guard:

```python
            train_bars, n_scored = slice_with_warmup(bars, fold.train_start, fold.train_end)
            if n_scored < MIN_SCORED_BARS or len(train_bars) < 100:
                continue
            try:
                res = run_strategy_backtest(train_bars, strategy=strategy, direction=direction,
                                            params=combo, entry_start=fold.train_start)
```

- [ ] **Step 4: Implement the OOS loop in `strategy_param_optimizer.py`**

Replace lines 120–124 (the `_slice_bars` + `>= 100` guard + call):

```python
            test_bars, n_scored = slice_with_warmup(bars, fold.test_start, fold.test_end)
            # Fix #2: judge the fold on bars INSIDE it (>= MIN_SCORED_BARS); the
            # warm-up prefix only primes indicators and can place no entry.
            if n_scored >= MIN_SCORED_BARS and len(test_bars) >= 100:
                try:
                    res = run_strategy_backtest(
                        test_bars, strategy=strategy, direction=direction, params=winner,
                        entry_start=fold.test_start,
                    )
```
Import `slice_with_warmup, MIN_SCORED_BARS` from `walk_forward`. Drop `_slice_bars` from the import if it is now unused. Update the comment at the `n_trades` key ("skipped by the 100-bar OOS guard" → "skipped by the MIN_SCORED_BARS guard").

- [ ] **Step 5: Implement `entry_start` in `run_strategy_backtest`**

Signature: add `entry_start: date | None = None` (import `from datetime import date`). Inside `_Strategy.next`, before `if not self.position:`:

```python
            if entry_start is not None and self.data.index[-1].date() < entry_start:
                return  # warm-up bar: indicators prime, no entry (fix #2)
```

This needs a datetime index, which `_bars_to_df` builds when bars carry `time` (WFO bars always do). Add a guard after building `df`: if `entry_start is not None and not isinstance(df.index, pd.DatetimeIndex)`, return `_empty_result(strategy, direction, "entry_start needs dated bars")`.

After `stats = bt.run()`, when `entry_start` is set, recompute the window stats:

```python
def _window_stats(equity: pd.Series) -> tuple[float, float, float]:
    """Return %, max drawdown % (<= 0), annualised Sharpe of an equity slice."""
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return 0.0, 0.0, 0.0
    ret = (equity.iloc[-1] / equity.iloc[0] - 1.0) * 100.0
    dd = float(((equity / equity.cummax()) - 1.0).min() * 100.0)
    daily = equity.pct_change().dropna()
    sd = float(daily.std())
    sharpe = float(daily.mean() / sd * (252 ** 0.5)) if sd > 0 else 0.0
    return float(ret), dd, sharpe
```

```python
    if entry_start is not None:
        eq = stats["_equity_curve"]["Equity"]
        eq = eq[eq.index >= pd.Timestamp(entry_start)]
        total_ret, max_dd, sharpe = _window_stats(eq)
```
Place this after the existing `total_ret`/`max_dd`/`sharpe` assignments, so it overrides them. Train and OOS both use it, so the IS-vs-OOS degradation compares like with like.

- [ ] **Step 6: Fix the existing optimizer test fake**

`tests/test_strategy_param_optimizer.py:34`: change the fake's signature to `def fake_backtest(bars, *, strategy, direction, params=None, **kwargs):`. Its comment at line 50 ("test_months=4 (~123 days) clears the OOS section's >=100-bar minimum") becomes "calendar-day synthetic bars; the warm-up path is covered on trading-day bars in test_walk_forward_warmup.py".

- [ ] **Step 7: Run tests**

```bash
./.venv/Scripts/python.exe -m pytest -q tests/test_walk_forward_warmup.py tests/test_walk_forward.py tests/test_strategy_param_optimizer.py tests/test_strategy_backtest.py tests/test_strategy_backtest_bearish.py tests/test_data_leakage.py
```
Expected: all pass. `test_data_leakage.py` must stay green. The warm-up prefix comes from bars **before** the fold, so no future data enters.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/walk_forward.py backend/app/services/strategy_param_optimizer.py backend/app/services/strategy_backtest.py backend/tests/test_walk_forward_warmup.py backend/tests/test_strategy_param_optimizer.py
git commit -m "fix(wfo): warm-up prefix and in-fold scoring so OOS folds run on trading-day data (review #2)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Earnings veto in the options scan (fix #3, part 1, High)

**Files:**
- Modify: `backend/app/scoring/stock_scorer.py:858-904` (`_rule_event` records `earnings_days` and `reject_days` in `detail`)
- Modify: `backend/app/routers/scan.py:142-143, 1219` (`_final_status` variadic; new `_earnings_veto`)
- Modify: `backend/app/schemas/__init__.py:612+` (`TradeCardData.earningsVeto: bool = False`, `earningsUnknown: bool = False`)
- Modify: `frontend/types/domain.ts:613+` (same two optional fields)
- Test: `backend/tests/test_stock_scorer_events.py` (append), `backend/tests/test_scan_earnings_veto.py` (new)

**Interfaces:**
- Produces: `RuleResult("event").detail` always carries `"earnings_days": int | None` and `"reject_days": int`. In options mode it also carries `"earnings_unknown": bool`.
- Produces: `_earnings_veto(card: StockScoreCard) -> bool` in `routers/scan.py`. Task 4 and Task 5 rely on `TradeCardData.earningsVeto` / `earningsUnknown`.

- [ ] **Step 1: Failing tests**

Append to `tests/test_stock_scorer_events.py`:

```python
def test_options_detail_records_earnings_even_when_dividend_is_nearer():
    cfg = {"event": {"reject_days": 21, "caution_days": 45}}
    r = _rule_event(earnings_date=date.today() + timedelta(days=5),
                    dividend_date=date.today() + timedelta(days=2),
                    cfg=cfg, scoring_mode="options")
    assert r.detail["event"] == "dividend"
    assert r.detail["earnings_days"] == 5
    assert r.detail["reject_days"] == 21


def test_options_unknown_earnings_flagged_but_score_unchanged():
    cfg = {"event": {"reject_days": 21, "caution_days": 45}}
    r = _rule_event(earnings_date=None, dividend_date=None, cfg=cfg, scoring_mode="options")
    assert r.status == "PASS" and r.score == 90       # D4: no ETF penalty
    assert r.detail["earnings_unknown"] is True
```

New `tests/test_scan_earnings_veto.py`:

```python
from app.routers.scan import _earnings_veto, _final_status
from app.scoring.stock_scorer import RuleResult


class _Card:
    def __init__(self, rules):
        self.rules = rules


def _ev(status, earnings_days, reject_days=21, event="earnings"):
    return RuleResult("event", status, 5, {"event": event, "earnings_days": earnings_days,
                                           "reject_days": reject_days})


def test_veto_when_earnings_inside_reject_window():
    assert _earnings_veto(_Card([_ev("REJECT", 3)])) is True


def test_veto_when_dividend_labelled_but_earnings_inside():
    assert _earnings_veto(_Card([_ev("REJECT", 5, event="dividend")])) is True


def test_no_veto_outside_window_or_unknown():
    assert _earnings_veto(_Card([_ev("CAUTION", 30)])) is False
    assert _earnings_veto(_Card([_ev("PASS", None)])) is False
    assert _earnings_veto(_Card([])) is False


def test_final_status_variadic_takes_worst():
    assert _final_status("PASS", "PASS", "PASS", "REJECT") == "REJECT"
    assert _final_status("PASS", "CAUTION", "PASS") == "CAUTION"
```

Check `RuleResult`'s constructor order in `stock_scorer.py` before running: `RuleResult(name, status, score, detail)` as used in `_rule_event`.

- [ ] **Step 2: Run and confirm failure**

`./.venv/Scripts/python.exe -m pytest -q tests/test_stock_scorer_events.py tests/test_scan_earnings_veto.py` should fail with a KeyError / ImportError.

- [ ] **Step 3: Implement `_rule_event`**

At the top of the function, after `today = date.today()`:

```python
    earnings_days = (earnings_date - today).days if earnings_date is not None else None
    if earnings_days is not None and earnings_days < 0:
        earnings_days = None
    base_detail = {"earnings_days": earnings_days, "reject_days": int(ec["reject_days"])}
    if scoring_mode != "stock":
        # D4 (fix #3): unknown is surfaced, never scored -- ETFs have no earnings.
        base_detail["earnings_unknown"] = earnings_date is None
```
Merge `base_detail` into every `detail` dict the function builds: `detail: dict = {"event": "none", **base_detail}` and `detail = {"event": event_label, "days_to_event": worst_days, **base_detail}`.

- [ ] **Step 4: Implement the veto in `scan.py`**

```python
def _final_status(*statuses: str) -> str:
    return min(statuses, key=lambda s: _ORDER.get(s, 1))


def _earnings_veto(card) -> bool:
    """Fix #3: earnings inside the horizon's reject window is a VETO on the
    options path, not a score penalty. 37 of 440 measured PASS setups stayed
    PASS with earnings 3 days out. Dividends stay a penalty (D3)."""
    r = next((r for r in card.rules if r.name == "event"), None)
    if r is None:
        return False
    days = r.detail.get("earnings_days")
    reject = r.detail.get("reject_days")
    return days is not None and reject is not None and days < reject
```

At line 1219:

```python
        finalStatus=_final_status(
            card.status, contract_card.status, entry.quality_status,
            "REJECT" if _earnings_veto(card) else "PASS",
        ),
        earningsVeto=_earnings_veto(card),
        earningsUnknown=bool(rule_detail.get("event", {}).get("earnings_unknown", False)),
```

Grep for other `_final_status(` callers (`grep -n "_final_status(" backend/app -r`) and confirm they still pass positional args. The variadic signature accepts them.

Schema (`TradeCardData`): add

```python
    # Fix #3: earnings inside the reject window -> finalStatus REJECT and no send.
    earningsVeto: bool = False
    earningsUnknown: bool = False
```
`frontend/types/domain.ts` `TradeCardData`: `earningsVeto?: boolean; earningsUnknown?: boolean;`

- [ ] **Step 5: Run tests**

```bash
./.venv/Scripts/python.exe -m pytest -q tests/test_stock_scorer_events.py tests/test_scan_earnings_veto.py tests/test_stock_scorer_stock_mode.py
./.venv/Scripts/python.exe -m pytest -q -k "scan" tests/
cd ../frontend && npm run typecheck
```
Expected: pass. If a scan snapshot test pins `finalStatus` for a fixture with near earnings, the new REJECT is the intended change. Update the expectation and say so in the commit body.

- [ ] **Step 6: Commit**

```bash
git commit -am "fix(scan): earnings inside the reject window vetoes an options candidate (review #3)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
(Add the new test file with `git add` first.)

---

### Task 4: Earnings veto at auto-trade fire time (fix #3, part 2, High)

**Files:**
- Modify: `backend/app/services/auto_trader.py` (new `EventVetoError`, `_apply_event_veto`, call in `fire()` right after the `_apply_vol_sizing` try-block at ~2357-2420)
- Test: `backend/tests/test_auto_trader_event_veto.py` (new)

**Interfaces:**
- Consumes: `effective_event_window(horizon, overrides)` from `app.scoring.stock_scorer`; `_calendar_dates_yf(symbol) -> (earnings, dividend)` from `app.data.market` (sync; `fire()` already does network I/O outside the lock at this point).
- Produces: `class EventVetoError(RuntimeError)` and history status `"event_veto_blocked"`. The `/auto-trade/fire` router already maps `RuntimeError`, so no router change is needed. Verify by reading how `RegimeHeadwindError` surfaces there.

- [ ] **Step 1: Failing tests**

```python
# backend/tests/test_auto_trader_event_veto.py
from datetime import date, timedelta
import pytest

import app.services.auto_trader as at


class _S:
    symbol = "AAPL"; horizon = "swing"; direction = "Bullish"


def test_veto_inside_window(monkeypatch):
    monkeypatch.setattr(at, "_fetch_earnings_date", lambda s: date.today() + timedelta(days=3))
    with pytest.raises(at.EventVetoError):
        at._apply_event_veto(_S())


def test_no_veto_outside_window(monkeypatch):
    monkeypatch.setattr(at, "_fetch_earnings_date", lambda s: date.today() + timedelta(days=90))
    at._apply_event_veto(_S())


def test_unknown_earnings_does_not_veto(monkeypatch):
    monkeypatch.setattr(at, "_fetch_earnings_date", lambda s: None)
    at._apply_event_veto(_S())


def test_missing_horizon_fails_closed(monkeypatch):
    monkeypatch.setattr(at, "_fetch_earnings_date", lambda s: None)
    s = _S(); s.horizon = None
    with pytest.raises(at.EventVetoError):
        at._apply_event_veto(s)
```

Add one integration test modelled on the existing `RegimeHeadwindError` fire test in `tests/test_auto_trader.py`. Find it with `grep -n "regime_headwind_blocked" tests/test_auto_trader.py` and copy its arrange block. Patch `_fetch_earnings_date` to 3 days out and assert:
(a) `fire()` raises `EventVetoError`;
(b) the last history row has `status == "event_veto_blocked"` and `premium_at_risk == 0.0`;
(c) the fake broker adapter's `place_order` was never called.

- [ ] **Step 2: Run and confirm failure** (`AttributeError: EventVetoError`).

- [ ] **Step 3: Implement**

Near the other error classes (~line 136):

```python
class EventVetoError(RuntimeError):
    """Fix #3: an earnings date inside the trade's horizon reject window.
    The scan marks such a card REJECT; this is the same rule at fire time,
    because an arm can sit for up to max_arm_age_minutes and the card may have
    been armed from a scan that predates the earnings announcement date."""


def _fetch_earnings_date(symbol: str):
    from app.data.market import _calendar_dates_yf
    return _calendar_dates_yf(symbol)[0]


def _apply_event_veto(strategy) -> None:
    from app.scoring.stock_scorer import effective_event_window
    if strategy.horizon is None:
        raise EventVetoError("armed trade has no horizon; event window unknown (fail closed)")
    reject_days, _ = effective_event_window(strategy.horizon, None)
    try:
        earnings = _fetch_earnings_date(strategy.symbol)
    except Exception as exc:  # noqa: BLE001 -- unknown == scan's unknown (D4)
        logger.warning("Event veto: earnings lookup failed for %s: %s", strategy.symbol, exc)
        return
    if earnings is None:
        return
    days = (earnings - date.today()).days
    if 0 <= days < reject_days:
        raise EventVetoError(
            f"earnings in {days}d is inside the {strategy.horizon} reject window (<{reject_days}d)"
        )
```
Ensure `date` is imported in `auto_trader.py` (`from datetime import date`). Check the existing import line.

In `fire()`, immediately after the `_apply_vol_sizing` try/except chain ends:

```python
        try:
            _apply_event_veto(strategy)
        except EventVetoError as exc:
            with self._lock:
                self._state.history.append({
                    "attempt_id":      attempt_id,
                    "order_id":        None,
                    "status":          "event_veto_blocked",
                    "broker":          strategy.broker,
                    "symbol":          strategy.symbol,
                    "option":          strategy.option_symbol,
                    "timestamp":       datetime.now(timezone.utc).isoformat(),
                    "premium_at_risk": 0.0,
                    "error":           str(exc),
                })
            logger.error("AutoTrader fire REFUSED for %s %s — %s",
                         strategy.symbol, strategy.direction, exc)
            raise
```
Then find every reader of history statuses (`grep -rn "regime_headwind_blocked" backend frontend`) and add `event_veto_blocked` wherever `regime_headwind_blocked` is listed (status lists, alert wording, frontend status labels).

- [ ] **Step 4: Run tests**

```bash
./.venv/Scripts/python.exe -m pytest -q tests/test_auto_trader_event_veto.py tests/test_auto_trader.py tests/test_auto_trade.py
```

- [ ] **Step 5: Commit** — `fix(auto-trade): refuse a fire with earnings inside the reject window (review #3)`.

---

### Task 5: Step 7: the checklist reads the scan's window, and send is blocked on veto (fix #3, part 3, High)

**Files:**
- Modify: `frontend/app/(frame)/@contextRail/screener/step-7-trade-card/page.tsx:118-126`
- Modify: `frontend/app/(frame)/screener/step-7-trade-card/page.tsx` (disable Place Limit / Place Market / Pin-to-basket while `effectiveCard?.earningsVeto`)
- Test: the existing rail test (`grep -rln "Earnings > 7d away" frontend`), and the Step-7 page test

**Interfaces:**
- Consumes: `TradeCardData.earningsVeto` / `earningsUnknown` (Task 3); `useScanStore(s => s.scanResult?.event_window)`.

- [ ] **Step 1: Failing tests** in the rail's existing test file:

```tsx
it('judges earnings against the scan-echoed window, not 7/3 days', () => {
  // arrange: scanResult.event_window = { reject_days: 21, caution_days: 45 }, nextEventDays 10
  // assert: gate label 'Earnings outside reject window', status 'REJECT'
});
it('shows CAUTION when the scan echoed no window', () => { /* event_window undefined -> CAUTION, detail mentions re-running the scan */ });
it('shows CAUTION "Earnings date unknown" when earningsUnknown', () => { /* nextEventDays null, earningsUnknown true */ });
```
Write these with the arrange helpers the file already uses. Copy its existing `Earnings > 7d away` test's setup and change only the store state and the assertions above.

In the Step-7 page test: with `earningsVeto: true` on the active card, the Place Limit and Place Market buttons are `disabled` and a reason `Earnings inside the reject window — no send` is visible.

- [ ] **Step 2: Run and confirm failure** (`npm run test -- --testPathPattern=step-7`).

- [ ] **Step 3: Implement the rail**

```tsx
  // Fix #3: the scan's own window (echoed on the result), never a fixed 7/3d.
  const evWin = useScanStore((s) => s.scanResult?.event_window);
  const days = wlRow?.nextEventDays;
  if (candidate.earningsUnknown) {
    gates.push({ label: 'Earnings date', status: 'CAUTION',
      detail: 'No earnings date on file — check the calendar before sending.' });
  }
  if (days != null) {
    gates.push(evWin
      ? {
          label: 'Earnings outside reject window',
          status: days < evWin.reject_days ? 'REJECT' : days < evWin.caution_days ? 'CAUTION' : 'PASS',
          detail: `Next event in ${days}d — reject <${evWin.reject_days}d, caution <${evWin.caution_days}d (this scan's window).`,
        }
      : { label: 'Earnings outside reject window', status: 'CAUTION',
          detail: `Next event in ${days}d — this scan carried no event window; re-run the scan.` });
  }
```
If the gate-builder is a pure function rather than a component, pass `evWin` in as an argument from the component instead of calling the hook inside it.

- [ ] **Step 4: Implement the send block** in `step-7-trade-card/page.tsx`. Find the disabled conditions of the Place Limit / Place Market buttons and the pin toggle (`grep -n "disabled=" "frontend/app/(frame)/screener/step-7-trade-card/page.tsx"`), and OR in `effectiveCard?.earningsVeto === true`. Render the reason next to the buttons with `<Text size={11} tone="reject">`.

- [ ] **Step 5:** `npm run typecheck && npm run test -- --testPathPattern=step-7`, then commit: `fix(step-7): earnings gate uses the scan window; send blocked on veto (review #3)`.

---

### Task 6: Option size capped at the per-trade loss limit (fix #4, High)

**Files:**
- Modify: `backend/app/services/portfolio_risk.py:138-155`
- Modify: `frontend/lib/risk.ts:563` (mirror) and wherever `maxSingleTradeExposurePct` is assembled for options (`grep -rn "maxSingleTradeExposurePct" frontend/lib`)
- Modify: `backend/config/risk_rules.yaml` comment above `max_loss_per_trade_pct` (it is not in the header block, so this comment is lost on the next Settings save; mirror the rule in `SCORING_RULES.md` or the risk section of `docs/`)
- Test: `backend/tests/test_portfolio_risk_loss_cap.py` (new); `frontend/lib/__tests__/risk.test.ts` (append)

**Interfaces:**
- Produces: for options, `check_position_risk` shrinks `adjusted_size` to fit `min(max_single_position_pct, max_loss_per_trade_pct)`. When one contract does not fit, it returns the hard reason `single_trade_exposure_too_high`. Stocks are unchanged (they have a stop and their own caps).

- [ ] **Step 1: Failing test**

```python
# backend/tests/test_portfolio_risk_loss_cap.py
"""Fix #4: with no protective order a long option can lose 100% of premium,
so the premium cap must not exceed max_loss_per_trade_pct (3.75% < 5%)."""
from app.services import portfolio_risk as pr


def _cfg(monkeypatch, single=0.05, loss=0.0375):
    cfg = {
        "portfolio": {"max_total_exposure_pct": 0.25, "max_concurrent_positions": 10,
                      "max_daily_recommendations": 5, "max_same_symbol_positions": 1,
                      "min_portfolio_value": 5000.0, "max_single_position_pct": single,
                      "max_loss_per_trade_pct": loss},
        "sizing": {"max_contracts_per_trade": 50},
    }
    monkeypatch.setattr(pr, "_load_config", lambda: cfg)


def test_option_premium_clamped_to_loss_limit(monkeypatch):
    _cfg(monkeypatch)
    # $4.50 premium x 100 = $450/contract; 10 contracts = $4,500 = 4.5% of 100k
    r = pr.check_position_risk("AAPL", "AAPL|185|2026-11-20|C", 10, 4.50, 4.50, [], 100_000)
    assert r.adjusted_size == 8           # 8 x 450 = 3,600 <= 3,750
    assert "size_reduced_to_fit_exposure_limit" in r.reasons
    assert r.approved


def test_option_one_contract_over_loss_limit_refused(monkeypatch):
    _cfg(monkeypatch)
    r = pr.check_position_risk("AAPL", "AAPL|185|2026-11-20|C", 1, 40.0, 40.0, [], 100_000)
    assert not r.approved and "single_trade_exposure_too_high" in r.reasons


def test_stock_unaffected_by_option_loss_cap(monkeypatch):
    _cfg(monkeypatch)
    r = pr.check_position_risk("AAPL", "AAPL|STOCK", 100, 180.0, 180.0, [], 100_000)
    assert r.approved and r.adjusted_size is None
```

- [ ] **Step 2: Run and confirm failure** (the first test gets `adjusted_size is None`).

- [ ] **Step 3: Implement** (replace the `max_single = (...)` expression):

```python
    if is_stock:
        max_single = float(rules.get("max_single_stock_position_pct", STOCK_SINGLE_DEFAULT))
    else:
        # Fix #4 (decision D5): the auto-trader and the direct send place NO
        # protective order, so a long option's loss at worst is its whole
        # premium. The per-trade loss limit is therefore a premium cap too.
        max_single = min(
            float(rules["max_single_position_pct"]),
            float(rules.get("max_loss_per_trade_pct", rules["max_single_position_pct"])),
        )
```

Frontend `risk.ts`: where the options single-exposure limit is compared (line 563), compare against `Math.min(limits.maxSingleTradeExposurePct, limits.maxLossPerTradePct)` for option cards. Check the units first (`singleExposure` may be a percent while `maxLossPerTradePct` is a fraction). Read how `limits` is built and convert explicitly. Append a Jest case: `$4,500` premium on `$100,000` with `maxLossPerTradePct 0.0375` gives `single_trade_exposure_too_high`.

Also confirm the auto-trader fire's exposure check goes through `check_position_risk` (`grep -n "check_position_risk" backend/app/services/auto_trader.py`). If it does, the auto path is covered. If it does not, add a call there with the same test pattern.

- [ ] **Step 4: Run tests**

```bash
./.venv/Scripts/python.exe -m pytest -q tests/test_portfolio_risk_loss_cap.py tests/test_portfolio_risk_contract_cap.py tests/test_auto_trader.py
cd ../frontend && npm run typecheck && npm run test -- --testPathPattern=risk
```
Existing tests that assumed a 5% option cap with a 3.75% loss limit in config will now shrink. Update them only where the new number follows from D5, and list them in the commit body.

- [ ] **Step 5: Commit**: `fix(risk): option premium capped at max_loss_per_trade_pct (review #4)`.

---

### Task 7: Basket stops claiming it sent orders (fix #5, High)

**Files:**
- Modify: `frontend/components/organisms/SendToBrokerDialog/index.tsx` (remove the per-row "Auto-send" control; the title/blurb say "Track basket in Portfolio — no broker order is placed")
- Modify: `frontend/app/(frame)/screener/step-7-trade-card/page.tsx:189` (`source: 'manual'` always for basket rows), `:1353` (count), `:1680-1683` (toast text)
- Test: `SendToBrokerDialog` test and the Step-7 page test (`grep -rln "sent to broker" frontend`)

**Interfaces:**
- `DraftOrder.autoSend` is removed. Typecheck will list every reader. Each one is either deleted or made to treat the row as manual.

- [ ] **Step 1: Failing tests**
  - The dialog renders no "Auto-send" checkbox and shows the text `no broker order is placed`.
  - After a basket submit of 2 saved rows, the toast reads `2 added to Portfolio` and `No broker order was placed`, and the text `sent to broker` is absent.
  - Every `addPosition` call from the basket received `source: 'manual'`.

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement**
  - Dialog: drop `autoSend` from the row state and `DraftOrder`. Remove the checkbox and the auto/manual counter. Change the submit button label to `Add ${n} to Portfolio`.
  - Page: `source: 'manual',` with comment `// Fix #5: the basket places no broker order (D6); 'broker' made phantom positions count against real caps.` Replace `let auto = 0, manual = 0` with `let saved = 0` and the toast state `{ saved, queued, adjusted }`. Toast:

```tsx
<Text size={13} weight={500}>{toast.saved + toast.queued} added to Portfolio</Text>
<Text size={11} tone="caution">No broker order was placed — send each one from its card to trade it.</Text>
{toast.queued > 0 && <Text size={11} tone="secondary">{toast.queued} awaiting backend sync</Text>}
```
  - Rename the page's `sendLabel` for a non-empty basket to `` `Track basket (${basket.length})` ``.

- [ ] **Step 4:** `npm run typecheck && npm run test -- --testPathPattern="SendToBrokerDialog|step-7"`. Commit: `fix(step-7): basket is labelled and stored as tracked, not sent (review #5)`.

---

### Task 8: `pullback_ema` skips signals below 1R (fix #6, High)

**Files:**
- Modify: `backend/app/services/strategy_engine.py:403-520` (`pullback_ema_signal` gains `min_signal_rr: float = 0.0`)
- Modify: `backend/config/strategy_params.yaml` `pullback_ema.exit` (add `min_signal_rr: 1.0`; **superseded 2026-10-03: ships 0.0, see D7**)
- Test: `backend/tests/test_pullback_min_rr.py` (new)

**Interfaces:**
- `exit:` keys are merged into params by `run_strategy_backtest` (`get_exit`) and the live scan (`_merge_strategy_params`), so one YAML key reaches both. Grep the strategy-watch evaluator for `get_exit` too; if it does not merge `exit:`, the watch would still emit sub-1R signals, so add the merge there.

- [ ] **Step 1: Failing test**

```python
# backend/tests/test_pullback_min_rr.py
"""Fix #6: SPY pullback_ema median planned R/R was 0.11; 95% of signals < 1:1."""
import json
from pathlib import Path

from app.services.strategy_engine import pullback_ema_signal

BARS = json.loads((Path(__file__).parent / "fixtures" / "SPY_candles.json").read_text())
P = dict(ema_period=50, trend_ema=100, atr_stop_mult=1.5, rr_target_mult=2.0,
         tolerance=0.04, exit_swing_lookback=20)


def _signals(**extra):
    out = []
    for n in range(120, len(BARS) + 1):
        s = pullback_ema_signal(BARS[:n], direction="Bullish", **P, **extra)
        if s is not None:
            out.append(s)
    return out


def _rr(s):
    return abs(s.target_price - s.entry_price) / abs(s.entry_price - s.stop_price)


def test_default_unchanged():
    assert len(_signals()) == len(_signals(min_signal_rr=0.0))


def test_floor_drops_sub_1r_signals():
    base, floored = _signals(), _signals(min_signal_rr=1.0)
    assert len(floored) < len(base)
    assert all(_rr(s) >= 1.0 - 1e-9 for s in floored)
```
Check how the signal function takes bars (dicts with `open/high/low/close/volume`) against the fixture's keys. If they differ, map them the way `strategy_backtest._Strategy.next` does.

- [ ] **Step 2: Run and confirm failure** (`TypeError: unexpected keyword 'min_signal_rr'`).

- [ ] **Step 3: Implement.** Add `min_signal_rr: float = 0.0,` to the signature. After `target = targets[0]`:

```python
    # Fix #6 / D7: SKIP, never clamp. A first target nearer than min_signal_rr R
    # needs a >90% win rate to pay costs; clamping would invent a target the
    # strategy never claimed (Chair, TRADING_REVIEW.md).
    if min_signal_rr > 0 and abs(target - current) < min_signal_rr * risk:
        return None
```
Use the variable names the function actually uses for entry and risk (`current` and `risk` appear in the ladder call at lines ~498-503). YAML, under `pullback_ema.exit`:

```yaml
      min_signal_rr: 1.0   # review fix #6: skip signals whose first target is < 1R
```
(Superseded 2026-10-03, Task 10a: the key ships as `min_signal_rr: 0.0`, i.e. disabled — see D7.) `exit:` keys go through `adopt()` untouched, so a WFO adopt cannot drop it. That is the reason `rr_target_mult` also lives there.

- [ ] **Step 4: Measure and run tests**

```bash
./.venv/Scripts/python.exe -m pytest -q tests/test_pullback_min_rr.py tests/test_strategy_backtest.py tests/test_strategy_backtest_bearish.py tests/test_signal_confidence.py
```
Then re-run the SPY row from the review and paste the result into the commit body. No pass/fail threshold applies to this number. It is evidence for the re-review:
```bash
./.venv/Scripts/python.exe -c "import json;from app.services.strategy_backtest import run_strategy_backtest as r;b=json.load(open('tests/fixtures/SPY_candles.json'));print(r(b,strategy='pullback_ema',direction='Bullish',commission=0.002))"
```

- [ ] **Step 5: Commit**: `fix(strategy): pullback_ema skips signals whose first target is under 1R (review #6)`.

---

### Task 9: Full suite, adversarial round, state

- [ ] **Step 1: Full suites**

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest -q
cd ../frontend && npm run typecheck && npm run test
```
Expected: green. Report any failure with its output. Do not mark it done.

- [ ] **Step 2: Quant regression suite (the review's baseline of 94)**

```bash
cd backend && ./.venv/Scripts/python.exe -m pytest -q tests/test_confidence_cache.py tests/test_confidence_gate.py tests/test_confidence_gate_stocks.py tests/test_data_leakage.py tests/test_regime_no_lookahead.py tests/test_signal_confidence.py tests/test_strategy_backtest.py tests/test_strategy_backtest_bearish.py tests/test_walk_forward.py
```

- [ ] **Step 3: Adversarial audit loop.** Run the `k-adversarial-audit-loop` skill in audit-only mode on `git diff origin/main...HEAD`. Fix every finding, and repeat until a round comes back clean (CLAUDE.md rule).

- [ ] **Step 4: Project state.** Add a `TRADING-REVIEW-FIXES-A` entry to `docs/superpowers/PROJECT_STATE.json` with `verify` presence probes (`def normalize_direction` in `strategy_backtest.py`, `def slice_with_warmup` in `walk_forward.py`, `def _earnings_veto` in `routers/scan.py`, `class EventVetoError` in `auto_trader.py`, `min_signal_rr` in `strategy_engine.py`). Add decisions D1–D7 with today's date. Run `python3 scripts/state.py`.

- [ ] **Step 5:** Push, open a PR against `main`, and run `python3 scripts/claim.py release TRADING-REVIEW-FIXES`.

- [ ] **Step 6: Re-review.** Run `/k-trading-software-reviewer` in mode A to re-grade areas 2–4 against this branch.

---

## Phase B backlog (needs its own plan after Phase A merges)

| # | Sev | Fix | Files to start from | Depends on |
|---|---|---|---|---|
| 7 | Med | Server reads account value itself (YAML now, broker balance when live); one default; ignore the client's `portfolioValue` | `schemas/__init__.py:1019`, `routers/auto_trade.py:127`, `services/portfolio_risk.py`, `lib/portfolioStore.ts` | Task 6 (changes the cap's base) |
| 8 | Med | `_market_is_open` uses the session clock plus the quote's halt flag, checked **before** disarm | `services/auto_trader.py:418, 2316` | — |
| 9 | Med | Daily-loss gate persisted, covers manual sends, counts realised losses | `services/auto_trader.py` daily-loss section, `position_writer.py` | #7 |
| 10 | Med | Regime: fetch ≥ window bars; minimum transitions per row before publishing | `routers/scan.py:1659`, `services/regime_omm.py` | — |
| 11 | Med | Confidence replay de-overlapped by `n_days`; gate on expectancy in R | `scoring/signal_confidence.py`, `scoring_rules.yaml` | — |
| 12 | Med | Spreads: hard rules on each leg; R/R from net debit; hide Send until multi-leg routing exists | `scoring/spread_builder.py`, `scoring/contract_validator.py`, Step 7 | — |
| 13 | Med | Options target from ATR/structure, not a flat +8% | `risk_rules.yaml reward_risk`, `scoring/reward_risk.py`, `scan.py:1007-1028` | — |
| 14 | Med | Swing DTE floor `ceil(hold_max × multiplier × k)` | `scoring/dte_window.py:43-45` | — |
| 15 | Low | `summary_text` says `%`, not `$` | `services/strategy_backtest.py` summary line | — (could fold into Task 2) |
| 16 | Low | Remove or mark NOT READ: `enhanced_states`, `max_days_in_pullback`, `theta_caution_days` | `scoring_rules.yaml`, `config_health.py:127` | — |
| 5b | — | Route the basket through the direct-send path (save → order → classify) | Step 7 `placeLimitPaper` path | Task 7 |
| 6b | — | Re-tune all strategies with the fixed WFO on multi-year DB data | Settings → Strategy Tuning | Tasks 1, 2, 8 |
