# RISK-TOOLTIP-SHARED-COMPARATORS (+ eventDetailText guard) — plan

Date: 2026-09-25. Approved by Kenneth ("Go ahead") on the proposal given at the end
of the A5c session. Frontend only, one layer, well under 500 lines.

Closes `open_questions` "RISK-TOOLTIP-SHARED-COMPARATORS" and the latent
"undefined in undefinedd" entry.

## Problem

1. `riskStatusTooltip` (`frontend/lib/statusTooltips.ts`) carries its own copy of the
   four risk-band comparators that `riskStore.computeMetrics`
   (`frontend/lib/riskStore.ts`) applies. The two copies agree today, but nothing
   pins them together: on both COUNT bands, changing `0.8` to `0.75` (or rejecting at
   `v >= c - 1`) ships the full suite green, because at the default caps (10, 5) the
   floors coincide. Result if it happened: "4 of a 5 limit (PASS)" beside a CAUTION
   badge.
2. `eventDetailText({})` returns `"undefined in undefinedd"`, so
   `ruleContributionTooltip('event', status, undefined)` never reaches its generic
   fallback. Unreachable today (the backend always sends a detail dict), but the type
   `EventDetail.days_to_event?: number` permits it.

## Change

### C1. One comparator, in `frontend/lib/status.ts`

```ts
export type RiskBandKind = 'fraction' | 'count';
export function riskBandStatus(kind: RiskBandKind, value: number, cap: number): Status
```

- `fraction` (exposure, concentration): REJECT when `value > cap`, CAUTION when
  `value > cap * 0.8`, else PASS.
- `count` (concurrent positions, daily recommendations): REJECT when `value >= cap`,
  CAUTION when `value >= Math.floor(cap * 0.8)`, else PASS.

Exactly today's expressions, character for character. Home is `lib/status.ts`
(not `riskStore.ts` as first proposed): both consumers already import it, and
`statusTooltips` imports only *types* from `riskStore` today — importing a value
would pull the persisted Zustand store into the tooltip module for no reason.

### C2. `computeMetrics` calls it

The four ternaries become `riskBandStatus('fraction', totalExposurePct, …)`,
`('count', concurrentPositions, …)`, `('count', dailyRecommendations, …)`,
`('fraction', largestConcentrationPct, …)`. Push order unchanged (it only feeds
`worstStatus`).

### C3. `riskStatusTooltip` calls it

Each band's `statusFor` closure is replaced by a `kind` field; the status is
`riskBandStatus(b.kind, b.value, b.cap)`. Band order, labels, formatting and the
worst-band sort are untouched. The doc comment is updated to say it shares the
comparator instead of mirroring it.

### C4. `eventDetailText` guard (`frontend/lib/scoreDetailText.ts`)

- `!d || !d.event` → `undefined` (the tooltip then falls back to its generic text).
- `event === 'none'` → unchanged.
- `days_to_event == null` → the event name alone (e.g. `"earnings"`).
- otherwise unchanged: `"earnings in 12d"`.

## Behaviour that is KEPT (not changed by this pass)

- cap 1, 0 positions → CAUTION (`floor(0.8) = 0`, `0 >= 0`).
- cap 2, 1 position → CAUTION (`floor(1.6) = 1`).
- A cap of 0 → REJECT for every count (`v >= 0`).

These are product questions for Kenneth, not part of a refactor.

## Tests

T1 (`frontend/lib/__tests__/riskBandStatus.test.ts`, new):
- **Count sweep.** For every cap 1..30 and every value 0..cap+2, `riskBandStatus('count', v, c)`
  equals an oracle written in integer arithmetic: REJECT iff `v >= c`, else CAUTION iff
  `5*v >= 4*c - (4*c % 5)` (i.e. `v >= floor(4c/5)`), else PASS. No floats in the oracle.
- The same sweep through **both consumers**: `computeMetrics` (store with
  `maxConcurrentPositions = c` / `maxDailyRecommendations = c`, `v` positions or `v` daily
  recommendations, all other bands held at PASS) must report the oracle status, and
  `riskStatusTooltip(…, 'positions' | 'daily')` must end in `(<oracle status>).`
- **Fraction boundaries** (exposure, concentration) through both consumers: at the cap
  (CAUTION), just above (REJECT), at exactly 80% (PASS), just above 80% (CAUTION).
- The kept behaviours above, as literal cases.

T2 (`frontend/__tests__/scoreDetail.test.tsx`): replace the self-referential
`eventDetailText` placeholder tests with real calls: `{event:'earnings',days_to_event:12}`
→ `'earnings in 12d'`; `{event:'none'}` → `'No upcoming event'`; `{event:'earnings'}` →
`'earnings'`; `{}` / `undefined` / `{days_to_event: 5}` → `undefined`. Plus
`ruleContributionTooltip('event', 'CAUTION', undefined)` equals the generic CAUTION text.

The existing sampled pins in `statusTooltips.literal.test.ts` stay.

## Mutations the tests must kill

- M1 count factor 0.8 → 0.75 in `riskBandStatus`.
- M2 count REJECT `v >= c` → `v >= c - 1`.
- M3 count `Math.floor` → `Math.round`.
- M4 fraction `>` → `>=` at the cap.
- M5 fraction CAUTION `>` → `>=` at 80%.
- M6 `computeMetrics` passes `'fraction'` for concurrent positions (kind swap).
- M7 `riskStatusTooltip` daily band `kind: 'fraction'`.
- M8 `riskStatusTooltip` reintroduces a local comparator for positions with 0.75
  (the original seam).
- M9 `eventDetailText` guard removed (`{}` → "undefined in undefinedd").
- M10 `days_to_event == null` branch removed.

## Gate / audit

One adversarial round over this plan and the diff together (the change is one layer and
small). Per `audit_rule` a finding blocks only if it can put a wrong number in front of a
user or on a broker order, or corrupt persisted data. Nothing here touches persisted
state or orders.

## Build notes (2026-09-25)

- M9 first SURVIVED: with the `!d.event` guard removed, `{}` still returns `undefined`
  via the new no-day-count branch (`return d.event`). The input that separates them is a
  day count with no event name (`{days_to_event: 5}` → "undefined in 5d"); that case was
  added to T2 and M9 is now killed. All ten mutations killed.
