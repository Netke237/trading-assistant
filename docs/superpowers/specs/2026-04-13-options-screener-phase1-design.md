# Options Screener — Phase 1 Design Spec

**Date**: 2026-04-13
**Status**: Approved for implementation planning
**Scope**: Phase 1 — Stock Screener (on-demand scan, stock validation pipeline, ranked output)
**PRD reference**: PRD-02 Master Phased PRD — Options Screener and Recommendation Assistant v0.3

---

## 1. Product context

A local-first web application for a single discretionary swing options trader, with future extension to 20–50 users. The primary job of Phase 1 is to replace manual stock scanning with a repeatable, explainable validation pipeline that produces a ranked list of bullish candidates ready for option contract evaluation in Phase 2.

Phase 1 delivers no contract recommendation and no trade card. It ends at a validated, ranked stock list.

---

## 2. Phase roadmap

| Phase | Scope |
|---|---|
| **1 — Stock Screener** | Data layer, universe builder, market regime, stock setup validation, scoring, ranked output, Excel export |
| 2 — Contract Evaluation | Alpaca options chain, hard/soft rules, contract scoring, entry quality |
| 3 — Trade Card + Approval | Buy/sell plan, reward-risk, Heston pricing, human approval |
| 4 — Monitoring | Watchlist, portfolio, alerts, calendar |

---

## 3. Data sources

| Source | Purpose | Notes |
|---|---|---|
| **Tiingo** | Historical OHLCV, EOD prices, fundamentals | Free tier — REST API, API key required |
| **Alpaca** | Options chains, Greeks, live quotes | Free account — REST API, no local bridge needed. Phase 1 uses Alpaca for price quotes only; full options chain in Phase 2 |

**Error handling**: If either data source is unavailable at scan time, the scan is blocked entirely. The UI shows a clear error banner identifying which source failed and allows the user to retry. No partial results are produced.

---

## 4. Database

**PostgreSQL** running in Docker locally.

- Single Docker container, started with one command on Windows
- Managed via SQLAlchemy ORM in the backend
- Stores: scan results, ranked stock history, audit log, settings state, watchlist and portfolio state
- Schema designed to migrate to a cloud PostgreSQL instance (Railway, Render, Supabase) without changes for future multi-user deployment

---

## 5. Backend architecture

**Layered monolith** — single FastAPI application, split into domain folders.

```
backend/
├── app/
│   ├── data/
│   │   ├── tiingo.py        # historical prices, OHLCV fetch
│   │   ├── alpaca.py        # quotes (Phase 1), options chain (Phase 2+)
│   │   └── cache.py         # in-memory rate-limit buffer
│   ├── scanning/
│   │   ├── universe.py      # symbol list management
│   │   ├── regime.py        # market regime validation
│   │   ├── setup.py         # stock setup rules (trend, pullback, trigger)
│   │   └── scoring.py       # stock score + confidence index
│   ├── models/              # SQLAlchemy ORM models
│   ├── api/                 # FastAPI route files per domain
│   ├── config.py            # settings.yaml loader
│   └── main.py              # app entry point
├── tests/
│   ├── unit/                # per-module unit tests
│   └── integration/         # full scan pipeline dry-run tests
└── requirements.txt
```

Each module has one clear job and communicates through explicit function interfaces. Modules are independently testable. Phases 2–4 add new folders without restructuring what exists.

---

## 6. Frontend architecture

**Next.js** (existing scaffold). Styling approach deferred to implementation planning (Tailwind recommended).

### Layout: Trading Workbench (Layout B)

The application is a **decision pipeline workbench**, not a dashboard homepage. The interface answers three questions at all times: what should I review next, why is this candidate valid or invalid, and what is my next action.

#### Three zones

**Zone 1 — Top control bar** (fixed, always visible)
- Universe selector
- Direction mode (Bullish / Bearish)
- Analysis horizon (Swing 5–15d, etc.)
- Last run timestamp
- Run Scan button

**Zone 2 — Left candidate queue** (persistent, scrollable)
- Ranked symbols grouped by Pass / Caution / Reject
- Each row: symbol, score, confidence, per-stage status dots (Regime · Setup)
- Selected row highlighted with green left border
- Export to Excel button at bottom

**Zone 3 — Right decision workbench** (selected symbol, scrollable)
- Symbol header: name, price, change, overall badge, score/confidence/direction metadata
- Seven-stage gated pipeline (see Section 7)
- Action rail at bottom: Watchlist / Defer / Evaluate Contract

---

## 7. Validation pipeline — stage definitions

Each stage displays one of four explicit states: **PASS · CAUTION · FAIL · NOT RUN**

| Stage | Label | Phase 1 status | Content |
|---|---|---|---|
| 01 | Market Regime | Built in P1 | Summary text: SPY trend, VIX level, breadth |
| 02 | Stock Setup | Built in P1 | Rule badges (Trend / Pullback / Trigger) + price chart + diagnostic bullets |
| 03 | Volatility + Events | Built in P1 | IV Rank bar visual + event checklist |
| 04 | Option Contract | Phase 2 | Collapsed, locked: "available after stock validation" |
| 05 | Trade Card | Phase 3 | Collapsed, locked: "awaits contract selection" |
| 06 | Human Approval | Phase 3 | Collapsed, locked: "awaits trade card" |
| 07 | Monitoring + Alerts | Phase 4 | Collapsed, locked: "active after approval" |

**Locked stages** render as a single slim header row with no body. They show NOT RUN badge and an italic context hint explaining the dependency. They feel intentionally gated, not empty.

### Stage 02 — Stock Setup internal structure

Three-tier layout:
1. **Rule badges row** — Trend / Pullback / Trigger, each showing Pass / Caution / Fail
2. **Price chart** — candlestick (doubled height, ~200px), 50MA + 200MA overlays, pullback zone shading, volume strip below. Chart supports setup validation, not charting for its own sake. Indicators: price candles, 50MA, 200MA, volume. No RSI/MACD in this pane.
3. **Diagnostic bullets** — 2–4 short lines: "Above 50DMA — trend intact", "Pullback depth 4.2% — within range", "Trigger not yet confirmed"

### Stage 03 — Volatility + Events internal structure

- IV Rank bar (0–100 track with low/high threshold markers, fill coloured by zone)
- IV Rank numeric value + acceptability label
- Event checklist: earnings proximity, ex-dividend, user-flagged events

---

## 8. Scoring model (Phase 1)

### Stock score card

Produced after stock setup validation. Separate from any contract scoring (Phase 2).

Components:
- Stock trend rule result (Pass / Caution / Fail + metrics)
- Pullback rule result
- Reversal trigger rule result
- Event context result
- Volatility context result (at stock selection stage)
- Weighted stock score (0–100)
- Stock confidence index (High / Medium / Low)

All weights are stored in `config/settings.yaml` and may be overridden at scan time without overwriting saved defaults.

### Final status per symbol

- **Pass** — stock score above configured threshold, no hard-fail rules
- **Caution** — score near threshold or one soft-fail rule triggered
- **Fail** — one or more hard-fail rules triggered
- **Review Manually** — conflicting signals across rule groups; no automatic alert

---

## 9. Universe builder

Supports:
- Preset lists (S&P 500, NASDAQ 100, custom presets)
- Manual symbol entry
- CSV upload
- Mixed sources

Universe membership is independent from ranking logic. Universes can be saved and reused across scans.

---

## 10. Scan behaviour (Phase 1)

- **On-demand only** — user clicks Run Scan; continuous mode deferred to Phase 4
- **Scan states**: Idle → Scanning → Completed / Failed / Cancelled
- Scan state is visible in the UI at all times
- Each completed scan is timestamped and stored; results can be compared to previous run (rank change, score change, rule-status changes)
- If either data source (Tiingo or Alpaca) is unavailable, scan blocks with a clear error — no partial results

---

## 11. Settings and overrides

All numeric thresholds, rule weights, risk limits, and scan parameters live in `config/settings.yaml`. No business-rule magic numbers in code.

Key configurable items for Phase 1:
- Direction mode default
- Analysis horizon default
- Stock rule thresholds (trend, pullback, trigger)
- Confidence thresholds
- Tolerance percentages on score boundaries
- Scan cadence (future)
- Pagination size
- Export defaults

Execution-time overrides do not overwrite saved defaults unless the user explicitly saves them.

---

## 12. Export

Ranked stock table downloadable as Excel (.xlsx) from the candidate queue. Includes all columns defined in FR-12: symbol, direction, horizon, rank, rank change, score, score change, rule-status changes, confidence, status, reject/caution reasons, key rule summaries.

---

## 13. Error handling

| Scenario | Behaviour |
|---|---|
| Tiingo unavailable | Scan blocked — error banner, retry option |
| Alpaca unavailable | Scan blocked — error banner, retry option |
| Symbol missing OHLCV | Symbol flagged as data-incomplete, excluded from ranking, visible in output |
| Missing optional enrichment | Penalty applied or sub-score omitted; symbol not silently advantaged |
| Scan partially completed before failure | Cancelled state shown; no partial results persisted |

---

## 14. Testing

Unit and integration tests are included from the start (PRD FR-44).

**Unit tests** cover:
- Stock ranking logic
- Each validation rule (trend, pullback, trigger, regime, volatility, events)
- Score card generation
- Settings loader and override behaviour
- Missing-data handling

**Integration tests** cover:
- Full scan pipeline in dry-run mode (no live API calls)
- Reproducibility: same input + same settings → same ranked output
- Data-leakage checks: scoring uses only available-at-time data

Test framework: **pytest** (backend). Frontend testing deferred to Phase 2.

---

## 15. Non-functional requirements (Phase 1)

| Requirement | Implementation |
|---|---|
| NFR-01 Simplicity | Settings in one YAML file; UI has no hidden complexity |
| NFR-03 Resilience | Missing optional data does not crash scan or export |
| NFR-05 Exportability | Excel export from ranked table |
| NFR-06 Local run | Documented startup: Docker (PostgreSQL) + uvicorn + Next.js dev server |
| NFR-07 UI availability | All Phase 1 features accessible through Next.js UI |

---

## 16. Repository structure changes

Existing scaffold is retained and extended:

```
Trading assistant/
├── backend/
│   ├── app/               # extended per Section 5
│   └── tests/             # unit + integration
├── frontend/
│   └── app/               # extended with workbench layout
├── config/
│   └── settings.yaml      # extended with all Phase 1 thresholds
├── docs/
│   ├── architecture.md    # updated
│   └── superpowers/specs/ # this file
├── .github/workflows/     # CI — existing, extended with test run
└── docker-compose.yml     # new — PostgreSQL container
```

---

## 17. GitHub initialisation

The existing local repo is already git-initialised. Steps required:
1. Create remote repository on GitHub (private)
2. Push existing commits
3. Add `.superpowers/` to `.gitignore`
4. Verify CI workflow runs on push

---

*End of Phase 1 design spec.*
