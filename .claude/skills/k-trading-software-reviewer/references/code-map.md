# Where things live, and how to gather evidence

This map was accurate when written. **Verify every path before relying on it** (`ls`, `grep -n`),
and scan `backend/app/scoring/` and `backend/app/services/` for files not listed here — new
gates and sizing logic get added often. Line numbers are never given on purpose: find them.

## Coverage inventory

The list rule 8 is checked against: every tracked source and config file that can decide a
trade, one row each. Run from the repo root:

```bash
git ls-files backend/app backend/config frontend/app frontend/components frontend/lib frontend/types \
  | grep -E '\.(py|ts|tsx|yaml|yml|json)$' \
  | grep -vE '(__tests__/|\.test\.|\.spec\.|/tests?/|/fixtures/|__mocks__/)' \
  | while read -r f; do
      case "$f" in
        *local_credentials.yaml|*/settings.yaml|*credential*.yaml|*credential*.json|*/.env*)
          printf 'CREDENTIAL\t-\t%s\n' "$f" ;;   # never opened: row "not reviewed: credentials"
        *) printf 'FILE\t%s\t%s\n' "$(wc -l < "$f")" "$f" ;;
      esac
    done > /tmp/trading_review_inventory.tsv
# credential files are often untracked: list them by name only, never cat them
ls backend/config/settings.yaml backend/config/local_credentials.yaml backend/.env* 2>/dev/null \
  | sed 's/^/CREDENTIAL\t-\t/' >> /tmp/trading_review_inventory.tsv
awk -F'\t' '$1=="FILE"{n++; l+=$2} $1=="CREDENTIAL"{c++} END{print n" files / "l" lines; "c+0" credential files"}' \
  /tmp/trading_review_inventory.tsv
```

The count is what the scope question quotes ("<n> files / <n> lines"). Record `git rev-parse
--short HEAD` and `git status --short` in the report so a later PARTIAL continuation can tell
which files changed. Files the area table below names take that table's area by default; every
other file goes through triage (SKILL.md step 2).

## Code

| Area | Start here |
|---|---|
| Scan pipeline — what actually gets built and recommended (long options, spreads, stocks) | `backend/app/routers/scan.py`, `backend/app/routers/stock_scan.py` (also stock risk-budget sizing and the live backtest gate) |
| Holding horizons and the DTE window they imply | `frontend/lib/horizonPresets.ts`, `backend/app/scoring/dte_window.py` |
| Entry quality, market session / halts | `backend/app/scoring/entry_quality.py`, `backend/app/services/market_session.py` |
| Stock scoring (trend, pullback, trigger, event, vol) and the regime cap | `backend/app/scoring/stock_scorer.py` |
| Contract filtering and ranking | `backend/app/scoring/contract_validator.py`, `dte_window.py` |
| Multi-leg spreads | `backend/app/scoring/spread_builder.py` |
| Trade plan, R/R, targets, stops | `backend/app/scoring/trade_plan.py`, `reward_risk.py`, `exit_plan.py`, `structural_stop.py`, `stop_cost.py`, `reprice_horizon.py` |
| Probability of hitting targets (Monte Carlo) | `backend/app/scoring/first_passage.py` |
| Signal confidence (backtested gate) | `backend/app/scoring/signal_confidence.py` |
| Position sizing | `backend/app/scoring/conviction_sizing.py`, `backend/app/services/portfolio_risk.py` |
| Premium stop per position | `backend/app/services/premium_stop.py` |
| Regime detection and gating | `backend/app/services/regime_*.py` — find which model the live gate actually imports (`grep -rn "import.*regime_" backend/app/routers backend/app/services`); at last check the daily path used `regime_omm.py`, HMM only intraday |
| Fundamentals gate | `backend/app/services/fundamentals_gate.py` |
| Strategy signals | `backend/app/services/strategy_engine.py` |
| Backtest, walk-forward, optimizer | `backend/app/services/strategy_backtest.py`, `walk_forward.py`, `strategy_param_optimizer.py`, `strategy_basket.py`, `picked_method.py` |
| Strategy watches (live alerts from strategies) | `backend/app/services/strategy_watch_evaluator.py`, `backend/config/strategy_watches.yaml` |
| Auto-trader and order routing | `backend/app/services/auto_trader.py`, `auto_trade_booking.py`, `broker_router.py` |
| Risk settings writes, position sends | `backend/app/routers/risk_settings.py` (writes the YAML), `backend/app/services/position_writer.py` |
| Frontend risk logic (some limits live only here) | `frontend/lib/risk.ts`, `frontend/lib/riskStore.ts` |
| Frontend mirrors of thresholds (must match the YAML) | `frontend/lib/status.ts`, `frontend/lib/confidenceText.ts` |

## Configuration (the builder's parameters)

`backend/config/`: `risk_rules.yaml`, `scoring_rules.yaml`, `contract_rules.yaml`,
`strategy_params.yaml`, `strategy_watches.yaml`, `settings.example.yaml`.

For each value you judge, `grep -rn "<key>" backend/app` to confirm **which code reads it** and
whether it is live. A value no code reads is dead config; a value read under a different name
than the YAML suggests is a bug.

## Intent and history

- `SCORING_RULES.md`, `PRD_HMM_Regime_Trading_Bot.md`, and the PRD files at repo root.
- `docs/superpowers/plans/*.md` — design decisions; comments in code and YAML cite them by
  decision ID (e.g. `STOCK-SENDS-...`, `DOCC-...`).
- Previous verdicts: `TRADING_REVIEW.md` (this skill), `TRADING_QUALITY_BENCHMARK.md`
  (predecessor), `PRODUCTION_READINESS_AUDIT.md`.

## Evidence commands

Run from `backend/`. Use `python3 -m pytest`, not bare `pytest` (on some machines the bare
binary is an isolated tool interpreter that can't see the repo's dependencies).

```bash
pip install -r requirements.txt   # if imports fail

# Quant regression suite — run EVERY file the grep lists, not a hand-picked subset
python3 -m pytest -q $(ls tests/*.py | grep -i -e leak -e lookahead -e walk_forward \
  -e confidence -e strategy_backtest)
```

Real-data backtest over the committed fixtures (check `run_strategy_backtest`'s current
signature and the strategy names in `strategy_params.yaml` first; both change):

```bash
python3 - <<'EOF'
import json, glob, os
from app.services.strategy_backtest import run_strategy_backtest
from app.routers.stock_scan import _backtest_commission   # the cost the live gate charges
live_cost = _backtest_commission()
strategies = ["pullback_ema", "breakout_base", "ma_crossover",
              "mean_reversion_rsi", "mean_reversion_bb"]   # adjust to strategy_params.yaml
for path in sorted(glob.glob("tests/fixtures/*_candles.json")):
    sym = os.path.basename(path).split("_")[0]
    bars = json.load(open(path))
    for s in strategies:
        for d in ("Bullish", "Bearish"):   # capitalised, as the code compares them
            try:
                for label, c in (("gross", 0.0), ("net", live_cost)):
                    r = run_strategy_backtest(bars, strategy=s, direction=d, commission=c)
                    print(sym, s, d, label, len(bars), "bars", r)
            except Exception as e:
                print(sym, s, d, "ERROR", type(e).__name__, e)
EOF
```

Keep the engine's warnings (stderr): they are evidence for the Quant, not noise.

Report the real `n_trades`, win rate, expectancy, Sharpe and max drawdown per row. Intraday-only
strategies (e.g. VWAP mean reversion) are N/A on daily bars — label them, don't run them as if
meaningful. Compare the fixture's length (count the bars, read the first/last dates) with every
warm-up period and walk-forward window the config asks for; if the data can't support the
test, that is a finding about what this environment can prove, not a verdict on the strategy.

Also check `.github/workflows/*.yml`: does CI actually run the quant suite? A green badge only
means what the workflow says.
