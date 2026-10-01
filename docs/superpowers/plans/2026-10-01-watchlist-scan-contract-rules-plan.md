# WATCHLIST-SCAN-CONTRACT-RULES — plan (r1, not yet reviewed)

- **Phase:** `WATCHLIST-SCAN-CONTRACT-RULES` (PROJECT_STATE.json), deferred by `STEP6-SCAN-CONTRACT-RULES`.
- **Branch:** `claude/youthful-carson-82x23x` (off main at the DOCC-5 merge).
- **Design decision (Kenneth, 2026-10-01):** store the rules with the star. Rejected alternative: leave the
  data alone and have the Watchlist say it grades on contract_rules.yaml.

## 1. What is true on main

1. `GET /api/contracts` grades with `validate_contract(augmented, stock_score, overrides=...)`. What the
   result depends on is `stock_score` (default 70), `contract_rules` (JSON; absent = the YAML), and
   `hold_min_days`/`hold_max_days`. Hold days set both the chain's DTE window and the widened DTE overrides.
   `direction` and `horizon` are accepted but not used for grading. `limit` (default 10) and `max_price`
   (default 50) cut the list after scoring.
2. Step 6 (`step-6-contracts/page.tsx:116-141`) sends `stock_score` = the candidate's `stockScore ?? 70`, the
   scan's own `contract_rules` (`scanResult.contract_rules ?? undefined`), hold days from
   `sanitizeHoldDays(context.holdMin, context.holdMax)`, plus `limit`/`max_price` from settings.
   `ContractStar` (`:263`) stores only the id.
3. `watchedContractsStore` (persist key `bamendjou-watched-contracts-v1`, version 2) holds `ids: string[]`.
   `syncFromBackend` replaces `ids` from `GET /api/watched-contracts` (`list[str]`).
4. Backend `watched_contracts` table: `id`, `contract_id` (unique), `created_at`. `POST` takes `{contract_id}`,
   is idempotent, and leaves an existing row alone. `DELETE /{contract_id:path}` is idempotent. Tables come
   from `create_all()`, which does not add columns to an existing table, so a new column needs an Alembic
   migration. The single head is `f3d5c81b0a47`.
5. Watchlist (`watchlist/page.tsx:99-127`) makes one `api.getContracts(sym, right, undefined, signal)` per
   (symbol, right) and matches each stored id against the flat result. This is the **defect marker**. It
   uses the default `limit` 10, so a low-scoring starred contract can be cut and never shown.

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
`contract_rules: {}` means "the scan ran on the YAML" and grades the same as the YAML. `null` means "we do
not know the scan's rules".

### 2.2 Backend

1. Model: `grading = Column(JSON, nullable=True)` on `WatchedContractModel`. Nullable, no default, no
   backfill. NULL = starred before this change; that is a real state, not a missing value.
2. Migration `<new>_add_grading_to_watched_contracts.py`: `down_revision = 'f3d5c81b0a47'`, adds the column,
   and the downgrade drops it. The docstring repeats the create_all point (adding the column to the model
   without the migration makes every GET on a live DB 500).
3. Router:
   - `ContractGradingModel` (pydantic): `contract_rules: dict[str, float] | None` (every value finite, not
     bool; unknown keys kept, because `/api/contracts` ignores them anyway); `hold_min_days`/`hold_max_days:
     int | None, ge=0`, both or neither, max >= min; `stock_score: int | None, 0..100`. Invalid input gets 422.
   - `POST /api/watched-contracts` takes optional `grading`. New row: store it. Existing row: unchanged, as
     today. (A star toggles, so re-starring always goes through DELETE first. Stated: a second POST for a row
     that exists does not refresh its grading.)
   - `GET /api/watched-contracts` keeps returning `list[str]` (no change to its shape).
   - New `GET /api/watched-contracts/detail` returns `list[{contract_id, grading | null}]` in `created_at`
     order. A stored grading that no longer validates (hand-edited DB) is served as `null`, never a 500.

### 2.3 Frontend

1. `types/domain.ts`: export `ContractGrading`.
2. `lib/api.ts`: `addWatchedContract(id, grading?)` sends `grading` only when given;
   `getWatchedContractsDetail()`.
3. `watchedContractsStore`: new persisted `grading: Record<string, ContractGrading>`. `version` 2 -> 3;
   `migrate` v<3 sets `grading: {}` and keeps `ids`. `add(id, grading?)` records grading when given;
   `remove`/`toggle` drop the id's grading. `syncFromBackend` reads `/detail` and replaces `ids` and `grading`
   together. If `/detail` fails, it falls back to today's `GET /api/watched-contracts` for ids and keeps the
   local grading for ids that are still present. `partialize` persists both fields.
4. `ContractStar`: optional `grading?: ContractGrading` prop, passed to `add` and `api.addWatchedContract`.
   The rollback on POST failure is unchanged.
5. Step 6: one `gradingFor(symbol)` built from the same values `loadContracts` sends (contract_rules
   `?? null`, sanitized hold, `stockScoreBySymbol[symbol] ?? 70`), passed to `<ContractStar grading=…>`.
   Shared code: `loadContracts` and `gradingFor` both read one memoised helper, so the two cannot drift.
6. Watchlist `refreshContracts`:
   - Group ids by `(symbol, right, gradingKey)`, where `gradingKey = stableStringify(grading) | ''`. One
     `getContracts` per group, with ctx `{ stock_score, hold_min_days, hold_max_days, contract_rules (only
     when non-null), limit: 100 }`. A group with no grading sends `{ limit: 100 }` only, which is today's
     request apart from the limit.
   - Results are kept per group. Each stored id is matched only against its own group's result, using
     today's exact match and then today's strike-rounding fallback. The same contract can be returned by two
     groups, so a flat match would pick the wrong grade.
   - `limit: 100` (the endpoint's max) because the Watchlist fetches only to find starred contracts, and the
     default 10 can cut the starred one (2.5 below has the residual).
7. Watchlist Contracts tab: a row whose grading is absent or has `contract_rules === null` shows a dim
   caution note in its status tooltip / a small marker: "Graded on contract_rules.yaml — starred before the
   scan's rules were saved (or the scan recorded none)". A row with recorded rules shows no marker. The tab
   header shows no global note.

### 2.4 Behaviour changes (stated)

- A contract starred in Step 6 from now on shows the same score/status in the Watchlist as Step 6 showed,
  given the same market data.
- Old stars (and stars whose scan recorded no rules) still grade on the YAML, now marked as such.
- The Watchlist asks for up to 100 contracts per group instead of 10. Same endpoint and same chain fetch;
  only more rows are serialised.
- `stock_score` is a snapshot from star time. The Watchlist does not re-score the stock. That matches "grade
  as the scan did".

### 2.5 Residuals (logged, not fixed)

1. `max_price` (default 50) can still drop a starred contract priced above $50. The scan applies no price cap.
   Same class as STEP6 deferred item (3).
2. A contract starred on a device whose POST failed is rolled back, as today. No retry queue.
3. Stars made from another device before this ships stay grading-less until unstarred and re-starred.

## 3. Tests (each with the mutation it must kill)

Backend `tests/test_watched_contracts_grading.py` (in-memory sqlite, as the existing router tests do):
1. POST with grading -> `/detail` returns it verbatim. *Kills: not storing grading.*
2. POST without grading -> `/detail` grading null; `GET /api/watched-contracts` still `list[str]`. *Kills:
   breaking the old shape.*
3. POST twice (second with a different grading) -> the first is kept. *Pins the stated idempotency.*
4. 422 on: non-finite/bool rule value, hold max < min, only one hold bound, stock_score 101. *Kills a missing
   validator.*
5. Hand-written invalid grading in the row -> `/detail` serves null, 200. *Kills a 500 on bad rows.*
6. Migration file: `down_revision == 'f3d5c81b0a47'` and it adds `grading` (static parse, as other migration
   tests do if present; else an import + attribute check).

Frontend:
7. `watchedContractsStore.test.ts`: migrate v2 -> v3 adds `grading: {}` and keeps ids; `add(id, g)` stores
   g; `remove` drops it; `syncFromBackend` replaces both from `/detail`, and on `/detail` failure falls back
   to ids and keeps the surviving local grading.
8. `ContractStar` test: click with grading -> `api.addWatchedContract(id, grading)` and the store holds it.
9. Step 6 page test: clicking the row star stores grading equal to the ctx `getContracts` was called with
   (contract_rules, hold, stock_score). *Kills drift between the two.*
10. Watchlist page test (extends `__tests__/page.test.tsx`):
    a. A starred id with grading -> `getContracts` is called with that ctx (contract_rules, hold days,
       stock_score, limit 100). *Kills the defect marker staying.*
    b. Two stars on the same symbol/right with different gradings -> two calls; each row shows its own
       group's score even when both groups return the same contract id. *Kills flat matching.*
    c. A star with no grading -> called with `{ limit: 100 }` and no contract_rules, and the YAML marker is
       shown; a star with rules shows no marker.

Gates: `npm run typecheck`, Jest full, backend pytest full, `python3 scripts/state.py` exit 0.
PROJECT_STATE: the phase verify becomes a presence probe for the grouped call (the defect marker is gone).
