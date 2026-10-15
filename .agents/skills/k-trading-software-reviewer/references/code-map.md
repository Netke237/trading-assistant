# Where things live, and how to gather evidence

This map was accurate when written. It is a guide to *where to look*, not the list of what to
review — that list is the coverage inventory below, built from what exists today. Line numbers
are never given on purpose: find them.

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

## Coverage inventory

Run from the repo root. It lists **every** source file of the running application — no keyword
or folder guessing, so nothing can fall through — with its line count, and flags credential
files. Everything it prints gets a Coverage row; nothing outside it is in scope. Excluded on
purpose: tests, test fixtures, `backend/app/fixtures/` (mock data, no live importer), data files
such as `backend/app/data/sp500.csv` (universe membership, maintained by a script — the code
that reads it is on the inventory), stories,
build caches and `__init__.py` files of five lines or
fewer (empty package markers; a larger one, like `schemas/__init__.py`, is listed).

```bash
{
find backend/app backend/config -type f \( -name '*.py' -o -name '*.yaml' \) \
     -not -path '*/__pycache__/*' -not -path '*/fixtures/*' \
  | while read f; do
      case "$f" in */__init__.py) [ "$(wc -l < "$f")" -gt 5 ] && echo "$f";; *) echo "$f";; esac
    done
find frontend/app frontend/components frontend/lib frontend/types -type f \( -name '*.ts' -o -name '*.tsx' \) \
  | grep -v -E '__tests__|testFixtures|\.test\.|\.stories\.'
} | sort -u | while read f; do
  case "$f" in
    *local_credentials*|*/settings.yaml|*credential*.yaml|*credential*.json|*/.env*) echo "  CRED  $f  (never open)";;
    *) printf '%6s  %s\n' "$(wc -l < "$f")" "$f";;
  esac
done
```

`services/credential_store.py` and `routers/credentials.py` are code, not secrets. They decide
which broker adapters exist and how keys are saved: read them in full like any other file, but never run
them or print any value they would load.

### Default area mapping

Paths: backend files are relative to `backend/app/`, except `config/*.yaml` (`backend/config/`); bare `.ts` names are under `frontend/lib/`; `components/…` and `app/…` are under `frontend/`.

A file may take several areas (write them all in the Area cell, e.g. `1, 4`). A parenthetical tag after a file *replaces* its row's area — `schemas/__init__.py` (3, 4, 5) is areas 3, 4, 5, not 1. A cap it triggers
applies to each. A file the table does not name is *in scope, area to be decided*: read its
file in the triage pass (SKILL.md step 2) and assign it. Never mark a file out of scope just because the table is silent.

| Area | Files (default assignment) |
|---|---|
| 1. Edge & strategy logic | `scoring/stock_scorer.py`, `scoring/fundamentals_scorer.py`, `scoring/entry_quality.py`, `services/strategy_engine.py`, `services/regime_gate.py` (1, 5 — also gates the auto-trader fire path), `services/regime_omm.py`, `services/regime_hmm.py`, `services/regime_hmm_daily.py`, `services/fundamentals_gate.py`, `services/market_structure.py`, `services/indicator_compute.py`, `services/strategy_watch_evaluator.py`, `services/composite_trigger_evaluator.py`, `routers/scan.py` (1, 3, 4, 5 — fires the armed auto-trader after a scan), `routers/stock_scan.py` (1, 2, 4), `routers/regime.py`, `schemas/__init__.py` (3, 4, 5 — spread defaults, portfolio value, qty, premium-stop bounds), `schemas/scan.py`, `schemas/stock_scan.py` (1, 4 — account size, risk %, strategy defaults), `data/augment.py`, `data/market.py` (1, 3 — quotes, IV), `config/strategy_watches.yaml` |
| 2. Statistical evidence | `scoring/signal_confidence.py`, `scoring/first_passage.py`, `services/strategy_backtest.py`, `services/walk_forward.py`, `services/strategy_param_optimizer.py`, `services/strategy_param_store.py`, `services/strategy_basket.py`, `services/picked_method.py`, `services/historical_store.py`, `data/confidence_cache.py`, `routers/strategy_tuning.py`, `config/strategy_params.yaml` |
| 3. Options & contract selection | `scoring/contract_validator.py`, `scoring/dte_window.py`, `scoring/spread_builder.py`, `scoring/reward_risk.py`, `scoring/reprice_horizon.py`, `scoring/trade_plan.py`, `scoring/exit_plan.py`, `scoring/structural_stop.py`, `scoring/stop_cost.py`, `models/heston.py`, `models/heston_cache.py`, `models/black_scholes.py`, `routers/contracts.py`, `data/option_symbol.py`, `data/tastytrade_iv.py`, `config/contract_rules.yaml` |
| 4. Risk parameters & sizing | `scoring/conviction_sizing.py`, `services/portfolio_risk.py`, `services/premium_stop.py`, `services/money_config.py`, `services/config_loader.py`, `services/config_health.py`, `routers/risk_settings.py`, `config.py`, `config/risk_rules.yaml`, `config/scoring_rules.yaml` (1, 3, 4 — scorer weights, vol and stop-premium rules, sizing ramp), `config/settings.example.yaml` (4, 5 — paper/live and broker switches), `models/portfolio.py`, frontend risk, settings and threshold modules (`risk.ts`, `riskStore.ts`, `settingsStore.ts`, `status.ts`, `confidenceText.ts`, `premiumStop.ts`, `executionParamDefaults.ts`, `scanParamsStore.ts`, `eventThresholdsStore.ts`, `ivThresholdsStore.ts`, `ivBasis.ts`, `regimeGateOverrides.ts`, `shortlistCap.ts`) |
| 5. Execution safety | `services/auto_trader.py`, `services/auto_trade_booking.py`, `services/broker_router.py`, `services/credential_store.py`, `routers/credentials.py` (read, never run), `services/position_writer.py`, `services/market_session.py`, `services/scan_window.py`, `services/portfolio_alert_monitor.py`, `services/regime_monitor.py`, `services/alert_*.py`, `services/notifications/*.py` (stop and alert delivery), `routers/auto_trade.py`, `routers/broker.py`, `routers/portfolio.py`, `data/governor.py`, broker adapters (`data/alpaca.py`, `data/alpaca_paper_execution.py`, `data/ibkr.py`, `data/ibkr_paper.py`, `data/tastytrade_bridge.py`, `data/tastytrade_session.py`, `data/tastytrade_paper.py`, `data/tradier_paper.py`, `data/tradier_stream.py`), `models/closed_position.py`, `main.py` (which monitors and schedulers actually start), frontend order paths (`directOrder.ts`, `paperTrade.ts`, `stockDirectSend.ts`, `autoTradeStore.ts`, `armBookingFields.ts`, `marketHours.ts`, `tradeCard*.ts`, `cardEdits.ts`, `components/organisms/AutoTradeArm/`, `components/organisms/StockAutoTradeArm/`, `components/organisms/SendToBrokerDialog/`, `components/organisms/TradeCard/`, `app/(frame)/screener/step-4-stocks/` (unattended after-scan execution), `app/(frame)/screener/step-7-*/`, `app/(frame)/@contextRail/screener/step-7-*/` (4, 5 — pre-trade checklist gates), `app/(frame)/portfolio/`) |

Usually *out of scope: no trading area* — **each with its own row**, and only after triage confirms it decides nothing in the SKILL.md rule 8 sense:
schedule stores and schedulers that only persist or trigger
jobs (`*_schedule_store.py`, `*_scheduler.py` — but check what each job does), EDGAR/S&P
universe maintenance, ORM models that only store data (`models/drawing.py`, `journal.py`,
`symbol_note.py`, `watchlist.py`, …), chart drawing and chart caches, news, symbol lookup,
UI-only routers, `database.py`.

## Configuration (the builder's parameters)

`backend/config/`: `risk_rules.yaml`, `scoring_rules.yaml`, `contract_rules.yaml`,
`strategy_params.yaml`, `strategy_watches.yaml`, `settings.example.yaml`.

For each value you judge, grep it across `backend/app` and `frontend/` — by its leaf name alone
when distinctive (`premium_stop_pct`), narrowed by parent block or loader call only when the
leaf is generic (`enabled`, `max`), plus the functions that receive a whole loaded block — to
confirm **which code reads it** and whether it is live (same rule as SKILL.md mode B). Every
application file the grep finds is already on the inventory; hits in tests, mocks (`__mocks__/`), `e2e/`, `backend/scripts/`, `frontend/scripts/` or root-level `frontend/*.ts` config files are not application code and are ignored. A value no code reads is dead config; a value read under a different name
than the YAML suggests is a bug.

## Intent and history

- `SCORING_RULES.md`, `PRD_HMM_Regime_Trading_Bot.md`, and the PRD files at repo root.
- `docs/superpowers/plans/*.md` — design decisions; comments in code and YAML cite them by
  decision ID (e.g. `STOCK-SENDS-...`, `DOCC-...`).
- Previous verdicts: `TRADING_REVIEW.md` (this skill), `TRADING_QUALITY_BENCHMARK.md`
  (predecessor), `PRODUCTION_READINESS_AUDIT.md`.

## Evidence commands

Run from `backend/`. Use the backend's own interpreter, not bare `pytest` (on some machines the
bare binary is an isolated tool interpreter that can't see the repo's dependencies). Each block
sets `PY` to `.venv/Scripts/python.exe` on Windows (where `python3` is usually a Microsoft Store
stub) or `.venv/bin/python` elsewhere, falling back to `python3` only when there is no `.venv`.

```bash
PY=$(ls .venv/Scripts/python.exe .venv/bin/python 2>/dev/null | head -1); PY=${PY:-python3}
"$PY" -m pip install -r requirements.txt   # only if imports fail

# Quant regression suite — run EVERY file the grep lists, not a hand-picked subset
"$PY" -m pytest -q $(ls tests/*.py | grep -i -e leak -e lookahead -e walk_forward \
  -e confidence -e strategy_backtest)
```

Real-data backtest over the committed fixtures (check `run_strategy_backtest`'s current
signature and the strategy names in `strategy_params.yaml` first; both change):

```bash
PY=$(ls .venv/Scripts/python.exe .venv/bin/python 2>/dev/null | head -1); PY=${PY:-python3}
"$PY" - <<'EOF'
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
