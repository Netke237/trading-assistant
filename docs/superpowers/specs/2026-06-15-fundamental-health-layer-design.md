# Design — Fundamental Health Layer

Date: 2026-06-15
Status: Draft for review
Author: Kenneth + Claude

Add company financial-health data (fundamentals) to Bamendjou as a new scoring
layer. It produces a **Fundamental Health 0–100** score plus plain-English labels,
shows them on every stock and options card, and acts as a **demote-only gate** that
can lower a candidate's PASS/CAUTION/REJECT verdict but never raise it.

The layer reuses two patterns Bamendjou already trusts:
- the **confidence gate** (a demote-only `RuleResult` appended inside `score_stock`), and
- the **historical store** (DB-first cache that fetches only the stale delta).

---

## 1. Decisions (locked)

| # | Decision | Choice |
|---|---|---|
| 1 | Influence level | **Soft gate + score.** Show the score; let it demote status; hard-reject only on dangerous balance sheets. Gate thresholds **user-adjustable in Settings** (see 5.2), like the confidence gate. |
| 2 | Scope | **Stock scan AND options scan**, horizons **Swing + Position only**. Intraday skips fundamentals entirely. |
| 3 | Bearish behavior | **Display + safety reject only.** Weak fundamentals never demote a bearish (put/short) candidate; the hard safety reject still applies. |
| 4 | Data source | **SEC EDGAR CompanyFacts** from the start (free, no API key). US-only; non-US symbols → "no data", gate is a no-op. |
| 5 | Storage | New `fundamentals` table + `fundamentals_store.py`, mirroring `historical_store.py`. Snapshots keyed by filing date (point-in-time ready). |

---

## 2. Why this is a small change

Both scan pipelines funnel through one function, `score_stock()`
(`backend/app/scoring/stock_scorer.py`):
- options scan: `backend/app/routers/scan.py:276` (pre-screen) and `:333` (final)
- stock scan:   `backend/app/routers/stock_scan.py:121`

So the gate is added **once**, inside `score_stock`, exactly like the existing
`confidence` / `confidence_gate` arguments — and it lights up in both scans.

---

## 3. Data layer — SEC EDGAR

### 3.1 Ticker → CIK mapping
EDGAR keys everything by CIK, not ticker. Fetch `https://www.sec.gov/files/company_tickers.json`
once, cache it (in-process + a small DB table or JSON file), refresh weekly. Map
`symbol → 10-digit zero-padded CIK`. A symbol with no CIK is non-US/unmapped →
fundamentals unavailable (see 3.5).

### 3.2 CompanyFacts fetch
`https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`

Requirements:
- **User-Agent header is mandatory** per SEC fair-access policy. Format:
  `"Bamendjou/1.0 (lenetke@googlemail.com)"`. Store the contact string in
  `settings.yaml` so it is configurable.
- Respect ~10 req/s ceiling. Fetches happen in the background prefetch, not the
  scan hot-path, so concurrency is low anyway.

### 3.3 Concept mapping (us-gaap → MVP-8)
Each metric maps to one or more us-gaap concepts, with fallbacks (taxonomy varies
by filer). Use the most recent annual (FY) value and the year-ago value to derive
YoY growth.

| MVP field | Primary us-gaap concept(s) | Notes / fallback |
|---|---|---|
| Revenue (for growth) | `RevenueFromContractWithCustomerExcludingAssessedTax` | fallback `Revenues`, `SalesRevenueNet` |
| Net income | `NetIncomeLoss` | — |
| EPS (for growth) | `EarningsPerShareDiluted` | fallback `EarningsPerShareBasic` |
| Gross margin | `GrossProfit` ÷ revenue | if `GrossProfit` absent, `revenue − CostOfRevenue` |
| Operating margin | `OperatingIncomeLoss` ÷ revenue | — |
| Free cash flow | `NetCashProvidedByUsedInOperatingActivities` − `PaymentsToAcquirePropertyPlantAndEquipment` | capex may be 0/absent → FCF = OCF |
| Debt / equity | (`LongTermDebtNoncurrent` + `LongTermDebtCurrent`) ÷ `StockholdersEquity` | fallback total `Liabilities` ÷ equity |
| Current ratio | `AssetsCurrent` ÷ `LiabilitiesCurrent` | — |
| Share-count growth | `WeightedAverageNumberOfDilutedSharesOutstanding` | YoY; fallback `CommonStockSharesOutstanding` |
| (Safety) Stockholders' equity | `StockholdersEquity` | used for negative-equity reject |

Each value carries its filing `end` date and `filed` date so snapshots are
point-in-time.

### 3.4 Storage — `fundamentals` table + `fundamentals_store.py`
New SQLAlchemy model `backend/app/models/fundamentals.py`, table `fundamentals`,
composite PK `(symbol, fiscal_period_end)`:

```
symbol            String(10)   PK
fiscal_period_end Date         PK     # the reporting period end
filed_date        Date                # when the filing hit EDGAR (point-in-time)
cik               String(12)
revenue           Numeric  (nullable)
net_income        Numeric  (nullable)
eps_diluted       Numeric  (nullable)
gross_profit      Numeric  (nullable)
operating_income  Numeric  (nullable)
op_cash_flow      Numeric  (nullable)
capex             Numeric  (nullable)
total_debt        Numeric  (nullable)
stockholders_eq   Numeric  (nullable)
current_assets    Numeric  (nullable)
current_liab      Numeric  (nullable)
shares_diluted    Numeric  (nullable)
source            String(20)          # "sec_edgar"
fetched_at        DateTime
```

`fundamentals_store.py` public API (mirrors `historical_store.py`):
- `get_fundamentals(symbol) -> FundamentalsSnapshot | None`
  DB-first; if the latest stored filing is older than the staleness window
  (default 90 days) OR no rows exist, fetch CompanyFacts, upsert all periods,
  return the most recent valid snapshot. Returns `None` for unmapped symbols.
- `prefetch_universe(symbols)` — background, rate-limited, idempotent upsert.
- `get_prefetch_status()` — progress dict, same shape as the OHLCV prefetch.

`FundamentalsSnapshot` is a dataclass holding the raw fields above **plus** the
derived metrics (revenue_growth_yoy, eps_growth_yoy, gross_margin,
operating_margin, fcf, debt_to_equity, current_ratio, share_growth_yoy).

### 3.5 Coverage gaps (never break a scan)
- Unmapped symbol (no CIK), fetch failure, or missing required concepts →
  `get_fundamentals` returns `None`.
- `None` → no fundamentals block on the card, and the gate is a **no-op**
  (status unchanged). Logged, never raised.
- Optional future fallback: yfinance for non-US coverage (out of scope for v1).

---

## 4. Scoring — `scoring/fundamentals_scorer.py`

Pure function, no I/O, fully unit-testable:

```python
score_fundamentals(snap: FundamentalsSnapshot, direction: Direction) -> FundamentalHealth
```

### 4.1 Three buckets → one score
Each derived metric → a 0–100 sub-score via thresholds in `scoring_rules.yaml`
(winsorized; no peer/sector ranking in v1 — absolute thresholds, simplest first).

- **Growth** (revenue growth YoY, EPS growth YoY)
- **Quality** (gross margin, operating margin, FCF > 0 / FCF margin)
- **Risk** (debt/equity, current ratio, share-count growth — inverted: dilution hurts)

```
HealthScore = round(0.35·Growth + 0.35·Quality + 0.30·Risk)
```
(weights in YAML, tunable). Direction does **not** change the score itself — only
the gate's reaction to it (section 5).

### 4.2 Output — `FundamentalHealth`
```
score:            int          # 0–100
quality_label:    "Strong" | "Neutral" | "Weak"
risk_label:       "Low" | "Medium" | "High"
growth_score:     int
quality_score:    int
risk_score:       int
safety_flags:     list[str]    # e.g. ["negative_equity"], ["extreme_leverage"]
detail:           dict         # raw + derived values for UI explainability
```

`safety_flags` non-empty drives the hard reject in section 5.

---

## 5. The gate — inside `score_stock`

`score_stock()` gains two optional args, used **only when horizon ∈ {Swing, Position}**:
`fundamentals: FundamentalHealth | None`, `fundamentals_gate: dict | None`.

Behavior (after the weighted score + confidence cap are computed):

1. If `fundamentals is None` or horizon is Intraday → do nothing.
2. Append a `RuleResult(name="fundamentals", status, score=health.score, detail=...)`.
   (Mirrors how the confidence `RuleResult` is appended.)
3. **Hard safety reject (both directions):** if `safety_flags` is non-empty,
   `final_status = _worse(final_status, "REJECT")`.
4. **Soft demote (Bullish only):**
   - `health.score < cautionBelow` → cap at CAUTION
   - `health.score < rejectBelow`  → cap at REJECT
5. **Bearish:** skip step 4 entirely (display + safety reject only).

The gate is **demote-only** — it uses the existing `_worse()` helper and never
raises status. The base 0–100 score is untouched (fundamentals are a separate
`RuleResult`, not folded into the weighted sum) — keeping the technical score clean.

### 5.1 Config — `scoring_rules.yaml` (defaults)
```yaml
fundamentals_gate:
  enabled: true
  cautionBelow: 45      # health < 45 → cap at CAUTION (bullish only)
  rejectBelow: 30       # health < 30 → cap at REJECT  (bullish only)
  safety:
    reject_on_negative_equity: true
    debt_to_equity_reject: 3.0      # ≥ this → safety reject (both directions)
  staleness_days: 90
  weights: { growth: 0.35, quality: 0.35, risk: 0.30 }
  thresholds:
    revenue_growth_yoy:  { strong: 0.15, weak: 0.0 }
    eps_growth_yoy:      { strong: 0.15, weak: 0.0 }
    gross_margin:        { strong: 0.40, weak: 0.20 }
    operating_margin:    { strong: 0.15, weak: 0.0 }
    debt_to_equity:      { strong: 0.5,  weak: 2.0 }   # lower is better
    current_ratio:       { strong: 2.0,  weak: 1.0 }
    share_growth_yoy:    { strong: 0.0,  weak: 0.03 }  # lower is better
```
These are **defaults only**. They are overridable per-scan from Settings — see 5.2.
Only active for Swing/Position via the same per-horizon wiring already in the file.

### 5.2 User-adjustable thresholds (Settings) — mirrors the confidence gate
The fundamentals gate is adjustable in the UI through the **exact mechanism the
confidence gate already uses**:

YAML default → `settingsStore.fundamentalsGate` → per-horizon editable params
(Step 3) → `RunScanButton` injects into the scan request `filters` →
`_resolve_fundamentals_gate(req)` merges request-over-YAML in the backend.

Adjustable in Settings (the same three "levers" pattern as confidence, plus the
one safety knob):

| Setting | Maps to | Range |
|---|---|---|
| Fundamentals enabled | `fundamentals_enabled` | on/off (off → gate no-op) |
| Health caution below | `fundamentals_caution_below` | 0–100 (%) |
| Health reject below | `fundamentals_reject_below` | 0–100 (%) |
| Debt/equity safety reject | `fundamentals_de_reject` | 0–10 |

Backend wiring (parallels `_resolve_gate` at `scan.py:108`):
```python
def _resolve_fundamentals_gate(req) -> dict:
    g = dict(load_fundamentals_gate_cfg())     # YAML default
    if req.fundamentals_enabled is not None:        g["enabled"]      = req.fundamentals_enabled
    if req.fundamentals_caution_below is not None:   g["cautionBelow"] = req.fundamentals_caution_below
    if req.fundamentals_reject_below is not None:    g["rejectBelow"]  = req.fundamentals_reject_below
    if req.fundamentals_de_reject is not None:       g["safety"]["debt_to_equity_reject"] = req.fundamentals_de_reject
    return g
```
When `enabled` is false the gate is a full no-op (the score still displays).

The **per-metric strong/weak thresholds** (the `thresholds:` block) stay in YAML
by default but are surfaced read-only on the preset horizon tabs and **editable on
the Custom tab**, exactly like `customParams` works today for the technical rules.

---

## 6. Wiring the routers

### 6.1 Options scan (`scan.py`)
- Resolve the gate once per scan via `_resolve_fundamentals_gate(req)` (5.2).
- Batch-load fundamentals for the universe alongside the existing `bars_map`
  prefetch (`get_fundamentals` is DB-first, so this is cheap after first warm-up).
- Pass `fundamentals=` + `fundamentals_gate=` into **both** `score_stock` calls
  (pre-screen `:276` and final `:333`). Pre-screen gating means fundamentally
  unsafe names are dropped *before* the expensive option-chain fetch — a perf win.
- Add a `fundamentals` block to `TradeCardData`.

### 6.2 Stock scan (`stock_scan.py`)
- Resolve the gate once per scan (same helper, shared).
- Fetch fundamentals inside `_process_stock` (or batch in `run_stock_scan`).
- Pass into the single `score_stock` call at `:121`.
- Add a `fundamentals` block to `PositionCardOut`.

### 6.3 Background prefetch
Add a `fundamentals_store.prefetch_universe` call wherever the OHLCV prefetch is
kicked off, so the table is warm before the first scan. Rate-limited, runs once
then served from DB for the staleness window.

---

## 7. Schemas + frontend

### 7.1 Backend schemas
New shared model `FundamentalsOut` (score, quality_label, risk_label,
growth_score, quality_score, risk_score, safety_flags, + the raw/derived detail):
- `PositionCardOut.fundamentals: FundamentalsOut | None`
  (`backend/app/schemas/stock_scan.py`)
- `TradeCardData.fundamentals: FundamentalsOut | None` (options `schemas`)

New gate-threshold fields on **both** request models (`ScanRequest` and
`StockScanRequest`), all optional so existing callers/tests are unaffected — they
parallel the existing `confidence_caution_below` / `confidence_reject_below`:
```
fundamentals_enabled:       Optional[bool]
fundamentals_caution_below: Optional[float]
fundamentals_reject_below:  Optional[float]
fundamentals_de_reject:     Optional[float]
```

### 7.2 Frontend
- `settingsStore.ts`: add a persisted `fundamentalsGate`
  `{ enabled, cautionBelow, rejectBelow, deReject }` (bump the store `version` +
  add a `migrate` branch, per the project's Zustand persistence rule).
- Step-3 per-horizon params (`step-3-direction/page.tsx`): add the fundamentals
  threshold rows under a new **"Fundamentals"** subGroup, for **Swing + Position**
  defaults only (Intraday omits them).
- `RunScanButton` (`index.tsx`): inject the resolved fundamentals thresholds into
  the scan request `filters`, mirroring the confidence block at `:134-145`
  (including the `enabled === false → 0 / no-op` path).
- `api.ts`: extend the `filters` type with the four `fundamentals_*` fields.
- `StockPositionCard` (`frontend/components/organisms/StockPositionCard/`): add a
  "Fundamental Health" section — the 0–100 score, the two labels, and the three
  bucket scores, styled like the existing score breakdown (color-mix tints, no
  card shadow, border-subtle).
- Options `TradeCard`: same section.
- Stock-scan results table (Step 4 stocks): add a sortable **Health** column.
- Show "—" / "No data" gracefully when `fundamentals` is `null`.
- Settings → Score weights & parameters: the gate levers (enabled / caution /
  reject / D-E safety) plus the per-metric strong/weak thresholds (read-only on
  preset tabs, editable on Custom), Swing/Position only.

---

## 8. Build order

**Phase 1 — Data + score (no UI, fully tested)**
1. `models/fundamentals.py` + Alembic migration for the `fundamentals` table.
2. EDGAR client: ticker→CIK map, CompanyFacts fetch, concept mapping → snapshot.
3. `fundamentals_store.py` (get / prefetch / status) with the staleness logic.
4. `scoring/fundamentals_scorer.py` + `scoring_rules.yaml` block.
5. Unit tests: concept mapping (fixture JSON), scorer thresholds, gate behavior
   (bullish demote, bearish no-demote, safety reject both directions, None no-op).

**Phase 2 — Engine + routers**
6. Add `fundamentals` / `fundamentals_gate` args to `score_stock` + the gate logic.
7. Wire both routers + schemas. Add prefetch to startup.

**Phase 3 — UI + adjustable thresholds**
8. `settingsStore.fundamentalsGate` (+ version bump/migrate), Step-3 param rows,
   `RunScanButton` filter injection, `api.ts` filter type, `_resolve_fundamentals_gate`.
9. `FundamentalsOut` rendering in both cards + sortable Health column + Settings
   per-metric threshold editing (Custom tab).

**Phase 4 — Later (optional)**
10. Sector-relative percentile ranking instead of absolute thresholds.
11. Point-in-time fundamental backtests (filing-date snapshots already stored).
12. yfinance fallback for non-US coverage.

---

## 9. Out of scope (v1)
- Intraday fundamentals (skipped by design).
- Sector/peer-relative ranking (absolute thresholds first).
- Earnings-surprise / beat-streak scoring (needs a consensus-estimate source).
- Non-US coverage.
- Folding fundamentals into the base 0–100 technical score.

## 10. Risks / watch-items
- **EDGAR taxonomy messiness:** concept names vary by filer. Mitigation: fallback
  chains per metric + "no data → no-op" so gaps degrade gracefully, never crash.
- **User-Agent compliance:** missing/!descriptive UA gets the IP throttled by SEC.
  Mitigation: mandatory configurable contact string, low concurrency.
- **Staleness vs freshness:** 90-day window means a card may show last quarter's
  filing. Acceptable — fundamentals are slow-moving by nature; filing date is shown.
