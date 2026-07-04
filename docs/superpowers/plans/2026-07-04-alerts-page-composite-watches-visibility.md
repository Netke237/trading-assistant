# Alerts Page — Composite Watches Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface **Composite Watches** (the scheduled/background composite triggers created via `CompositeAlertDialog` → `POST /api/composite-watches/`) on the Alerts page, where they are currently invisible, with enable/disable and delete controls. Also render live composite *rules* (from the item-1 plan) with a readable label instead of a blank-condition row.

**Architecture:** Add a third tab, **Watches**, to the existing Alerts page tab strip (`Alerts | Rules | Watches`). The tab fetches `GET /api/composite-watches/` (via the already-present `api.listCompositeWatches`) into local component state and renders a table with enable toggle (`api.setCompositeWatchEnabled`) and delete (`api.removeCompositeWatch`). A pure `compositeWatchSummary()` helper turns a watch's `trigger_def` into human-readable text. Separately, the existing Rules tab is taught to label composite-type alert rules so item-1's rows are not blank.

**Tech Stack:** Next.js 15 + React, Zustand, Jest + React Testing Library. All backend endpoints already exist — this is frontend-only.

**Related:** `docs/superpowers/plans/2026-07-04-live-composite-alert-rule-creation.md` (item 1) introduces `rule_type: 'composite'` on `GET /alerts/rules` rows; Task 4 here consumes that field. Item 1 is NOT a hard dependency for Tasks 1–3 (the Watches tab), but IS a dependency for Task 4.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `frontend/lib/compositeWatchSummary.ts` | Create | Pure helper: `trigger_def` → readable summary string |
| `frontend/lib/__tests__/compositeWatchSummary.test.ts` | Create | Unit tests for the helper |
| `frontend/app/(frame)/alerts/page.tsx` | Modify | Third "Watches" tab: fetch, render, enable toggle, delete |
| `frontend/app/(frame)/alerts/page.module.css` | Modify | Reuse existing `.rulesTable*` styles; add nothing unless needed |
| `frontend/types/alerts.ts` | Modify | Add optional `rule_type`/`composite_def` to `AlertRule` (for Task 4) |

---

## Design decisions (read before coding)

1. **Component-local state, not a new store.** Composite watches are read-mostly and only shown here. A `useState<CompositeWatch[]>` loaded on tab mount is simpler than a Zustand store and matches the page's existing pattern (it already uses local `fetch` for delivery prefs). No new store.

2. **Optimistic UI.** Enable-toggle and delete update local state immediately, then call the API; on failure, refetch to resync. Keeps the table responsive without a spinner.

3. **`compositeWatchSummary` is pure and defensively typed.** `trigger_def` is `Record<string, unknown>`; the helper reads `primary.model`, `primary.to_state`, `confirmations.length`, `strategy_confirmations.length` with guards, never throwing on a malformed def.

4. **Rules-tab composite label (Task 4).** After item 1, `GET /alerts/rules` can return `rule_type: 'composite'` rows with an empty `group`. The Rules tab's `conditionsSummary()` would render an empty string for these. Task 4 makes it render `compositeWatchSummary(rule.composite_def)` instead, so a live composite rule reads sensibly. Guarded so it is a no-op if item 1 has not shipped (field simply absent → falls through to the existing path).

---

## Task 1: Pure helper — `compositeWatchSummary`

**Files:**
- Create: `frontend/lib/compositeWatchSummary.ts`
- Test: `frontend/lib/__tests__/compositeWatchSummary.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/lib/__tests__/compositeWatchSummary.test.ts
import { compositeWatchSummary } from '../compositeWatchSummary';

describe('compositeWatchSummary', () => {
  it('summarizes primary model + target state', () => {
    expect(compositeWatchSummary({
      primary: { model: 'OMM', to_state: 'Bull' },
      confirmations: [], strategy_confirmations: [],
    })).toBe('OMM → Bull');
  });

  it('appends confirmation and strategy counts', () => {
    expect(compositeWatchSummary({
      primary: { model: 'HMM_daily', to_state: 'Trending' },
      confirmations: [{}, {}], strategy_confirmations: [{}],
    })).toBe('HMM_daily → Trending · 2 confirmations · 1 strategy');
  });

  it('handles "any" model and missing state', () => {
    expect(compositeWatchSummary({
      primary: { model: 'any' },
      confirmations: [], strategy_confirmations: [],
    })).toBe('any model → any state');
  });

  it('never throws on a malformed def', () => {
    expect(compositeWatchSummary({})).toBe('any model → any state');
    expect(compositeWatchSummary(null as unknown as Record<string, unknown>)).toBe('—');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=compositeWatchSummary`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the helper**

```ts
// frontend/lib/compositeWatchSummary.ts

/** Human-readable one-liner for a composite trigger_def. Never throws. */
export function compositeWatchSummary(def: Record<string, unknown> | null | undefined): string {
  if (!def || typeof def !== 'object') return '—';
  const primary = (def.primary ?? {}) as Record<string, unknown>;
  const model = typeof primary.model === 'string' ? primary.model : 'any';
  const modelText = model === 'any' ? 'any model' : model;
  const state = typeof primary.to_state === 'string' && primary.to_state ? primary.to_state : null;
  const stateText = state ?? 'any state';

  const parts = [`${modelText} → ${stateText}`];

  const confirmations = Array.isArray(def.confirmations) ? def.confirmations.length : 0;
  if (confirmations > 0) parts.push(`${confirmations} confirmation${confirmations === 1 ? '' : 's'}`);

  const strategies = Array.isArray(def.strategy_confirmations) ? def.strategy_confirmations.length : 0;
  if (strategies > 0) parts.push(`${strategies} strateg${strategies === 1 ? 'y' : 'ies'}`);

  return parts.join(' · ');
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --testPathPattern=compositeWatchSummary`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/compositeWatchSummary.ts frontend/lib/__tests__/compositeWatchSummary.test.ts
git commit -m "feat(alerts): compositeWatchSummary helper for trigger_def display"
```

---

## Task 2: Alerts page — add the Watches tab (fetch + render)

**Files:**
- Modify: `frontend/app/(frame)/alerts/page.tsx`

- [ ] **Step 1: Extend imports + tab state**

At the top of `page.tsx`, add imports:

```tsx
import { api, type CompositeWatch } from '@/lib/api';
import { compositeWatchSummary } from '@/lib/compositeWatchSummary';
```

Change the tab state type:

```tsx
  const [tab, setTab] = useState<'alerts' | 'rules' | 'watches'>('alerts');
  const [watches, setWatches] = useState<CompositeWatch[]>([]);
  const [watchesLoaded, setWatchesLoaded] = useState(false);
```

- [ ] **Step 2: Fetch watches when the Watches tab is first opened**

Add after the existing effects:

```tsx
  const loadWatches = useCallback(() => {
    api.listCompositeWatches()
      .then((w) => { setWatches(w); setWatchesLoaded(true); })
      .catch(() => setWatchesLoaded(true));
  }, []);

  useEffect(() => {
    if (tab === 'watches' && !watchesLoaded) loadWatches();
  }, [tab, watchesLoaded, loadWatches]);
```

- [ ] **Step 3: Add the tab button**

In the `.pageTabStrip`, after the Rules tab button, add:

```tsx
        <button
          type="button"
          className={[styles.pageTab, tab === 'watches' ? styles.pageTabActive : ''].join(' ')}
          onClick={() => setTab('watches')}
        >
          Watches
        </button>
```

- [ ] **Step 4: Render the Watches table**

After the `{tab === 'rules' && (…)}` block, add:

```tsx
      {tab === 'watches' && (
        <section className={styles.section}>
          <div className={styles.rulesHeader}>
            <Text size={11} tone="secondary" weight={600}>Composite Watches</Text>
            <Text size={11} tone="dim">
              Background checks by the scheduler — active even when no chart tab is open.
            </Text>
          </div>
          {!watchesLoaded ? (
            <div className={styles.empty}><Text size={13} tone="secondary">Loading…</Text></div>
          ) : watches.length === 0 ? (
            <div className={styles.empty}>
              <Text size={13} tone="secondary">
                No composite watches yet. Create one from a chart&apos;s Composite Alert dialog.
              </Text>
            </div>
          ) : (
            <div className={styles.rulesTable}>
              <div className={[styles.watchesTableRow, styles.rulesTableHeader].join(' ')}>
                <Text size={11} tone="dim" weight={600}>Symbol</Text>
                <Text size={11} tone="dim" weight={600}>Direction</Text>
                <Text size={11} tone="dim" weight={600}>Interval</Text>
                <Text size={11} tone="dim" weight={600}>Trigger</Text>
                <Text size={11} tone="dim" weight={600}>Enabled</Text>
                <Text size={11} tone="dim" weight={600}>Actions</Text>
              </div>
              {watches.map((w) => (
                <div key={w.id} className={styles.watchesTableRow}>
                  <Data size={12} weight={500}>{w.symbol}</Data>
                  <Text size={12}>{w.direction}</Text>
                  <Text size={12}>{w.interval}</Text>
                  <Text size={12}>{compositeWatchSummary(w.trigger_def)}</Text>
                  <Toggle
                    on={w.enabled}
                    onChange={(on) => toggleWatch(w.id, on)}
                  />
                  <div className={styles.rulesActions}>
                    <button
                      type="button"
                      className={styles.btnDanger}
                      onClick={() => deleteWatch(w.id)}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}
```

Note: the Watches table has 6 columns vs the Rules tab's 7, so it uses a dedicated `.watchesTableRow` grid class (added unconditionally in Task 3 Step 3) rather than reusing `.rulesTableRow`. This avoids relying on a visual check an agentic worker cannot perform.

- [ ] **Step 5: Typecheck (will fail until Task 3 adds handlers)**

Run: `cd frontend && npm run typecheck`
Expected: FAIL — `toggleWatch`/`deleteWatch` not defined yet. Proceed to Task 3.

---

## Task 3: Alerts page — enable toggle + delete handlers (optimistic)

**Files:**
- Modify: `frontend/app/(frame)/alerts/page.tsx`
- Modify: `frontend/app/(frame)/alerts/page.module.css` (only if grid misaligns)

- [ ] **Step 1: Add the handlers**

Add near the other `function handle…` helpers in `AlertsPage`:

```tsx
  function toggleWatch(id: string, on: boolean) {
    setWatches((prev) => prev.map((w) => (w.id === id ? { ...w, enabled: on } : w)));
    api.setCompositeWatchEnabled(id, on).catch(() => loadWatches());
  }

  function deleteWatch(id: string) {
    setWatches((prev) => prev.filter((w) => w.id !== id));
    api.removeCompositeWatch(id).catch(() => loadWatches());
  }
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 3: Add the 6-column grid class (required)**

Add a scoped grid class in `page.module.css` so the Watches table aligns (Task 2 already references `styles.watchesTableRow`):

```css
.watchesTableRow {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr 2fr 0.6fr 1fr;
  gap: 12px;
  align-items: center;
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/app/\(frame\)/alerts/page.tsx frontend/app/\(frame\)/alerts/page.module.css
git commit -m "feat(alerts): Watches tab lists composite watches with enable/delete"
```

---

## Task 4: Rules tab — label composite-type rules (bridges item 1)

**Files:**
- Modify: `frontend/types/alerts.ts` (`AlertRule` type)
- Modify: `frontend/app/(frame)/alerts/page.tsx` (`conditionsSummary`)

- [ ] **Step 1: Extend the `AlertRule` type**

In `frontend/types/alerts.ts`, add to the `AlertRule` interface:

```ts
  rule_type?: 'standard' | 'composite';
  composite_def?: Record<string, unknown>;
```

- [ ] **Step 2: Make `conditionsSummary` composite-aware**

In `page.tsx`, replace `conditionsSummary`:

```tsx
function conditionsSummary(rule: AlertRule): string {
  if (rule.rule_type === 'composite' && rule.composite_def) {
    return `Composite — ${compositeWatchSummary(rule.composite_def)}`;
  }
  return rule.group.conditions.map(conditionText).join(` ${rule.group.logic} `);
}
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/types/alerts.ts frontend/app/\(frame\)/alerts/page.tsx
git commit -m "feat(alerts): render live composite rules with a readable label in Rules tab"
```

---

## Task 5: Manual verification

- [ ] **Step 1:** `cd frontend && npm run dev`; ensure backend running.
- [ ] **Step 2:** Create a Composite Watch from a chart. Open Alerts → **Watches**; confirm it appears with a readable Trigger summary.
- [ ] **Step 3:** Toggle it off, reload the page, confirm the disabled state persisted (backend round-trip).
- [ ] **Step 4:** Delete it; confirm it disappears and does not reappear on reload.
- [ ] **Step 5 (needs item 1):** Create a live composite Rule; open Alerts → **Rules**; confirm it shows `Composite — …` rather than a blank Conditions cell.

---

## Self-review checklist (done during writing)

- Item-2 requirement (show Composite Watches) covered by Tasks 1–3. Enable/disable + delete covered (Task 3). Readable trigger text covered (Task 1).
- Item-1 bridge (composite rules in Rules tab) covered by Task 4, guarded so it is inert if item 1 has not shipped.
- Type consistency: `compositeWatchSummary(def)` signature identical across helper (Task 1), Watches render (Task 2), Rules summary (Task 4). `CompositeWatch` reused from `api.ts` (not redefined).
- No new store introduced (design decision 1). Optimistic updates resync on failure (design decision 2).
- Dependency note: Tasks 1–3 have no dependency on item 1; Task 4 depends on item 1's `rule_type`/`composite_def` list fields.
