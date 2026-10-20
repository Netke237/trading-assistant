# APP-AUDIT-B-SAVE-FEEDBACK — #371

Remediation: 10% (concrete plan); size L; complexity 5/5. Board item #371 (part of #350, programme #348). Frontend only. No backend, calibration, schema, storage-key or persisted-shape change.

## Defect (from #371 and its 2026-10-17 follow-up)

The Settings footer button `SaveButton` (`frontend/app/(frame)/settings/page.tsx`) only flips a local flag and always shows "Saved":

1. Risk: type 234567 in Portfolio value, the field's blur POSTs `/settings/risk`, the POST fails (500), backend keeps 100000, footer says Saved.
2. Operator timezone: edit to Asia/Tokyo, click the footer — zero PUTs, backend keeps Europe/Berlin, footer says Saved. (The section's own Save works.)
3. Browser storage: when `localStorage.setItem` throws `QuotaExceededError` or `SecurityError` for the theme, Markov or confidence-gate writes, the new value stays displayed while the stored bytes stay old (zustand v5 `persist` updates memory, then the storage write throws out of `set()`), and the footer still says Saved. Reload restores the old value.

## Contract

The footer never reports success while the app knows that a Settings change is not saved. "Saved" means: no tracked save is still in flight, no tracked save's latest attempt failed, no tracked section holds an unsubmitted edit, and no tracked browser-storage write has failed since its last successful write. Otherwise the footer names every outstanding item in a persistent, accessible message.

Out of scope (unchanged): which value each section sends, per-section save buttons and their existing inline messages (except brokers, below), the order of local-store write vs POST in each section, risk enforcement (#354), cross-tab lost updates (#400, serialized after this item), presentation polish (#358). The footer does **not** submit any section's draft to the backend: it reports it. Actions that are not settings saves (Run now / trigger, start tuning job, adopt params, add / delete / run a schedule entry, Test notification) are not tracked.

## Mechanism

### A. Save ledger — `frontend/lib/settingsSaveStatus.ts` (new)

A non-persisted zustand store (no `persist()`, like `configHealthStore`: a stored "saved" verdict would be a stale green). Three record kinds, keyed by a channel id with a human label:

- `trackSave<T>(channel, label, run: () => Promise<T>): Promise<T>` — synchronously, before `run` is awaited, increments the channel's attempt sequence and records it in flight with its promise. On settle, the result is applied **only if that attempt is still the channel's latest** (an older attempt finishing late never overwrites a newer one): success clears the channel's failure; rejection records `failed` with a short message. The original result/rejection is returned/re-thrown unchanged so each section's existing handling keeps working. A section whose request resolves with a non-OK response (notifications uses raw `fetch`) passes a `run` that throws on `!res.ok`.
- `setDraft(channel, label, dirty: boolean)` — records or clears an unsubmitted edit. Sections clear their draft on unmount (their local draft state is discarded with the component, and the remounted section re-reads the server value).
- Browser-storage failures (fed by B): `failed` per storage key, holding the last serialized value whose write failed.
- `settleAll(): Promise<void>` — awaits every in-flight promise, looping until none is in flight (an attempt started while waiting is also awaited).
- `retryLocalWrites(): void` — for each failed storage key, `localStorage.setItem(key, pendingValue)`; success clears it, a throw keeps it failed.
- `outstanding(): { channel, label, kind: 'failed' | 'draft' | 'local', message }[]` — what the footer lists.

A failed backend save stays recorded until a later attempt on the same channel succeeds or the page reloads, even if the section unmounts or its remount re-fetches the server value: the operator's edit was not saved, and that remains true.

### B. Reporting storage — `frontend/lib/reportingLocalStorage.ts` (new)

`reportingLocalStorage(label): Storage`, modelled on `quotaSafeLocalStorage` in `scanStore.ts`: reads/removes pass through; `setItem(k, v)` calls `localStorage.setItem`; on success it clears any recorded failure for `k`; on a throw it records `failed` for `k` with `label` and `v`, **then re-throws the same error** (existing throw semantics are preserved — this item adds reporting, not new swallowing). Wire it via `createJSONStorage(() => typeof window === 'undefined' ? undefined : reportingLocalStorage(label))` into exactly these stores, keeping name, version, migrate and partialize byte-for-byte unchanged:

| Store | Key (unchanged) | Label |
|---|---|---|
| `settingsStore` | `bamendjou-settings` | Settings (this browser) |
| `theme` | `bamendjou:theme` | Appearance (this browser) |
| `riskStore` | `bamendjou-risk-v1` | Risk limits (this browser) |
| `scanParamsStore` | `bamendjou:scan-params` | Strategy scan parameters (this browser) |

`riskStore` and `scanParamsStore` currently rely on persist's default storage (`createJSONStorage(() => localStorage)`); the explicit wrapper serializes identically. No version bump: no shape change. The implementer must grep every caller of these stores' setters for a `try/catch` that depends on the throw and confirm it still receives it (it does, since B re-throws).

### C. Footer — `SaveButton` in `page.tsx`

On click: button shows "Saving…" and is disabled; `await settleAll()`; `retryLocalWrites()`; read `outstanding()`.

- Nothing outstanding → existing behaviour: "Saved" for 1.5 s (`role="status"`).
- Otherwise → button returns to "Save changes" and a persistent message beside it (`role="alert"`, reject tone) begins "Not saved:" and lists each item:
  - `failed` → "<label>: save failed — not confirmed by the server"
  - `draft` → "<label>: unsaved edit — use its Save button" (for an invalid strategy override draft: "<label>: invalid value not applied")
  - `local` → "<label>: could not be stored in this browser (storage full or blocked) — the previous value returns on reload"

The message stays until the next click, or clears itself as soon as `outstanding()` becomes empty (subscribe to the ledger). Blur fires on mousedown, before click, so a blur-triggered save (risk, trade-history retention) is already in flight when the click handler runs and is awaited.

### D. Channels wired in `page.tsx`

"Baseline" = the last value the server confirmed (load response or save response). Draft = the editable value differs from the baseline; if the load failed and nothing has been saved, draft = edited since mount.

| Channel id | Label | Save path to wrap in `trackSave` | Draft |
|---|---|---|---|
| `risk` | Risk limits | `handleSaveRisk` → `saveRiskSettings` | — (blur-saved) |
| `timezone` | Operator timezone | `OperatorTimezoneSection.handleSave` → `api.putSchedulingTimezone` (keep #404's load-failure guard) | `tz` vs baseline (load or save response) |
| `scan-run-retention` | Scheduled scan history retention | `api.saveScheduledScanRunRetention` | `days` vs baseline |
| `history-retention` | Trade history retention | `handleSaveRetention` → `saveHistoryRetention` | — (blur-saved) |
| `notifications` | Notifications | `handleSave` POST `/settings/notifications`, throwing on `!res.ok` | enabled/to/user/chat id vs loaded baseline, or a non-empty password/bot token |
| `broker:ibkr_paper`, `broker:tradier_paper`, `broker:tradier_live`, `broker:alpaca_paper`, `broker:tastytrade_paper` | "<Broker> credentials" | each `save*` → `api.postCredentials` | inputs vs the store's values |
| `schedule:ingestion`, `schedule:edgar`, `schedule:sp500`, `schedule:tuning` | Nightly OHLCV ingestion / EDGAR fundamentals / S&P 500 liquidity update / Strategy tuning schedule | `DataForm.handleSave`, `ScheduleSection.handleSave` (channel/label passed as props) | enabled/time/(days) vs baseline |
| `schedule-entry:<id>` | Scheduled scan "<label>" | `ScheduledScansSection.updateEntry` | — (blur/change-saved) |
| `strategy:<field>` | the override's label | — | `OverrideInput` holds a validation error (an invalid draft is not stored, #373) |
| `iv-thresholds` | IV thresholds (session) | — | any IV input dirty and not applied |

Broker saves today have no `try/catch`: a rejected `postCredentials` is an unhandled rejection and leaves the button on "Saving…" forever. Add `try/catch/finally` so `setSaving(null)` always runs, and show "Save failed" next to that broker's button on failure (cleared on its next attempt). The local-store write before the POST stays where it is.

Local blur-commit fields (scan caps, confidence/fundamentals gates, ATR pairs, spreads, Markov, density, theme, backtest thresholds) need no channel: their commit is a store write, covered by B.

## Tickets (sequential)

**T1 — ledger + reporting storage** (`frontend/lib/settingsSaveStatus.ts`, `frontend/lib/reportingLocalStorage.ts`, `settingsStore.ts`, `theme.ts`, `riskStore.ts`, `scanParamsStore.ts`, new tests under `frontend/lib/__tests__/`). Tests first: latest-attempt-wins in both orders; rethrow/return passthrough; `settleAll` awaits attempts started while waiting; draft set/clear; for each of the four stores and each of `QuotaExceededError` and `SecurityError`: memory changes, raw bytes stay old, failure recorded, error still thrown, a later successful write clears it, `retryLocalWrites` writes the pending bytes and clears it; keys, versions and serialized shape unchanged (existing persistence tests stay green).

**T2 — footer + risk + timezone + local + drafts that need no new backend wiring** (`page.tsx`, tests in `frontend/app/(frame)/settings/__tests__/`; blocked by T1). Reproduce the three defect cases first (red), with `userEvent` or explicit blur-then-click: risk 500 → no "Saved", "Risk limits" listed, captured POST payload 234567, then a successful re-blur → footer "Saved"; risk POST still pending at click → "Saving…", then the real outcome; timezone draft → zero PUTs, listed, then its own Save → PUT captured, footer "Saved"; theme / Markov / confidence storage throws (both types) → listed, raw bytes old, once storage stops throwing, a footer click retries the write and reports "Saved" with the bytes now new, and a remount/reload readback shows the stored value. Strategy-override invalid draft and IV dirty draft are listed. The message clears when the outstanding list empties.

**T3 — remaining backend channels** (`page.tsx`, tests; blocked by T2, same file). Wire scan-run retention, trade-history retention, notifications, the five broker forms (with the try/catch fix), the four schedules and schedule-entry updates. Per channel: failed save listed, success clears, draft listed then cleared by its own Save, draft cleared on unmount. Broker: a rejected POST no longer leaves "Saving…", shows "Save failed".

Each ticket: Python not needed; `cd frontend && npm run typecheck` and full `npm run test` green before commit. Synthetic fixtures, mocked API, jsdom storage only: no backend, jobs, broker calls or notifications.

## Verification and reviews

Plan stage: a fresh independent auditor per round applies `.claude/skills/bmad-review-adversarial-general/SKILL.md` to this plan against the real code, gate verbatim from `audit_rule`. Round 1 of this stage is already counted (an earlier, never-pushed plan by another agent reportedly had one review; its record is unrecoverable, counted conservatively), so at most two more plan rounds. Tickets are cut only after a clean plan round.

Code stage: after T3 closes, `git merge origin/main`, rerun typecheck + full Jest, then a fresh auditor reviews `origin/main..<branch>`; later rounds review only fixes; cap 3. Records in `PROJECT_STATE.json` and comments on #371. Status `built` until a verified merge; self-merge only under `board.md` step 7.

Manual browser check: the Jest suites drive the real stores against jsdom `localStorage` and capture every API call, which is the regression evidence. A live-browser check of the three scenarios needs a backend whose `/settings/risk` can be made to fail and a browser with full storage; if not run, it is listed as not done in the PR.

Milestones: 20% plan approved; 50% T1–T3 built; 70% acceptance + local checks; 85% code audit clean; 95% exact-head CI / pre-merge record; 100% verified merge.
