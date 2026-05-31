# Change Requests — May 2026

**Source:** `change and corrections.docx` (user document)  
**Date:** 2026-05-13  
**Cross-referenced:** PRD-02 Master Phased PRD v0.3  
**Status:** Approved — awaiting implementation

---

## CR-01 — Move Market Regime to Step 1 of the workflow

**Type:** Workflow restructure (PRD FR-06 amendment)

**Problem:** The current workflow places Universe selection and Direction/Horizon before the regime check. The user needs to know market conditions first, then decide what to scan and which direction to take.

**Change:** Market Regime becomes Step 1. The new step order is:

| Step | Screen | Was |
|------|--------|-----|
| 1 | Market Regime | 3 |
| 2 | Universe | 1 |
| 3 | Direction + Horizon | 2 |
| 4 | Stock Ranking | 4 |
| 5 | Vol + Events | 5 |
| 6 | Contracts | 6 |
| 7 | Trade Card | 7 |

**PRD conflict:** FR-06 states the workflow "must remain unchanged." This CR formally amends that constraint. See PRD Appendix A for the amendment text.

---

## CR-02 — Direction + Horizon: execution-time filter overrides panel

**Type:** Feature enhancement (aligns with FR-04)

**Problem:** The large empty area below the horizon picker on Step 3 (formerly Step 2) is unused. Users have no way to view or override scoring parameters at scan time without going to Settings.

**Change:** Replace the empty area with an "Execution Parameters" panel. Each row shows the parameter name, the current default value (pulled from the selected horizon's config), and an editable override input. Overrides apply to the current scan only and never overwrite saved settings.

**Fields:**

| Parameter | Default source | Unit |
|-----------|---------------|------|
| IV Rank pass threshold | `scoring_rules.yaml → vol.iv_rank_pass_max` | 0–100 |
| IV Rank tolerance | new | % |
| RSI floor | `scoring_rules.yaml → trigger.rsi_floor` | 0–100 |
| RSI tolerance | new | % |
| MACD fast / slow / signal | `scoring_rules.yaml → trigger.macd_*` | integers |
| MACD tolerance | new | % |
| EMA condition (SMA50 > SMA200) | toggle — Swing and Position only | on/off |
| Max Delta | `contract_rules.yaml → hard_reject.max_delta` | 0.00–1.00 |
| Max candle body (ATR multiple) | `scoring_rules.yaml → pullback.atr_caution_max` | decimal |
| Candlestick lookback (bars) | `scoring_rules.yaml → pullback.swing_high_lookback_bars` | integer |
| Bid-ask spread ceiling | `contract_rules.yaml → hard_reject.max_bid_ask_spread_pct` | % |
| Event reject days | `scoring_rules.yaml → event.reject_days` | days |
| Event caution days | `scoring_rules.yaml → event.caution_days` | days |

**Custom horizon:** Borrows the nearest preset's scoring parameters (matched by max hold days). Only the DTE range differs. The panel shows the matched preset's defaults.

---

## CR-03 — Persistent scan log panel on the Direction + Horizon page

**Type:** New feature

**Problem:** After a scan there is no visible breakdown of what was rejected and why. Users cannot diagnose filter calibration problems without inspecting raw API responses.

**Change:** The lower section of Step 3 (Direction + Horizon) permanently hosts a scan log panel.

- **Before first scan:** Placeholder text — "No scan run yet."
- **After scan:** Full rejection log, stage analysis, and DTE recommendation. Persists across page navigation; resets only when a new scan starts.

**Minimum panel content:**
1. **Rejection breakdown table** — Reason → Count (e.g. "stock REJECT score 23 → 103")
2. **Stage summary** — e.g. "486 stocks rejected at stock scoring stage; 73 rejected at contract stage"
3. **DTE recommendation** — e.g. "For Swing 5–15d: target DTE 21–45d (2–3× your hold period to reduce theta drag)"

**Persistence:** Stored in `scanStore` alongside the existing scan result. Survives page navigation, cleared on next scan start.

---

## CR-04 — Dashboard: General Market News card

**Type:** New feature

**Problem:** The Dashboard has no general financial news feed. Users rely on external sources (Yahoo Finance, etc.) for macro context.

**Change:** Add a new "Market News" card to the Dashboard showing headlines for broad market proxy symbols (SPY, QQQ, VIX, DIA).

- Backend: reuse the existing `GET /api/news?symbols=SPY,QQQ,VIX,DIA` endpoint. No backend changes needed.
- Frontend: new `MarketNewsCard` organism on the dashboard page.
- This is a separate card from any existing watchlist or portfolio news cards.

---

## CR-05 — Universe selection: bug fixes and list cleanup

**Type:** Bug fix + minor change

**Bugs:**
1. **Watchlist bug:** Selecting "Watchlist" as the universe sends the literal string `"Watchlist"` to the backend, which treats it as an unknown ticker. Fix: expand to the actual list of starred symbols from `watchlistStore` before sending the scan request.
2. **Unavailable presets:** Russell 2000, STOXX 600, and DAX 40 are listed in the UI but cause hard scan errors (backend flags them as unavailable). Remove these three options from the universe picker.

**Addition:**
- Add SPY as a selectable single-symbol universe option.

---

## CR-06 — Dynamic universe list refresh (manual trigger)

**Type:** Feature

**Problem:** The S&P 500 list (`sp500.csv`, 640 symbols) and the NDX100 list (hardcoded in `universe_presets.py`) are never updated automatically. Both go stale every time an index rebalances.

**Change:** Add a "Refresh" button in the Universe selection step. On click:
- Fetches the current S&P 500 constituents from Wikipedia's machine-readable table (or equivalent public source).
- Fetches the current NDX100 from Nasdaq's published list.
- Overwrites `sp500.csv` and updates the in-memory NDX100 list.
- Shows a toast: "S&P 500 updated — 503 symbols" (or error if fetch fails).

**New backend route:** `POST /api/universe/refresh/{preset}` — fetches, validates, writes cache, returns updated count.

**Scope:** Manual trigger only. No auto-refresh on startup.

---

## CR-07 — Market regime hard gate when direction conflicts

**Type:** Feature — cross-step enforcement

**Problem:** The Market Regime page (`scanStore.regime`) currently has no connection to the scan execution path. A REJECT regime does not block or warn the user at scan time.

**Change:** When `scanStore.regime === 'REJECT'` and the selected direction conflicts with it (Bullish in a downtrend, or Bearish in an uptrend):

1. Show a persistent warning badge on the Direction+Horizon page header and on the RunScanButton.
2. When the user clicks RunScanButton: block and show a confirmation dialog — "Market regime is REJECT for a Bullish scan. Proceed anyway?" — with Cancel / Proceed options.

This mirrors the existing REJECT confirmation dialog already present on the old Step 3 (now Step 4). No backend changes needed — regime status is already in `scanStore`.

---

## PRD amendments required

| Clause | Change |
|--------|--------|
| FR-06 workflow order | Amend to: Regime → Universe → Direction → Stock → Vol/Events → Contracts → Trade Card |
| FR-06 "must remain unchanged" | Add footnote: step order amended by CR-01; the constraint now applies to steps 2–7 |
| FR-06 acceptance criteria | Add: "When regime = REJECT and direction conflicts, a confirmation gate is presented before scan execution" |
