# APP-AUDIT-INVENTORY source index

Source baseline `00b4ab54069e2a43e0a66cd1f183f5fa2347f336`. Generated with TypeScript AST, import resolution and independent Git-tree route census. Read `provenance.json` for exact input hashes and tool versions.

**Execution classification recorded:** semantic-classification.json and reconciliation.json distinguish source capabilities, actual fixture observations and pending domain correctness. Independent final evidence review remains pending. This report does not certify displayed numbers, orders or persistence. No exclusion is user-approved.

## Counts (distinct units)

```json
{
  "source_route_entry_files": 45,
  "entry_classifications": {
    "error-boundary": 1,
    "layout": 4,
    "loading-boundary": 1,
    "not-found-boundary": 1,
    "parallel-slot-fallback": 4,
    "parallel-slot-page": 6,
    "private-folder-source": 1,
    "redirect": 3,
    "url-page": 24
  },
  "entry_file_kinds": {
    "default": 4,
    "error": 1,
    "layout": 4,
    "loading": 1,
    "not-found": 1,
    "page": 34
  },
  "reachable_source_modules": 299,
  "component_definitions": 283,
  "component_route_requirement_instances": 2269,
  "jsx_custom_component_calls": 2813,
  "native_surface_candidates": 979,
  "native_route_requirement_instances_normalized": 2900,
  "state_rows_normalized": 9,
  "component_state_requirement_ids": 20421,
  "native_state_requirement_ids_normalized": 26100,
  "settings_sections": 9,
  "screener_modes": 3,
  "prebreakout_submodes": 3,
  "component_files_not_reached": 4,
  "unresolved_discovery_items": 1
}
```

Definitions include inline components/icons; instances are conservative route/component candidates, not DOM counts or a disclosure count. Nine pending state requirements apply to each instance through the normalized join documented in inventory.json. Native disclosures are occurrence metadata inside definitions; multiple categories may overlap.

## Route entries

| Entry ID / source | URL | Classification | Numeric owner |
| --- | --- | --- | --- |
| `frontend/app/(frame)/@contextRail/alerts/default.tsx` | `/alerts` | parallel-slot-fallback | G; persistence I; presentation J |
| `frontend/app/(frame)/@contextRail/analysis/page.tsx` | `/analysis` | parallel-slot-page | H; persistence I; presentation J |
| `frontend/app/(frame)/@contextRail/chart/page.tsx` | `/chart` | parallel-slot-page | H; persistence I; presentation J |
| `frontend/app/(frame)/@contextRail/dashboard/page.tsx` | `/dashboard` | parallel-slot-page | H; persistence I; presentation J |
| `frontend/app/(frame)/@contextRail/default.tsx` | `/` | parallel-slot-fallback | H; persistence I; presentation J |
| `frontend/app/(frame)/@contextRail/portfolio/page.tsx` | `/portfolio` | parallel-slot-page | F; persistence I; presentation J |
| `frontend/app/(frame)/@contextRail/screener/default.tsx` | `/screener` | parallel-slot-fallback | H; persistence I; presentation J |
| `frontend/app/(frame)/@contextRail/screener/step-7-trade-card/default.tsx` | `/screener/step-7-trade-card` | parallel-slot-fallback | C; persistence I; presentation J |
| `frontend/app/(frame)/@contextRail/screener/step-7-trade-card/page.tsx` | `/screener/step-7-trade-card` | parallel-slot-page | C; persistence I; presentation J |
| `frontend/app/(frame)/@contextRail/watchlist/page.tsx` | `/watchlist` | parallel-slot-page | G; persistence I; presentation J |
| `frontend/app/(frame)/alerts/page.tsx` | `/alerts` | url-page | G; persistence I; presentation J |
| `frontend/app/(frame)/analysis/page.tsx` | `/analysis` | url-page | H; persistence I; presentation J |
| `frontend/app/(frame)/calendar/page.tsx` | `/calendar` | url-page | H; persistence I; presentation J |
| `frontend/app/(frame)/chart/page.tsx` | `/chart` | url-page | H; persistence I; presentation J |
| `frontend/app/(frame)/dashboard/page.tsx` | `/dashboard` | url-page | H; persistence I; presentation J |
| `frontend/app/(frame)/error.tsx` | `/` | error-boundary | H; persistence I; presentation J |
| `frontend/app/(frame)/journal/page.tsx` | `/journal` | url-page | H; persistence I; presentation J |
| `frontend/app/(frame)/layout.tsx` | `/` | layout | H; persistence I; presentation J |
| `frontend/app/(frame)/loading.tsx` | `/` | loading-boundary | H; persistence I; presentation J |
| `frontend/app/(frame)/portfolio/page.tsx` | `/portfolio` | url-page | F; persistence I; presentation J |
| `frontend/app/(frame)/screener/layout.tsx` | `/screener` | layout | H; persistence I; presentation J |
| `frontend/app/(frame)/screener/page.tsx` | `/screener` | redirect | H; persistence I; presentation J |
| `frontend/app/(frame)/screener/step-1-regime/page.tsx` | `/screener/step-1-regime` | url-page | B; persistence I; presentation J |
| `frontend/app/(frame)/screener/step-2-universe/page.tsx` | `/screener/step-2-universe` | url-page | B; persistence I; presentation J |
| `frontend/app/(frame)/screener/step-3-direction/page.tsx` | `/screener/step-3-direction` | url-page | B; persistence I; presentation J |
| `frontend/app/(frame)/screener/step-4-prebreakout/page.tsx` | `/screener/step-4-prebreakout` | url-page | E; persistence I; presentation J |
| `frontend/app/(frame)/screener/step-4-ranking/page.tsx` | `/screener/step-4-ranking` | url-page | C; persistence I; presentation J |
| `frontend/app/(frame)/screener/step-4-stocks/page.tsx` | `/screener/step-4-stocks` | url-page | D; persistence I; presentation J |
| `frontend/app/(frame)/screener/step-5-strategy/page.tsx` | `/screener/step-5-strategy` | redirect | D; persistence I; presentation J |
| `frontend/app/(frame)/screener/step-5-vol-events/page.tsx` | `/screener/step-5-vol-events` | url-page | C; persistence I; presentation J |
| `frontend/app/(frame)/screener/step-6-backtest/page.tsx` | `/screener/step-6-backtest` | url-page | D; persistence I; presentation J |
| `frontend/app/(frame)/screener/step-6-contracts/page.tsx` | `/screener/step-6-contracts` | url-page | C; persistence I; presentation J |
| `frontend/app/(frame)/screener/step-7-position-card/page.tsx` | `/screener/step-7-position-card` | url-page | D; persistence I; presentation J |
| `frontend/app/(frame)/screener/step-7-trade-card/page.tsx` | `/screener/step-7-trade-card` | url-page | C; persistence I; presentation J |
| `frontend/app/(frame)/settings/page.tsx` | `/settings` | url-page | B; persistence I; presentation J |
| `frontend/app/(frame)/strategy-watch/page.tsx` | `/strategy-watch` | url-page | G; persistence I; presentation J |
| `frontend/app/(frame)/validation/page.tsx` | `/validation` | url-page | H; persistence I; presentation J |
| `frontend/app/(frame)/watchlist/page.tsx` | `/watchlist` | url-page | G; persistence I; presentation J |
| `frontend/app/__test-crash/page.tsx` | `/__test-crash` | private-folder-source | H; persistence I; presentation J |
| `frontend/app/chart/standalone/layout.tsx` | `/chart/standalone` | layout | H; persistence I; presentation J |
| `frontend/app/chart/standalone/page.tsx` | `/chart/standalone` | url-page | H; persistence I; presentation J |
| `frontend/app/dev/components/page.tsx` | `/dev/components` | url-page | H; persistence I; presentation J |
| `frontend/app/layout.tsx` | `/` | layout | H; persistence I; presentation J |
| `frontend/app/not-found.tsx` | `/` | not-found-boundary | H; persistence I; presentation J |
| `frontend/app/page.tsx` | `/` | redirect | H; persistence I; presentation J |

## Source readbacks

### Root, inherited layouts and mode redirect

Root page unconditionally redirects to /dashboard. /screener redirects to shared Step 1. Legacy Step 5 redirects to stocks Step 4. ScreenerStepGate reads hydrated persisted mode before allowing slugs; mismatched slugs route to active mode index 4, failed hydration grace routes to Step 1. Do not treat source slug digit as logical Stocks step index.

- `frontend/app/page.tsx:4` — redirect('/dashboard')
- `frontend/app/(frame)/screener/page.tsx:10` — shared Step 1 redirect
- `frontend/app/(frame)/screener/step-5-strategy/page.tsx:8` — compatibility redirect
- `frontend/components/organisms/ScreenerStepGate/index.tsx:125` — hydration fallback and active-mode replace

### Frame, slots and standalone exposure

Root layout mounts hydration/theme/min-width globally. Frame wraps children and parallel contextRail with TopBar, ConfigHealthBanner, NavRail, InitStores and shortcuts. ContextRail renders supplied children; rail pages/defaults are not independent URL pages. Standalone chart inherits root layout but has a pass-through standalone layout rather than Frame. Slot retained content versus defaults is runtime/history dependent.

- `frontend/app/layout.tsx:87` — root wrappers
- `frontend/app/(frame)/layout.tsx:27` — two route children including contextRail
- `frontend/components/organisms/ContextRail/index.tsx:13` — slot children rendered
- `frontend/app/chart/standalone/page.tsx:4` — ChartWorkspace inside Suspense fallback null

### Developer and private source entries

dev/components explicitly calls notFound outside development; development renders atom/molecule gallery including statuses/theme. __test-crash also checks NODE_ENV then throws, but leading underscore is Next private-folder convention: source page existence does not establish routable /__test-crash. Runtime/Next route manifest must resolve exposure. Neither source entry silently excluded.

- `frontend/app/dev/components/page.tsx:35` — NODE_ENV guard
- `frontend/app/__test-crash/page.tsx:5` — private source crash function and production notFound guard

### Min-width and shared boundaries

Actual source uses 1280px minimum by default and 1200px only on exact Step 7 trade-card/position-card paths. The overlay keeps children mounted. Frame has error/reset and loading boundaries; root not-found is separate. Runtime must exercise boundary reachability without assuming private crash source can invoke Frame error.

- `frontend/components/MinWidthGate/index.tsx:14` — 1280/1200 constants and path switch
- `frontend/app/(frame)/error.tsx:1` — shared error/reset implementation
- `frontend/app/(frame)/loading.tsx:1` — shared loading implementation
- `frontend/app/not-found.tsx:1` — root not-found implementation

### Settings nine sections and nested state

SECTIONS has exactly nine keys and initial active section is brokers. JSX branches dispatch local form components; scan has nested spreads, gates and scheduled controls; tuning has ProposalCard.expanded fold evidence. Credential/notification/job controls are source inventory only and must use synthetic inputs with network mutations blocked. Settings sections own explicit domain handoffs, not one blanket settings correctness claim.

- `frontend/app/(frame)/settings/page.tsx:33` — SECTIONS metadata
- `frontend/app/(frame)/settings/page.tsx:46` — initial brokers local state
- `frontend/app/(frame)/settings/page.tsx:75` — all nine conditional forms
- `frontend/app/(frame)/settings/page.tsx:2686` — nested expandable tuning proposal

### Persistence overlay is part of restoration

StoreHydration starts explicit store rehydrations, then conditional last-scan recovery and metadata fetches. Options context reconstruction precedes recovered result insertion under guarded conditions. InitStores independently rehydrates portfolio/watchlist then syncs backend data. Browser reload probes must record both storage and mock recovery responses; seeding localStorage alone does not define final state. These mechanisms are read for discovery only, not independently audited correctness.

- `frontend/components/StoreHydration/index.tsx:35` — rehydrate, last scan recovery and guarded context
- `frontend/components/molecules/InitStores/index.tsx:12` — local then backend overlay

### Navigation and regime confirmation

NavItems has eleven primary destinations (Validation is still a source route without a primary nav entry). NavRail substitutes Stepper when pathname starts /screener. StepNavBar has a REJECT-regime confirmation dialog; modal presence suppresses arrow shortcuts. Runtime must test buttons, direct URLs, keyboard navigation and back/forward under each mode.

- `frontend/components/organisms/NavItems/index.tsx:20` — eleven ITEMS
- `frontend/components/organisms/NavRail/index.tsx:23` — pathname branch
- `frontend/components/organisms/StepNavBar/index.tsx:58` — modal keyboard guard
- `frontend/components/organisms/StepNavBar/index.tsx:71` — regime confirmation dialog

### Domain tabs and nested actions

Watchlist has stocks/contracts tabs and selected-symbol InlineChartPanel. Portfolio has open/history, per-contract EditDrawer, close error and ClosePositionDrawer overlays plus clear confirmation. Alerts selects alerts/rules/watches and new/edit/duplicate rule builder. Journal toggles create/edit form and deletion ConfirmDialog. Calendar has month navigation and day selection; strategy-watch has single and bulk subscription controls. Their custom child calls and native conditions are retained in definition records, with all actual mutation paths mocked/blocked by runtime task.

- `frontend/app/(frame)/watchlist/page.tsx:66` — tabs/selection state
- `frontend/app/(frame)/portfolio/page.tsx:97` — edit/open/history/close state
- `frontend/app/(frame)/alerts/page.tsx:212` — three tabs and builder state
- `frontend/app/(frame)/journal/page.tsx:49` — form/edit/delete state
- `frontend/app/(frame)/calendar/page.tsx:96` — month anchor/selected date
- `frontend/app/(frame)/strategy-watch/page.tsx:42` — single/bulk strategy/direction/horizon controls

### CSS tooltips, portal placement and imperative charts

Tooltip renders a role=tooltip span; CSS hides it with display:none and exposes it for wrap:hover and focus-within. Source occurrence IDs cover this actual CSS trigger. TradeCard portals methodSelector into decisionTarget, with inline fallback when target is undefined and hidden when null; selector JSX remains in TradeCard source. ChartPane/CandlestickChart instantiate lightweight-charts imperatively. ChartWorkspace subscribes click/crosshair and Escape drawing behavior. Explicit manual surface IDs preserve these non-JSX/placement requirements. A repository-wide source search found no other createPortal callsite or onContextMenu/contextmenu handler in app/components; that search does not certify third-party chart menus or all CSS semantic disclosures.

- `frontend/components/atoms/Tooltip/index.tsx:14` — role=tooltip markup
- `frontend/components/atoms/Tooltip/Tooltip.module.css:59` — hover/focus-within CSS trigger
- `frontend/components/organisms/TradeCard/index.tsx:3154` — method selector portal conditions
- `frontend/components/organisms/ChartPane/index.tsx:92` — imperative chart creation and crosshair subscription
- `frontend/components/organisms/ChartWorkspace/index.tsx:712` — drawing click subscription; Escape/crosshair below

## Settings and modes

| Setting key | Entry action | Component / owner |
| --- | --- | --- |
| theme | Settings > Appearance; local active='theme' | ThemeForm; B / I / J |
| scan | Settings > Scan; includes thresholds, spreads, scheduled scans and retention/timezone children | ScanForm; B / I / J |
| strategy | Settings > Strategy scan | StrategyScanForm; B / I / J |
| brokers | Settings initial section or Brokers; paper/live locked states; fake credentials only | BrokersForm; F / I / J |
| risk | Settings > Risk; local draft and backend hydration | RiskForm; F / I / J |
| regime | Settings > Regime; markov presets and editable inputs | RegimeForm; B / I / J |
| notifications | Settings > Notifications; Gmail/Telegram + retention; all sends blocked/mocked | NotificationForm; G / I / J |
| data | Settings > Data; ingestion, EDGAR and SP500 schedules; all jobs blocked/mocked | DataForm; H / I / J |
| tuning | Settings > Strategy Tuning; job progress/proposals/expanded folds; all start/adopt/clear mocked | StrategyTuningForm; D / I / J |

- **options**: Shared 1-3; ranking -> vol-events -> contracts -> trade-card (7 logical steps). Gate/rail/navigation and store restoration are separate requirements.
- **stocks**: Shared 1-3; step-4-stocks Strategy -> step-6-backtest Backtest -> step-7-position-card Position (6 logical steps). step-5-strategy is unconditional compatibility redirect to step-4-stocks, then active-mode gate can redirect again.
- **prebreakout**: Shared 1-3; step-4-prebreakout only. Local scanMode chooses prebreakout/pullback/fib. Each has parameter disclosures, tables, selected context/chart/news, scan-report inspector and inline composite-alert entry; candidate charts open separate window.

## Components and transitive coverage

All local module edges and per-entry closures are in `inventory.json.import_graph` and `route_entries[].reachable_modules`. Each definition includes JSX calls/props, native controls, conditions (including map repetition), hooks, source ranges and fixture requirements. Settings local functions and child disclosures are retained; barrels/imports are conservative module closures, so unrendered exports may remain.

- `frontend/app/(frame)/@contextRail/alerts/default.tsx`: 67 modules; 46 candidate component definitions; roots `frontend/app/(frame)/@contextRail/alerts/default.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/@contextRail/analysis/page.tsx`: 72 modules; 47 candidate component definitions; roots `frontend/app/(frame)/@contextRail/analysis/page.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/@contextRail/chart/page.tsx`: 69 modules; 47 candidate component definitions; roots `frontend/app/(frame)/@contextRail/chart/page.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/@contextRail/dashboard/page.tsx`: 68 modules; 47 candidate component definitions; roots `frontend/app/(frame)/@contextRail/dashboard/page.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/@contextRail/default.tsx`: 67 modules; 46 candidate component definitions; roots `frontend/app/(frame)/@contextRail/default.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/@contextRail/portfolio/page.tsx`: 70 modules; 48 candidate component definitions; roots `frontend/app/(frame)/@contextRail/portfolio/page.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/@contextRail/screener/default.tsx`: 67 modules; 46 candidate component definitions; roots `frontend/app/(frame)/@contextRail/screener/default.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/@contextRail/screener/step-7-trade-card/default.tsx`: 73 modules; 47 candidate component definitions; roots `frontend/app/(frame)/@contextRail/screener/step-7-trade-card/default.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/@contextRail/screener/step-7-trade-card/page.tsx`: 72 modules; 47 candidate component definitions; roots `frontend/app/(frame)/@contextRail/screener/step-7-trade-card/page.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/@contextRail/watchlist/page.tsx`: 71 modules; 49 candidate component definitions; roots `frontend/app/(frame)/@contextRail/watchlist/page.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/alerts/page.tsx`: 73 modules; 51 candidate component definitions; roots `frontend/app/(frame)/@contextRail/alerts/default.tsx`, `frontend/app/(frame)/alerts/page.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/analysis/page.tsx`: 83 modules; 55 candidate component definitions; roots `frontend/app/(frame)/@contextRail/analysis/page.tsx`, `frontend/app/(frame)/analysis/page.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/calendar/page.tsx`: 70 modules; 50 candidate component definitions; roots `frontend/app/(frame)/@contextRail/default.tsx`, `frontend/app/(frame)/calendar/page.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/chart/page.tsx`: 119 modules; 69 candidate component definitions; roots `frontend/app/(frame)/@contextRail/chart/page.tsx`, `frontend/app/(frame)/chart/page.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/dashboard/page.tsx`: 87 modules; 67 candidate component definitions; roots `frontend/app/(frame)/@contextRail/dashboard/page.tsx`, `frontend/app/(frame)/dashboard/page.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/error.tsx`: 68 modules; 47 candidate component definitions; roots `frontend/app/(frame)/@contextRail/default.tsx`, `frontend/app/(frame)/error.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/journal/page.tsx`: 75 modules; 53 candidate component definitions; roots `frontend/app/(frame)/@contextRail/default.tsx`, `frontend/app/(frame)/journal/page.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/layout.tsx`: 67 modules; 46 candidate component definitions; roots `frontend/app/(frame)/@contextRail/default.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/loading.tsx`: 68 modules; 47 candidate component definitions; roots `frontend/app/(frame)/@contextRail/default.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/(frame)/loading.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/portfolio/page.tsx`: 93 modules; 70 candidate component definitions; roots `frontend/app/(frame)/@contextRail/portfolio/page.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/(frame)/portfolio/page.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/screener/layout.tsx`: 70 modules; 49 candidate component definitions; roots `frontend/app/(frame)/@contextRail/screener/default.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/(frame)/screener/layout.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/screener/page.tsx`: 71 modules; 49 candidate component definitions; roots `frontend/app/(frame)/@contextRail/screener/default.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/(frame)/screener/layout.tsx`, `frontend/app/(frame)/screener/page.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/screener/step-1-regime/page.tsx`: 83 modules; 57 candidate component definitions; roots `frontend/app/(frame)/@contextRail/screener/default.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/(frame)/screener/layout.tsx`, `frontend/app/(frame)/screener/step-1-regime/page.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/screener/step-2-universe/page.tsx`: 72 modules; 50 candidate component definitions; roots `frontend/app/(frame)/@contextRail/screener/default.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/(frame)/screener/layout.tsx`, `frontend/app/(frame)/screener/step-2-universe/page.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/screener/step-3-direction/page.tsx`: 95 modules; 69 candidate component definitions; roots `frontend/app/(frame)/@contextRail/screener/default.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/(frame)/screener/layout.tsx`, `frontend/app/(frame)/screener/step-3-direction/page.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/screener/step-4-prebreakout/page.tsx`: 104 modules; 75 candidate component definitions; roots `frontend/app/(frame)/@contextRail/screener/default.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/(frame)/screener/layout.tsx`, `frontend/app/(frame)/screener/step-4-prebreakout/page.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/screener/step-4-ranking/page.tsx`: 119 modules; 97 candidate component definitions; roots `frontend/app/(frame)/@contextRail/screener/default.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/(frame)/screener/layout.tsx`, `frontend/app/(frame)/screener/step-4-ranking/page.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/screener/step-4-stocks/page.tsx`: 100 modules; 67 candidate component definitions; roots `frontend/app/(frame)/@contextRail/screener/default.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/(frame)/screener/layout.tsx`, `frontend/app/(frame)/screener/step-4-stocks/page.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/screener/step-5-strategy/page.tsx`: 71 modules; 49 candidate component definitions; roots `frontend/app/(frame)/@contextRail/screener/default.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/(frame)/screener/layout.tsx`, `frontend/app/(frame)/screener/step-5-strategy/page.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/screener/step-5-vol-events/page.tsx`: 77 modules; 55 candidate component definitions; roots `frontend/app/(frame)/@contextRail/screener/default.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/(frame)/screener/layout.tsx`, `frontend/app/(frame)/screener/step-5-vol-events/page.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/screener/step-6-backtest/page.tsx`: 113 modules; 75 candidate component definitions; roots `frontend/app/(frame)/@contextRail/screener/default.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/(frame)/screener/layout.tsx`, `frontend/app/(frame)/screener/step-6-backtest/page.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/screener/step-6-contracts/page.tsx`: 84 modules; 59 candidate component definitions; roots `frontend/app/(frame)/@contextRail/screener/default.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/(frame)/screener/layout.tsx`, `frontend/app/(frame)/screener/step-6-contracts/page.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/screener/step-7-position-card/page.tsx`: 98 modules; 65 candidate component definitions; roots `frontend/app/(frame)/@contextRail/screener/default.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/(frame)/screener/layout.tsx`, `frontend/app/(frame)/screener/step-7-position-card/page.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/screener/step-7-trade-card/page.tsx`: 118 modules; 89 candidate component definitions; roots `frontend/app/(frame)/@contextRail/screener/step-7-trade-card/page.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/(frame)/screener/layout.tsx`, `frontend/app/(frame)/screener/step-7-trade-card/page.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/settings/page.tsx`: 71 modules; 75 candidate component definitions; roots `frontend/app/(frame)/@contextRail/default.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/(frame)/settings/page.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/strategy-watch/page.tsx`: 70 modules; 49 candidate component definitions; roots `frontend/app/(frame)/@contextRail/default.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/(frame)/strategy-watch/page.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/validation/page.tsx`: 75 modules; 52 candidate component definitions; roots `frontend/app/(frame)/@contextRail/default.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/(frame)/validation/page.tsx`, `frontend/app/layout.tsx`
- `frontend/app/(frame)/watchlist/page.tsx`: 89 modules; 67 candidate component definitions; roots `frontend/app/(frame)/@contextRail/watchlist/page.tsx`, `frontend/app/(frame)/layout.tsx`, `frontend/app/(frame)/watchlist/page.tsx`, `frontend/app/layout.tsx`
- `frontend/app/__test-crash/page.tsx`: 41 modules; 7 candidate component definitions; roots `frontend/app/__test-crash/page.tsx`, `frontend/app/layout.tsx`
- `frontend/app/chart/standalone/layout.tsx`: 41 modules; 8 candidate component definitions; roots `frontend/app/chart/standalone/layout.tsx`, `frontend/app/layout.tsx`
- `frontend/app/chart/standalone/page.tsx`: 85 modules; 23 candidate component definitions; roots `frontend/app/chart/standalone/layout.tsx`, `frontend/app/chart/standalone/page.tsx`, `frontend/app/layout.tsx`
- `frontend/app/dev/components/page.tsx`: 65 modules; 36 candidate component definitions; roots `frontend/app/dev/components/page.tsx`, `frontend/app/layout.tsx`
- `frontend/app/layout.tsx`: 40 modules; 7 candidate component definitions; roots `frontend/app/layout.tsx`
- `frontend/app/not-found.tsx`: 41 modules; 8 candidate component definitions; roots `frontend/app/layout.tsx`, `frontend/app/not-found.tsx`
- `frontend/app/page.tsx`: 41 modules; 7 candidate component definitions; roots `frontend/app/layout.tsx`, `frontend/app/page.tsx`

## Outstanding discovery

Remaining checks belong to the recorded lane; source/runtime classification does not certify domain correctness or shipping approval. The full machine-readable list includes source evidence and disposition.

- `pending:backend-restart` — Browser storage reload and backend recovery mocks exist; no actual backend process/database restart performed or certified. Source config hash update is provenance only.

## Regeneration and focused verification

From the repository root:

```powershell
node docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/generate-source-inventory.cjs
node docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/generate-source-inventory.cjs --check
```

`--check` compares all three generated files byte-for-byte, checks IDs/source ranges, the independently obtained baseline route census and normalized state cardinality. It does not convert pending semantic/runtime checks into passes. Read `source-annotations.json` for reviewed semantic statements and state fixtures.

Original Task 2 evidence remains pinned to its original application SHA. The final semantic classification overlay resolves source capability/entry/state contracts without claiming every conservative candidate is actual DOM or every state has passed. Integrated evidence records changed-source execution separately.

Native candidates each have stable IDs, source ranges, owners, entry actions/conditions and state templates. Expand native route/state requirements using `native_instance_expansion` on each route-instance. Fixture rows still need data identity suffixes; source occurrences are not production row counts.

Focused contract verification: `node docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/verify-source-inventory.cjs`. This separately checks filesystem route census and known redirect/private/slot/CSS/portal/imperative/lifecycle edge cases.
