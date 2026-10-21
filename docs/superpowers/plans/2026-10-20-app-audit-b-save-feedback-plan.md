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

- `trackSave<T>(channel, label, run: () => Promise<T>): Promise<T>` — synchronously, before `run` is awaited, increments the channel's attempt sequence and records it in flight with its promise. `run` must contain **every step of that save which precedes the request and can stop it from being sent** (e.g. a broker's store write before its POST), so a throw anywhere before or in the request is a failed attempt (plan round 2 F3). Steps that run only after the request succeeded (e.g. Risk's store writes after its POST) stay outside `run`; their storage failures are reported by B. A synchronous throw inside `run` is a rejection of that attempt. On settle, latest-attempt outcome updates apply **only if that attempt is still the channel's latest**; every attempt is nevertheless removed from the all-pending registry when it settles. Rejection records `failed` with a short message. Success clears records only under the confirmation rules in A1 below; ignoring an older outcome is not proof of the final server value. The original result/rejection is returned/re-thrown unchanged so each section's existing handling keeps working. A section whose request resolves with a non-OK response (notifications uses raw `fetch`) passes a `run` that throws on `!res.ok`.
- `setDraft(channel, label, dirty: boolean)` — records or clears an unsubmitted edit while its section is mounted.
- `discardDraft(channel)` — called from the section's unmount cleanup (sections mount only while their subnav item is active, `page.tsx:80-88`, while the footer stays mounted): if the channel has a live draft, it becomes a persistent `discarded` record ("edit discarded when you left the section — not saved"). A `discarded` record stores the channel's attempt sequence at discard time. Nothing else clears it except: a successful latest `trackSave` attempt **that began after the discard and with no older attempt for that channel still pending** (an attempt already in flight when the section was left cannot clear it; overlapping later attempts are unconfirmed under A1 — R3-F1/R4-F1); for the local-commit channels without a request (`strategy:<field>`, `iv-thresholds`), a later successful commit of that field (valid store write or clear) / Apply or Reset, via `clearDiscarded(channel)`; or a page reload. A new live draft on a channel replaces its `discarded` record while the section is mounted and becomes `discarded` again if left dirty (plan round 2 F1).
- Browser-storage failures (fed by B): `failed` per storage key, holding the last serialized value whose write failed.
- `settleAll(): Promise<void>` — awaits every in-flight promise, looping until none is in flight (an attempt started while waiting is also awaited).
- `retryLocalWrites(): void` — for each failed storage key, `localStorage.setItem(key, pendingValue)`; success clears it, a throw keeps it failed.
- `outstanding(): { channel, label, kind: 'failed' | 'draft' | 'discarded' | 'unconfirmed' | 'local', message }[]` — what the footer lists.

A failed backend save stays recorded until a later attempt on the same channel succeeds or the page reloads, even if the section unmounts or its remount re-fetches the server value: the operator's edit was not saved, and that remains true.

### A1. Overlapping backend saves are unconfirmed (R4-F1 correction)

Keep every in-flight attempt promise in a per-channel registry until it settles, including superseded attempts; `settleAll` awaits all of them, not only the latest. No request is serialized, cancelled, retried or submitted automatically: existing section callback order is preserved.

At `trackSave` entry, synchronously read whether **any older attempt for this channel is still pending**, then assign/register the new sequence. If one is pending, record a persistent `unconfirmed` marker for this channel immediately. Completion order is not commit-order proof: even a latest response received last may represent a write committed before an older pending write. Therefore **any** such overlap stays unconfirmed in either completion order.

A latest successful attempt clears `failed` and `unconfirmed` only if it began with **no older same-channel attempt pending**. It clears `discarded` only if that condition holds **and** its sequence is strictly greater than the sequence stamped at discard. An earlier attempt that settles later can clean its own pending-registry entry but cannot clear these records. A successful overlapping latest attempt retains the unconfirmed marker even after all requests finish. A new live draft may replace a discarded record, but neither draft updates, remount GET/readback, local-write retry, nor `clearDiscarded` clears unconfirmed backend state. That requires a later successful latest save started after all earlier same-channel promises settled. This is conservative confirmation reporting; it does not rewrite server values or issue another request on the user's behalf.

The footer reports `unconfirmed` as "<label>: latest save not confirmed — save or re-enter this setting again". After `settleAll`, the warning remains until the operator performs that new section/field save; a subsequent footer click may then report Saved. The in-flight registry is independent from latest-result and draft records, so unmount/remount cannot erase the older attempts.

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
  - `discarded` → "<label>: edit discarded when you left the section — not saved"
  - `unconfirmed` → "<label>: latest save not confirmed — save or re-enter this setting again"
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
| `broker:ibkr_paper`, `broker:tradier_paper`, `broker:tradier_live`, `broker:alpaca_paper`, `broker:tastytrade_paper` | "<Broker> credentials" | the whole `save*` body: the store write (`setIbkrPaper` etc.) **and** `api.postCredentials`, so a storage throw before the POST is a failed attempt (round 2 F3) | inputs vs the store's values |
| `schedule:ingestion`, `schedule:edgar`, `schedule:sp500`, `schedule:tuning` | Nightly OHLCV ingestion / EDGAR fundamentals / S&P 500 liquidity update / Strategy tuning schedule | `DataForm.handleSave`, `ScheduleSection.handleSave` (channel/label passed as props) | enabled/time/(days) vs baseline |
| `schedule-entry:<id>:<field>` (one channel per key in the patch; a pattern change's patch covers `pattern`, `fire_time`, `cadence_minutes`, `window_start_hour`, `window_end_hour`) | Scheduled scan "<label>" <field> | `ScheduledScansSection.updateEntry`, one `trackSave` per patched key sharing the single PUT, so a success on another field never clears this field's failure (round 2 F2) | `schedule-entry:<id>:label` draft = the row's `label` input ≠ `entry.label`; `schedule-entry:<id>:enabled` draft = the row's displayed toggle state ≠ `entry.enabled` (the row tracks it from `Toggle.onChange` and re-syncs it when `entry.enabled` changes, mirroring `Toggle`'s own effect). Both evaluated only while no attempt for that entry is in flight. The other row controls render `entry.*` directly, so a failed PUT already shows the server value again. |
| `strategy:<field>` | the override's label | — | `OverrideInput` holds a validation error (an invalid draft is not stored, #373) |
| `iv-thresholds` | IV thresholds (session) | — | any IV input dirty and not applied |

Broker saves today have no `try/catch`: a rejected `postCredentials` is an unhandled rejection and leaves the button on "Saving…" forever. Add `try/catch/finally` so `setSaving(null)` always runs, and show "Save failed" next to that broker's button on failure (cleared on its next attempt). The local-store write before the POST stays where it is, inside the tracked `run`.

Local blur-commit fields (scan caps, confidence/fundamentals gates, ATR pairs, spreads, Markov, density, theme, backtest thresholds) need no channel: their commit is a store write, covered by B.

## Tickets (sequential)

**T1 — ledger + reporting storage** (`frontend/lib/settingsSaveStatus.ts`, `frontend/lib/reportingLocalStorage.ts`, `settingsStore.ts`, `theme.ts`, `riskStore.ts`, `scanParamsStore.ts`, new tests under `frontend/lib/__tests__/`). Tests first: latest-attempt-wins in both orders; rethrow/return passthrough; `settleAll` awaits attempts started while waiting; draft set/clear; overlapping same-channel saves retain unconfirmed in both completion orders, a late superseded attempt remains awaited by `settleAll`, remount/draft/local-retry cannot clear it, and only a later successful latest save begun without older pending attempts clears it; for each of the four stores and each of `QuotaExceededError` and `SecurityError`: memory changes, raw bytes stay old, failure recorded, error still thrown, a later successful write clears it, `retryLocalWrites` writes the pending bytes and clears it; keys, versions and serialized shape unchanged (existing persistence tests stay green).

**T2 — footer + risk + timezone + local + drafts that need no new backend wiring** (`page.tsx`, tests in `frontend/app/(frame)/settings/__tests__/`; blocked by T1). Reproduce the three defect cases first (red), with `userEvent` or explicit blur-then-click: risk 500 → no "Saved", "Risk limits" listed, captured POST payload 234567, then a successful re-blur → footer "Saved"; risk POST still pending at click → "Saving…", then the real outcome; timezone draft → zero PUTs, listed, then its own Save → PUT captured, footer "Saved"; theme / Markov / confidence storage throws (both types) → listed, raw bytes old, once storage stops throwing, a footer click retries the write and reports "Saved" with the bytes now new, and a remount/reload readback shows the stored value. Strategy-override invalid draft and IV dirty draft are listed. Late attempt (R3-F1): timezone Save in flight, type another value, switch section, the in-flight PUT succeeds → the footer still lists the timezone as discarded (same for a broker form). Discard (round 2 F1): edit the timezone, switch to another subnav section, click the footer → "Not saved" with the timezone listed as discarded and zero PUTs; return and save the timezone → cleared. Same for an invalid strategy-override draft (cleared by a later valid commit or clear of that field) and an IV draft (cleared by Apply/Reset). The message clears when the outstanding list empties.

**T3 — remaining backend channels** (`page.tsx`, tests; blocked by T2, same file). Wire scan-run retention, trade-history retention, notifications, the five broker forms (with the try/catch fix), the four schedules and schedule-entry updates. Per channel: failed save listed, success clears, draft listed then cleared by its own Save, a draft left behind on section switch listed as discarded until that channel's next successful save. Broker: a rejected POST no longer leaves "Saving…", shows "Save failed"; the store write throws (both exception types) → no POST, broker listed as failed; storage recovers and the footer retries the local write → the broker is **still** listed until its own Save succeeds (round 2 F3). Schedule entry (round 2 F2): a failed enable PUT followed by a successful fire-time PUT → the enable failure is still listed; a label blur and a toggle click whose PUTs both succeed but leave the server with the stale value of one field → that field is listed as an unsaved edit after refresh.

**R4-F1 deferred-commit regression (T3, retention channel):** Start server/display90; submit120 as attempt1, keep its server write deferred; edit180 then leave the section (discard sequence1). Remount/read90, Save90 as attempt2 while1 remains pending. Exercise both completion/commit orders, including2 committing90 then1 committing120. After every promise settles, footer must say Not saved with the retention label and unconfirmed status; displayed90/server120 must never be certified Saved. Keep attempt1 in `settleAll` after2 settles. Neither GET on remount, a draft update, nor local-storage retry clears this status. Once both requests settle, explicitly Save90 again as attempt3: capture the actual request, server/display90, then footer Saved. This is a frozen mocked server/transport model, no live jobs/provider calls.

Each ticket: Python not needed; `cd frontend && npm run typecheck` and full `npm run test` green before commit. Synthetic fixtures, mocked API, jsdom storage only: no backend, jobs, broker calls or notifications.

## Verification and reviews

Plan stage: a fresh independent auditor per round applies `.claude/skills/bmad-review-adversarial-general/SKILL.md` to this plan against the real code, gate verbatim from `audit_rule`. Round 1 of this stage is already counted (an earlier, never-pushed plan by another agent reportedly had one review; its record is unrecoverable, counted conservatively). Round 2 (2026-10-20) found three gate findings (F1 discarded drafts, F2 shared schedule-entry channel, F3 broker store write outside the tracked attempt), fixed above. Round 3 (2026-10-20, the last allowed round) found one gate finding (R3-F1: an in-flight attempt finishing after a discard cleared the discarded record); its fix is written above but **unaudited** — the plan stage reached its three-round cap without a clean round, so no tickets are cut until Kenneth opens a new plan stage. Tickets are cut only after a clean plan round.

Code stage: after T3 closes, `git merge origin/main`, rerun typecheck + full Jest, then a fresh auditor reviews `origin/main..<branch>`; later rounds review only fixes; cap 3. Records in `PROJECT_STATE.json` and comments on #371. Status `built` until a verified merge; self-merge only under `board.md` step 7.

Manual browser check: the Jest suites drive the real stores against jsdom `localStorage` and capture every API call, which is the regression evidence. A live-browser check of the three scenarios needs a backend whose `/settings/risk` can be made to fail and a browser with full storage; if not run, it is listed as not done in the PR.

Milestones: 20% plan approved; 50% T1–T3 built; 70% acceptance + local checks; 85% code audit clean; 95% exact-head CI / pre-merge record; 100% verified merge.

## Authorized second plan stage (2026-10-21)

Owner response ["ok with both recommendations"](https://github.com/Netke237/trading-assistant/issues/371#issuecomment-6307656780) accepts the new plan-review stage and report-only footer contract. The original three plan rounds remain capped/nonclean and are preserved, including the conservatively counted unrecoverable first round. Stage2 has cap3, continuous plan rounds4–6. Its first review examines the R3-F1 correction (discard sequence versus in-flight attempt sequence) and interactions against current main `a1811c0e`, including newer Settings save/schedule feedback changes. No code or tickets until a clean plan round. The original interval closes at3 by the verified new-stage authorization decision, retaining clean:false and its cap history. Once the first new-stage review runs, record cumulative plan_stages; no earlier counter is reset. This does not authorize a fourth review of the old stage.
