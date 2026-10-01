# WATCHLIST-SCAN-CONTRACT-RULES — plan (r2; plan round 1 NOT clean: 1 blocking + 4 should-fix + 9 nits, all addressed below)

- **Phase:** `WATCHLIST-SCAN-CONTRACT-RULES` (PROJECT_STATE.json), deferred by `STEP6-SCAN-CONTRACT-RULES`.
- **Branch:** `claude/youthful-carson-82x23x` (off main at the DOCC-5 merge).
- **Design decision (Kenneth, 2026-10-01):** store the rules with the star. Rejected alternative: leave the
  data alone and have the Watchlist say it grades on contract_rules.yaml.

## 1. What is true on main

1. `GET /api/contracts` grades with `validate_contract(augmented, stock_score, overrides=...)`. What the
   result depends on is `stock_score` (default 70), `contract_rules` (JSON; absent = the YAML), and
   `hold_min_days`/`hold_max_days`. Hold days set both the chain's DTE window and the widened DTE overrides.
   `direction` and `horizon` are accepted but not used for grading. `max_price` (default 50) drops rows
   BEFORE scoring (`contracts.py:236-241`); `limit` (default 10) cuts after scoring.
   The chain fetch is for ONE expiry (`market.py` `fetch_option_chain_async`): with hold days, the listed
   expiry nearest the centre of today's DTE window; without them, the first expiry >= 21 days out. It
   honours an explicit `expiry` argument when that date is listed, but `/api/contracts` never passes one.
   Stored rules are a DELTA on the live `contract_rules.yaml` (`scan.py:1718` records only overridden keys;
   `validate_contract` applies them on a fresh `_load_config()`, `contract_validator.py:405-407`).
2. Step 6 (`step-6-contracts/page.tsx:116-160`) sends `stock_score` = the candidate's `stockScore ?? 70`, the
   scan's own `contract_rules` (`scanResult.contract_rules ?? undefined`), hold days from
   `sanitizeHoldDays(context.holdMin, context.holdMax)` (only when both are non-null), plus `limit`/`max_price` from settings.
   `ContractStar` (`:263`) stores only the id.
3. `watchedContractsStore` (persist key `bamendjou-watched-contracts-v1`, version 2) holds `ids: string[]`.
   `syncFromBackend` replaces `ids` from `GET /api/watched-contracts` (`list[str]`).
4. Backend `watched_contracts` table: `id`, `contract_id` (unique), `created_at`. `POST` takes `{contract_id}`,
   is idempotent, and leaves an existing row alone. `DELETE /{contract_id:path}` is idempotent. Tables come
   from `create_all()`, which does not add columns to an existing table, so a new column needs an Alembic
   migration. The single head is `f3d5c81b0a47`.
5. Watchlist (`watchlist/page.tsx:99-127`) makes one `api.getContracts(sym, right, undefined, signal)` per
   (symbol, right) and matches each stored id against the flat result. This is the **defect marker**.
   An id it cannot match is silently dropped (`:183-199`). Three things make a star vanish today: the
   default `limit` 10; the default `max_price` 50 (Step 6 sends the user's `maxContractPrice`); and the
   single-expiry fetch, whose window-centre expiry moves with today's date, so a star's fixed expiry stops
   being fetched within days to weeks.

## 2. Design

### 2.1 What is stored: `ContractGrading`

```ts
interface ContractGrading {
  contract_rules: Record<string, number> | null; // null = the scan recorded none (older result / unrecordable)
  hold_min_days:  number | null;                 // both set or both null
  hold_max_days:  number | null;
  stock_score:    number | null;                 // 0-100 int; null -> backend default 70
}
```

These are exactly the grading inputs Step 6 sent for that row at the moment the star was clicked.
`contract_rules: {}` means "the scan overrode nothing". `null` means "we do not know the scan's rules".
Both are deltas on the YAML in force when the Watchlist is viewed, exactly as Step 6 and the scan apply
them (residual 2.5.4). The contract's expiry is not part of `ContractGrading`: it is already in the id.

### 2.2 Backend

1. Model: `grading = Column(JSON(none_as_null=True), nullable=True)` on `WatchedContractModel`
   (`none_as_null` so a Python None is SQL NULL, not JSON `null`). Nullable, no default, no backfill.
   NULL = starred before this change, or starred without grading; a real state, not a missing value.
2. Migration `<new>_add_grading_to_watched_contracts.py`: `down_revision = 'f3d5c81b0a47'`, adds the column,
   and the downgrade drops it. The docstring repeats the create_all point (adding the column to the model
   without the migration makes every GET on a live DB 500).
3. Router:
   - `ContractGradingModel` (pydantic): `contract_rules: dict[str, StrictInt | StrictFloat] | None` plus a
     validator rejecting bool and non-finite values (pydantic lax mode would coerce `True` and `"5"`, and
     `/api/contracts` 422s on anything but a finite JSON number, which would break that Watchlist group);
     unknown keys kept, as `/api/contracts` ignores them; `hold_min_days`/`hold_max_days: StrictInt | None,
     ge=0`, both or neither, max >= min; `stock_score: StrictInt | None, 0..100`. Invalid input gets 422.
   - `POST /api/watched-contracts` takes optional `grading`. New row: store it. Existing row: unchanged, as
     today. (A star toggles, so re-starring always goes through DELETE first. Stated: a second POST for a row
     that exists does not refresh its grading.)
   - `GET /api/watched-contracts` keeps returning `list[str]` (no change to its shape).
   - `GET /api/contracts` gains `expiry: str | None = Query(None)`, forwarded to
     `fetch_option_chain_async(expiry=...)`. When `expiry` is given, the response keeps only rows whose
     `expiry` equals it (the fetch falls back to the window/default expiry when the date is not listed,
     e.g. expired; those rows are not the star's and must not be returned). Grading is unchanged: the same
     hold-widened overrides apply to the explicit expiry, so the score matches Step 6's for that contract.
     Absent = today's behaviour exactly.
   - New `GET /api/watched-contracts/detail` returns `list[{contract_id, grading | null}]` in `created_at`
     order. A stored grading that no longer validates (hand-edited DB) is served as `null`, never a 500.

### 2.3 Frontend

1. `types/domain.ts`: export `ContractGrading`.
2. `lib/api.ts`: `addWatchedContract(id, grading?)` sends `grading` only when given;
   `getWatchedContractsDetail()`; `getContracts` ctx gains `expiry?: string`.
3. `watchedContractsStore`: new persisted `grading: Record<string, ContractGrading>`. `version` 2 -> 3;
   `migrate` v<3 sets `grading: {}` and keeps `ids`. `add(id, grading?)` records grading when given;
   `remove` drops the id's grading. `toggle` is unused in the app (grep) and is REMOVED, so it cannot
   become a grading-less star path. `syncFromBackend` reads `/detail` and replaces `ids` and `grading`
   together. If `/detail` fails, it falls back to today's `GET /api/watched-contracts` for ids and keeps the
   local grading for ids that are still present. `partialize` persists both fields.
4. `ContractStar`: optional `grading?: ContractGrading` prop, passed to `add` and `api.addWatchedContract`.
   Unstar captures `prev = grading[id]` before `remove`, and a failed DELETE rolls back with
   `add(id, prev)`, so the grading survives. POST-failure rollback (`remove`) unchanged.
5. Step 6: one `gradingFor(symbol)` built from the same values `loadContracts` sends (contract_rules
   `?? null`, sanitized hold, `stockScoreBySymbol[symbol] ?? 70`), passed to `<ContractStar grading=…>`.
   Shared code: `loadContracts` and `gradingFor` both read one memoised helper, so the two cannot drift.
6. Watchlist `refreshContracts`:
   - Group ids by `(symbol, right, expiry, gradingKey)`, where `gradingKey` is a stable stringify of the
     REQUEST the grading produces (so `contract_rules: {}` and `null`, which send the same request, share a
     key), '' for none. One `getContracts` per group, with ctx `{ expiry, stock_score, hold_min_days,
     hold_max_days, contract_rules (only when non-empty), limit: 100, max_price: 500 }`. A group with no
     grading sends `{ expiry, limit: 100, max_price: 500 }`.
   - `refreshContracts`' `useCallback` depends on `[watchedIds, grading]`, so a grading change refetches.
   - Results are kept per group. Each stored id is matched only against its own group's result, using
     today's exact match and then today's strike-rounding fallback. The same contract can be returned by two
     groups, so a flat match would pick the wrong grade.
   - `limit: 100` and `max_price: 500` (the endpoint's maxima) because the Watchlist fetches only to find
     starred contracts; neither affects grading. With `expiry` set the result is one expiry's strikes, so
     100 covers it in practice.
   - A starred id with no match in its group's result (expired, delisted, or a group fetch that failed)
     is no longer dropped: it renders a row with the id's label, status `NO_DATA`, dashes for market
     fields, and the note "Not in the current chain (expired or not listed)". A failed group fetch does not
     blank the other groups' rows (per-group `Promise.allSettled`); `offline` is set only when every group
     failed, as today when the single batch failed.
7. Watchlist Contracts tab: a row whose grading is absent or has `contract_rules === null` shows a dim
   caution note in its status tooltip / a small marker: "Graded on contract_rules.yaml — starred before the
   scan's rules were saved (or the scan recorded none)". A row with recorded rules shows no marker. The tab
   header shows no global note.

### 2.4 Behaviour changes (stated)

- A contract starred in Step 6 from now on is graded in the Watchlist with the same inputs Step 6 used,
  so it shows the score/status Step 6 would show for it today (same market data, same YAML). Starred
  contracts no longer vanish from the tab: they stay listed until their expiry, then show as not in chain.
- Old stars (and stars whose scan recorded no rules) still grade on the YAML, now marked as such.
- The Watchlist asks for the star's own expiry, up to 100 rows, no effective price cap. One chain request
  per (symbol, right, expiry, grading) group instead of per (symbol, right): more requests when a user
  stars several expiries of one name.
- `stock_score` is a snapshot from star time. The Watchlist does not re-score the stock. That matches "grade
  as the scan did".

### 2.5 Residuals (logged, not fixed)

1. A contract starred on a device whose POST failed is rolled back, as today. No retry queue.
2. Stars made before this ships (backend row NULL; local v2 data migrates to `grading: {}`) stay
   grading-less, marked as YAML-graded, until unstarred and re-starred from Step 6.
3. DELETE and POST are fired without awaiting each other; a fast unstar/re-star can reach the server out of
   order, leaving no row or the old grading. Pre-existing for ids; now it can also carry a stale grading.
4. Stored rules are a delta on the YAML in force at viewing time, as everywhere else; an edit to
   `contract_rules.yaml` (or the DTE multiplier/tolerance) after starring changes the Watchlist grade, with
   no marker. A full config snapshot was rejected as out of proportion.
5. Step 6's own `max_price`/`limit` cut (STEP6 deferred item 3) is unchanged.

## 3. Tests (each with the mutation it must kill)

Backend `tests/test_watched_contracts_grading.py` (in-memory sqlite, as the existing router tests do):
1. POST with grading -> `/detail` returns it verbatim. *Kills: not storing grading.*
2. POST without grading -> `/detail` grading null; `GET /api/watched-contracts` still `list[str]`. *Kills:
   breaking the old shape.*
3. POST twice (second with a different grading) -> the first is kept. *Pins the stated idempotency.*
4. 422 on: non-finite/bool rule value, hold max < min, only one hold bound, stock_score 101. *Kills a missing
   validator.*
4b. Numeric-string rule value (`"5"`) and bool (`true`) -> 422. *Kills lax pydantic coercion.*
5. Hand-written invalid grading in the row -> `/detail` serves null, 200. *Kills a 500 on bad rows.*
5b. POST without grading stores SQL NULL (`grading IS NULL` query finds it). *Kills JSON-null storage.*
6. Migration: `down_revision == 'f3d5c81b0a47'`, and applying `upgrade()` via an Alembic `Operations`
   context on a sqlite DB that already has the old `watched_contracts` table adds `grading`; `downgrade()`
   removes it. *Kills a migration that does not add the column.*
6b. `tests/test_contracts_expiry.py` (or added to `test_step6_contract_rules.py`): `expiry` reaches
   `fetch_option_chain_async`; rows of another expiry are filtered out; absent `expiry` = unchanged call.
   *Kills not forwarding / not filtering.*

Frontend:
7. `watchedContractsStore.test.ts`: migrate v2 -> v3 adds `grading: {}` and keeps ids; `add(id, g)` stores
   g; `remove` drops it; `syncFromBackend` replaces both from `/detail`, and on `/detail` failure falls back
   to ids and keeps the surviving local grading — including after `persist.rehydrate()` from v3 storage
   (the store has `skipHydration`); `toggle` no longer exists.
8. `ContractStar` test: click with grading -> `api.addWatchedContract(id, grading)` and the store holds it;
   unstar whose DELETE rejects -> the id AND its grading are restored. *Kills a grading-less rollback.*
9. Step 6 page test: clicking the row star stores grading equal to the ctx `getContracts` was called with
   (contract_rules, hold, stock_score). *Kills drift between the two.*
10. Watchlist page test (extends `__tests__/page.test.tsx`):
    a. A starred id with grading -> `getContracts` is called with that ctx (expiry, contract_rules, hold
       days, stock_score, limit 100, max_price 500). *Kills the defect marker staying.*
    b. Two stars on the same symbol/right with different gradings -> two calls; each row shows its own
       group's score even when both groups return the same contract id. *Kills flat matching.*
    c. A star with no grading -> called with `{ expiry, limit: 100, max_price: 500 }` and no
       contract_rules, and the YAML marker is shown; a star with rules shows no marker.
    d. Two stars, same symbol/right/grading, different expiries -> two calls, both rows shown.
    e. A star absent from its group's result -> its "not in chain" row still renders; one group rejecting
       leaves the other group's rows visible.

Gates: `npm run typecheck`, Jest full, backend pytest full, `python3 scripts/state.py` exit 0.
PROJECT_STATE: the phase verify becomes a presence probe for the grouped call (the defect marker is gone).
