# Frontend Storage Catalog & Ownership Matrix — Lane I

**Phase**: `APP-AUDIT-PERSISTENCE` (Issue #357)  
**Baseline**: `e5be63a1fa97b95c354f34075676281845bd6385`  
**Artifact**: `storage-matrix.json`

## Overview

Lane I has inventoried and verified all persistent, session, and ephemeral storage touchpoints across the frontend application. The inventory covers:
- **15 Zustand `persist` Stores**
- **6 Direct Browser Storage Call Sites** (`localStorage` / `sessionStorage`)
- **13 Ephemeral / In-Memory / API-Synchronized Stores**

---

## 1. Zustand Persist Stores

| Store File | Storage Key | Key Style | Version | Storage Engine | Partialize Filter | Migration Handler |
|---|---|---|---|---|---|---|
| `alertStore.ts` | `bamendjou-alerts-v2` | legacy-hyphen | 3 | `localStorage` | toasts, config, suppressedAlerts, firedAlerts | `migrateAlerts`: v0..v2 -> v3 backfills `STRUCTURAL_STOP_BREACHED` |
| `autoTradeStore.ts` | `bamendjou-auto-trade` | legacy-hyphen | 2 | `localStorage` | selectedBroker, autoMode (demotes `armed` to `manual`) | Inline: v1 -> v2 normalizes selectedBroker and mode |
| `chartAlertStore.ts` | `bamendjou:alerts` | colon | 2 | `localStorage` | rules, history | `migrateChartAlerts`: v1 -> v2 operators & channels |
| `chartStore.ts` | `bamendjou:chart` | colon | 2 | `localStorage` | symbol, symbolName, interval, chartType, indicators, paneLayout | `migrateChartStore`: v0/v1 -> v2 defaults & interval |
| `drawingStore.ts` | `bamendjou:drawings` | colon | 1 | `localStorage` | drawings | `migrateDrawings`: v0 -> v1 sanitizes coordinates |
| `portfolioStore.ts` | `bamendjou-portfolio-v1` | legacy-hyphen | 7 | `localStorage` | positions | `migratePortfolioPersist`: stop flooring, `premiumStopPct`, `holdMaxDays` (deduping in `merge()`) |
| `riskStore.ts` | `bamendjou-risk-v1` | legacy-hyphen | 4 | `localStorage` | limits, dailyRecommendations, lastResetDate, symbols, portfolioValueUpdatedAt | `migrateRisk`: v3 -> v4 bounds exposure percentages |
| `scanParamsStore.ts` | `bamendjou:scan-params` | colon | 12 | `localStorage` | All fields (no partialize filter) | Inline: v11 -> v12 strategy overrides and win rates |
| `scanStore.ts` | `bamendjou-scan-store` | legacy-hyphen | 19 | `localStorage` | Results, previousRun, context, duration, picks, states, cardEdits (ephemeral limit prices evicted) | Inline: v18 -> v19 stamps; v<10 horizon preset |
| `searchProfilesStore.ts` | `bamendjou:search-profiles` | colon | 5 | `localStorage` | profiles, legacyTargetPctDropped | Inline: v4 -> v5 normalizes target profit percentages |
| `settingsStore.ts` | `bamendjou-settings` | legacy-hyphen | 24 | `localStorage` | broker, alertDeduplicationHours, markov, gates, limits, paper credentials, spreads, scheduleConfig | `migrateSettings`: v0..v23 -> v24 timezone, broker endpoints |
| `structureStore.ts` | `bamendjou:structure` | colon | 2 | `localStorage` | visibility, structureVisible | Inline: v1 -> v2 swing visibility flags |
| `theme.ts` | `bamendjou:theme` | colon | 1 | `localStorage` | theme ('dark' \| 'light') | Inline: v0 -> v1 defaults to 'dark' |
| `watchedContractsStore.ts` | `bamendjou-watched-contracts-v1` | legacy-hyphen | 3 | `localStorage` | ids, grading | `migrateWatchedContracts`: v1/v2 -> v3 initializes grading map |
| `watchlistStore.ts` | `bamendjou-watchlist-v1` | legacy-hyphen | 1 | `localStorage` | added | `migrateWatchlist`: v0 -> v1 uppercases and trims symbols |

---

## 2. Direct Storage Call Sites

1. **`frontend/app/layout.tsx:53`**:
   - `localStorage.getItem('bamendjou:theme')`
   - Executed inline before React hydrates to prevent theme flash (FOUC).
2. **`frontend/app/(frame)/dashboard/page.tsx:111,118`**:
   - `localStorage.getItem('bamendjou:showEarnings')` / `setItem('bamendjou:showEarnings', ...)`
   - Toggles visibility of upcoming earnings events on the dashboard.
3. **`frontend/app/(frame)/settings/page.tsx:2688-2689`**:
   - `sessionStorage.getItem('bamendjou:wfo:jobId')` / `setItem('bamendjou:wfo:jobId', ...)`
   - `sessionStorage.getItem('bamendjou:wfo:adopted')` / `setItem('bamendjou:wfo:adopted', ...)`
   - Stores active WFO tuning job ID and JSON array of adopted strategy names (`Set<string>`) during walk-forward optimization runs.
4. **`frontend/components/molecules/CollapsibleSection/index.tsx:49,64`**:
   - Production caller keys in `localStorage`:
     - `bamendjou:tradecard-scores-collapsed` (`TradeCard/index.tsx:2388`)
     - `bamendjou:tradecard-ladder-collapsed` (`TradeCard/index.tsx:2422`)
     - `bamendjou:tradecard:${qualification.kind}:scoring-evidence:collapsed` (`ScoreCardPanel/index.tsx:108`)
5. **`frontend/lib/audit.ts:15,33,50`**:
   - `localStorage.getItem('bamendjou-audit-log')` / `setItem('bamendjou-audit-log', ...)`
   - FIFO audit log of sensitive trader actions (`APPROVE`, `REJECT`, `SUBMIT`, `CLOSE`) with automatic eviction of oldest 100 entries upon `QuotaExceededError`.
6. **`frontend/lib/chartAlertStore.ts:141,175`**:
   - `localStorage.getItem('bamendjou:alert-tombstones')` / `setItem('bamendjou:alert-tombstones', ...)`
   - Stores tombstone IDs of deleted chart alerts to prevent them from resurrecting on server re-sync.

---

## 3. Ephemeral / In-Memory Stores

The following stores do not write to browser storage and are reset on page reload:
- `universeStore.ts`: Current universe selection and custom tickers
- `tradeCardUiStore.ts`: Active TradeCard tab and modal state
- `portfolioUiStore.ts`: Portfolio table sort/filter and drawer open state
- `watchlistUiStore.ts`: Watchlist table sort and filter state
- `configHealthStore.ts`: Backend configuration validation health report
- `directSendNotesStore.ts`: Ephemeral broker send order note drafts
- `journalStore.ts`: Synchronized directly with backend `/api/journal` endpoints
- `notesStore.ts`: Synchronized directly with backend `/api/notes` endpoints
- `analysisStore.ts`: Single-symbol analysis result cache
- `eventThresholdsStore.ts`: Per-horizon event proximity reject/caution windows fetched at start
- `ivThresholdsStore.ts`: Per-horizon IV rank thresholds fetched at start
- `performanceStore.ts`: Backend-calculated portfolio performance history
- `strategyProfilesStore.ts`: Transient strategy parameter tuning drafts in Settings

---

## 4. Verification & Testing

All migrations, corruption fallbacks, quota handling, and rehydration alignments are verified by the automated test suite in `frontend/lib/__tests__/auditPersistence.test.ts` (18 passing assertions).
