# Storage findings from source 4b1f6b86

All reproductions use mocked APIs and targeted browser storage exceptions as
described in `coverage.md`. These are product observations, not fixes. The
coordinator owns defect publication and independent review bookkeeping.

## S1 — failed Search Profile CRUD mutates memory despite unchanged saved data

For each of `QuotaExceededError` and `SecurityError`, seed the single synthetic
Storage baseline profile; inject a `setItem` failure on
`bamendjou:search-profiles`; then save a new profile, update the direction,
rename, or delete through Step3. All four actions mutate the real store before
the persistence exception. New/renamed/deleted dropdown entries remain visible;
reapplying the failed update reads Bearish from memory while the saved baseline
still contains Bullish. Reload restores the old saved profiles. No saved bytes
are corrupted in these eight cases, but the UI and effective applied profile
diverge from saved readback. See `profile-{save,update,rename,delete}-*` cases.

Expected: preserve the committed profile view on failed writes, or expose an
explicit unsaved draft/error state whose values cannot masquerade as saved
profiles. Retest CRUD for both exceptions, old raw bytes, memory/apply behavior,
and reload. Source: `frontend/lib/searchProfilesStore.ts`,
`frontend/components/organisms/SearchProfileBar/index.tsx`, and
`frontend/components/molecules/SaveProfileDialog/index.tsx`.

## S2 — local Settings falsely confirms failed browser writes (extends #371)

Set light theme, Markov lookback30, or confidence caution61 through Settings;
inject the matching key failure; change to dark/lookback45/caution72; click Save
changes. With both exceptions, displayed values change and the footer says
Saved while exact old bytes survive. Reload restores light/30/61. All six
cases are captured as `settings-{theme,markov,confidence}-*` with prior raw bytes
and attempted new bytes. The Save button is an unconditional local flash; it
does not verify or retry storage. This extends the prior false-Saved evidence
to browser-local writes, distinct from server-save failures.

Expected: failure leaves a clear unsaved/error state and cannot show Saved;
committed state must agree with readback. Retest both exception types for these
setters and successful subsequent recovery. Source:
`frontend/lib/settingsStore.ts`, `frontend/lib/theme.ts`, and
`frontend/app/(frame)/settings/page.tsx` (`SaveButton`).

## S3 — opening an unknown future profile store downgrades and discards data (extends #381)

Seed the current valid profile shape in a version9999 envelope with an unknown
state field `futureAuditSentinel`. Load Step3. The store immediately overwrites
the key with version5 and discards the sentinel. There is no compatible
migration for a newer schema; hydration alone destroys its version and unknown
state. `unknown-future-version` includes exact before and after bytes.

Expected: an older client leaves unknown newer data untouched and refuses or
explicitly handles unsupported data without silent downgrade. This is a
synthetic forward-version compatibility check, not a claim that version9999
exists in a released application. Retest opening, readback, and subsequent
CRUD while unknown-version data is present. Source:
`frontend/lib/searchProfilesStore.ts` migration and partialization.

## S4 — Appearance's advertised theme synchronization does not occur

Open two same-origin Settings tabs in one browser context. Set dark in one;
the other receives the native storage event and reads dark saved bytes but
continues to render light. The exact source promise is the Theme row in
`frontend/app/(frame)/settings/page.tsx:225`:
`hint="Persisted in localStorage; synced across tabs"`. The Appearance intro
and ThemeProvider comments about within-page store-to-DOM synchronization are
not the basis of this finding. The `process-restart-and-cross-tab` case captures
events and each tab's values. Process restart independently reads the persisted
theme correctly.

Expected: the second tab renders the persisted theme after the event. Source:
`frontend/components/ThemeProvider/index.tsx`, `frontend/lib/theme.ts`, and
Appearance text in Settings. Retest both directions and process restart.

## S5 — ordinary Settings edits in two tabs lose unrelated saved fields

Open two same-origin Settings tabs after setting lookback35 through the normal
Regime input. In the first tab, use that input to set lookback55. The second
still shows35 despite receiving the storage event. In the second tab's Scan
section, fill confidence caution with64 and blur. Its whole-store write
overwrites saved lookback55 with35, even though that edit only concerned
confidence. This reproduction uses ordinary UI interactions throughout; there
is no external importer, direct audit-harness storage write, or fault injection
in this case. Exact storage bytes and events are in
`process-restart-and-cross-tab`.

Expected integrity: an ordinary edit to confidence must preserve newer saved
Markov parameters or surface a conflict. This is a persisted-data lost-update
defect through normal two-tab UI use; it does not depend on an advertised merge
feature. The previously documented unsupported stale external-profile-import
case is a different flow. Source:
`frontend/lib/settingsStore.ts` whole-state persistence. Retest stale tabs
editing different fields and same-field conflicts without losing prior values.

## Passing failure boundary: supported restore importer

Both exception types abort on a backup write failure or on a primary key write
failure. The primary prior bytes remain exact in all cases. Primary-write
failure retains a readable exact backup; backup-write failure creates none.
The exception reaches the caller and the script prints no successful import.
No importer defect is claimed by this matrix.
