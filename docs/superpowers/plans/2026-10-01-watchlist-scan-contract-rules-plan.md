# WATCHLIST-SCAN-CONTRACT-RULES — plan (r11; round 1 NOT clean 1B/4S/9N; round 2 NOT clean 1B/4S/10N; round 3 NOT clean 0B/2S/10N; round 4 NOT clean 0B/6S/12N; round 5 NOT clean 0B/4S/9N; round 6 NOT clean 0B/1S/13N; round 7 NOT clean 0B/2S/5N; round 8 NOT clean 0B/1S/6N; round 9 NOT clean 0B/1S/7N; round 10 NOT clean 0B/1S/11N; all addressed below)

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
   `validate_contract` applies them on a fresh `_load_config()`, `contract_validator.py:411-413`).
2. Step 6 (`step-6-contracts/page.tsx:116-160`; `loadContracts` itself is 123-160) sends `stock_score` = the candidate's `stockScore ?? 70`, the
   scan's own `contract_rules` (`scanResult.contract_rules ?? undefined`), hold days from
   `sanitizeHoldDays(context.holdMin, context.holdMax)` (only when both are non-null), plus `limit`/`max_price` from settings.
   `ContractStar` (`:263`) stores only the id.
3. `watchedContractsStore` (persist key `bamendjou-watched-contracts-v1`, version 2) holds `ids: string[]`.
   `syncFromBackend` replaces `ids` from `GET /api/watched-contracts` (`list[str]`).
4. Backend `watched_contracts` table: `id`, `contract_id` (unique), `created_at`. `POST` takes `{contract_id}`,
   is idempotent, and leaves an existing row alone. `DELETE /{contract_id:path}` is idempotent. Live DBs are
   Alembic-managed; tests and ad-hoc bootstraps use `create_all()` (`database.py:33-35`), which does not add
   columns to an existing table, so a new column needs an Alembic migration. The single head is `f3d5c81b0a47`.
5. Watchlist (`watchlist/page.tsx:99-127`) makes one `api.getContracts(sym, right, undefined, signal)` per
   (symbol, right) and matches each stored id against the flat result. This is the **defect marker**.
   An id it cannot match is silently dropped (`:183-199`). Three things make a star vanish today: the
   default `limit` 10; the default `max_price` 50 (Step 6 sends the user's `maxContractPrice`); and the
   single-expiry fetch (the Watchlist sends no hold days, so it gets the first expiry >= 21 days out),
   whose expiry moves with today's date, so a star's fixed expiry stops
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
   - `ContractGradingModel` (pydantic): `contract_rules: dict[str, Any] | None` with a validator that, for
     every key in `CONTRACT_OVERRIDE_KEYS`, requires `is_finite_rule_value` (so `True`, `"5"`, NaN, huge ints
     422 — pydantic lax typing would coerce them), and DROPS unknown keys before storing (the scan records
     only override keys; `/api/contracts` ignores the rest). Exactly the acceptance rule of
     `_parse_contract_rules`. `hold_min_days`/`hold_max_days: StrictInt | None, ge=0`, both or neither,
     max >= min; `stock_score: StrictInt | None, 0..100`. Invalid input gets 422.
   - `POST /api/watched-contracts` takes optional `grading: ContractGradingModel | None`. Three request
     shapes, told apart by pydantic `model_fields_set`: field ABSENT -> new row stores SQL NULL, existing
     row untouched; `"grading": {...}` -> stored (new row) or overwrites (existing row); explicit
     `"grading": null` -> new row NULL, existing row's grading CLEARED to SQL NULL (assigned as Python None,
     which `none_as_null` stores as SQL NULL). Still idempotent (same request, same state). Needed because Step 6 decides "starred" from local
     `ids` only, which can diverge from the server (cleared storage, second device), so a click can POST
     for a row that already exists with NULL or stale grading (round 2 S1).
   - The finite-number check is ONE helper, `is_finite_rule_value(val) -> bool` in
     `app/scoring/contract_validator.py` (not bool, int/float, `math.isfinite`, OverflowError -> False),
     used by `_parse_contract_rules`, the POST validator, and scan.py's recording check (`scan.py:1719-1725`,
     today a third copy), so the three cannot drift (a POST 422 would silently degrade the star to YAML
     grading).
   - `GET /api/watched-contracts` keeps returning `list[str]` (no change to its shape).
   - `GET /api/contracts` gains two optional parameters, both absent = today's behaviour exactly:
     - `expiry: str | None` (an empty `expiry=` is treated as absent; `api.ts` sends it only when truthy),
       forwarded as the keyword `expiry=` to `fetch_option_chain_async` only when given
       (absent -> the call is made exactly as today, without an `expiry` kwarg). When given, the response
       keeps only rows whose `expiry` equals it (the fetch falls back to the window/default expiry when the
       date is not listed, e.g. expired; those rows are not the star's).
     - `strikes: str | None`, a comma-separated list of integer strikes (422 if any item is not an int;
       with `strikes` given, the router returns EVERY filtered row — no `results[:limit]` at the end either;
       items are stripped of spaces and empty items dropped, so `187,` and `187, 190` parse; a list that is
       empty after that, including `strikes=`, is treated as absent).
       When given, rows are filtered to those strikes AFTER scoring, and neither `max_price` nor `limit`
       is applied: the caller asked for specific contracts, so nothing may cut them (round 2 B1: SPY/TSLA
       list >100 strikes per expiry, and a hard-rejected star ties at 0 and was cut in strike order).
     Grading is unchanged by either: the same hold-widened overrides apply, so the score equals what the
     call without them gives for that contract when it lands on the same expiry (pinned by test 6c).
     - When `expiry` is given, the chain fetch is called with `expiry=E` and `dte_bounds=None` (and no
       `min_dte_floor`), so a listed E is fetched and an unlisted E (expired/delisted) falls back to the
       plain first-expiry->=21-days chain, which is then filtered to `[]` (200) -> `not_listed`. The
       hold-day DTE bounds are still computed and still widen the GRADING overrides exactly as today; only
       the fetch's expiry choice ignores them.
     - When `expiry` is given and the raw chain comes back empty, respond 503 with detail starting
       "Option chain unavailable for <symbol> <expiry>". The check sits immediately after the chain fetch,
       before the existing no-price check. Causes: a Tradier outage/timeout (swallowed into `[]`), an
       expirations list with no expiry >= 21 days, or a listed E with zero quoted strikes (accepted: that
       case shows "Could not load the chain — retry" though the chain technically loaded). Absent `expiry`
       = unchanged (empty chain -> 200 `[]`).
   - New `GET /api/watched-contracts/detail` returns `list[{contract_id, grading | null}]` in `created_at`
     order. A stored grading that no longer validates (hand-edited DB) is served as `null`, never a 500.

### 2.3 Frontend

1. `types/domain.ts`: export `ContractGrading`.
2. `lib/api.ts`: `addWatchedContract(id, grading?: ContractGrading | null)` puts `grading` in the body
   whenever it is `!== undefined` (so an explicit `null` is sent as `"grading": null`, absent = no key);
   `getWatchedContractsDetail()`; `getContracts` ctx gains `expiry?: string` (sent URL-encoded as
   `&expiry=`) and `strikes?: number[]` (sent as `&strikes=` + `encodeURIComponent(strikes.join(','))`,
   i.e. `strikes=187%2C190`; omitted when empty).
3. `watchedContractsStore`: new persisted `grading: Record<string, ContractGrading>`. `version` 2 -> 3;
   `migrate` v<3 sets `grading: {}` and keeps `ids` (the two existing identity-passthrough migrate tests
   are rewritten accordingly). `add(id, grading?)` records grading when given, INCLUDING when the id is
   already present (today it returns early, which would drop a rollback's grading);
   `remove` drops the id's grading; new `clearGrading(id)` drops only the grading. `toggle` is unused in the app (grep) and is REMOVED, so it cannot
   become a grading-less star path. `syncFromBackend` reads `/detail` and replaces `ids` and `grading`
   together, through `api.getWatchedContractsDetail()` (not raw `fetch`, so tests mock one module). If
   `/detail` fails, it falls back to `api.getWatchedContracts()` (`api.ts:589`, today's
   `GET /api/watched-contracts`, replacing the store's raw `fetch`) for ids and keeps the local
   grading for ids that are still present. If both fail, state is kept (no `set`), as today's `catch {}`.
   A `/detail` row with `grading: null` is omitted from the `grading` map (no null-valued keys). It calls `set` only when ids or grading differ structurally,
   so a no-op sync does not refire the Watchlist fetch. `partialize` persists both fields.
4. `ContractStar`: optional `grading?: ContractGrading` prop, passed to `add` and `api.addWatchedContract`.
   Unstar captures `prev = grading[id]` before `remove`, and a failed DELETE rolls back with
   `add(id, prev)`, so the grading survives (the id returns at the END of `ids`, so its missing-row
   position may change; accepted). POST failure: on a 422 with grading, retry once WITHOUT
   grading (the star then exists, honestly marked YAML-graded) and `console.warn`; any other failure rolls
   back with `remove`, as today. The 422 retry is `addWatchedContract(id, null)` (explicit null = clear any
   stale server grading) together with store `clearGrading(id)` (drops `grading[id]` locally); if the retry
   also fails, `remove(id)`. The status comes from `api.ts`'s thrown message (`API <path> → <status>: …`,
   no status field): `lib/directOrder.ts`'s private `parseApiError` is moved to `lib/apiError.ts` and
   exported with `statusOf(e): number | null`; `directOrder.ts` imports it back (behaviour unchanged).
5. Step 6: `loadContracts` builds each symbol's `ContractGrading` (contract_rules `?? null`, sanitized
   hold or nulls, `stockScoreBySymbol[symbol] ?? 70`), derives that symbol's `getContracts` ctx FROM it
   through one pure helper `gradingToCtx(g)` in `lib/contractGrading.ts` (null contract_rules / null hold
   -> the field OMITTED, i.e. `undefined`, exactly what Step 6 sends today, so the two existing
   `toBeUndefined()` tests stay green; `{}` is passed THROUGH as `{}`, as Step 6 sends it today and
   `contractRules.test.tsx:55-61` expects — `api.ts:420` drops an empty object from the URL),
   and keeps the gradings in local state `gradingBySymbol` set together with the fetched rows. The row's
   `<ContractStar grading={gradingBySymbol[symbol]}>` therefore stars with exactly the inputs that graded
   the row on screen, even if `scanResult` is replaced while Step 6 is mounted (round 2 N4).
6. Watchlist `refreshContracts`:
   - Each id is parsed up front by `parseContractId(id)` in `lib/contractGrading.ts`: exactly 4 `|` parts,
     a non-empty upper-case symbol (`/^[A-Z][A-Z0-9.\-]*$/`), right `C`/`P`, ISO `YYYY-MM-DD` expiry,
     a strike matching `/^\d+(\.\d+)?$/` (so `187abc` fails; `parseFloat` alone would accept it) (the expiry
     is checked by regex only; an impossible date like `2026-02-30` passes and
     lands as `not_listed`, accepted). An id that fails becomes an `invalid` row and is never sent, so one bad id cannot 422 its siblings' group. The strike sent
     is `Math.trunc(parseFloat(strike))`, matching market.py's `int()`, de-duplicated per group; matching a
     result row uses the same trunc rule (replacing today's `Math.round` fallback) plus today's exact-id
     match first.
   - An id whose expiry is before today (local date) is a `missing` row with `reason: 'expired'` without
     any fetch.
   - Group the rest by `(symbol, right, expiry, gradingKey)`, where `gradingKey` is a stable stringify of
     `gradingToCtx(grading)` with `stock_score` null normalised to 70 (so `{}`/`null` rules and
     `null`/`70` score, which send equivalent requests, share a key; empty `contract_rules` dropped from
     the key); a grading that yields the same request as none (all null, or only `stock_score` 70) gets
     '', the no-grading key.
   - In the `/detail`-failure fallback the local grading is re-checked client-side (`isValidGrading`: finite
     numbers, hold both-or-neither with max >= min, stock_score int 0-100); an invalid entry is treated as
     no grading, and so shows the YAML marker. One `getContracts` per group, with ctx `{ expiry, strikes: [the group's starred
     strikes], ...gradingToCtx(<the first member's grading, in watchedIds order>) }` (an empty `contract_rules` is dropped from the URL by `api.ts`). A group
     with no grading sends `{ expiry, strikes }`. `strikes` disables `limit` and `max_price` server-side.
   - `refreshContracts`' `useCallback` depends on `[watchedIds, grading]`, so a grading change refetches.
   - Kept results: a list of settled group results `{ groupKey, strikes: Set<number>, outcome: rows |
     'rejected' }`, where `groupKey` is (symbol, right, expiry, gradingKey). Nothing is discarded when a
     refresh STARTS: the last settled set stays on screen while a refresh is in flight (today's behaviour,
     `page.tsx:113-116` replaces `contracts` only on success). When a non-aborted refresh settles, its
     results REPLACE the kept list atomically (an aborted refresh changes nothing). The zero-ids and
     zero-groups paths clear the list.
   - Matching an id: among kept results with the id's `groupKey` whose `strikes` CONTAINS the id's
     (trunc) strike — a superset request counts, so unstarring a sibling does not blank a row — use that
     result (at most one exists per groupKey, since a settled refresh replaces the whole list; "first" is
     defensive); `rejected` -> `fetch_failed`; rows -> today's exact-id match then the trunc fallback (a fallback-matched live row carries
     `{ ...contract, id: storedId }`, as today at `page.tsx:195-196`, so `ContractStar.isWatched` is true
     and a click unstars rather than adds), else `not_listed`. Ids are de-duplicated first, as today's
     `seen` set (`page.tsx:179-184`), so a duplicated local id cannot collide on a React key. No such kept result (first mount, a newly starred expiry/grading, a strike newly joining
     a group before a request carrying it settles) -> `missing` with `reason: 'loading'`. A row is thus
     never graded from a request that lacked its strike, and never flashes Loading on Refresh or unstar. With the `strikes` filter two groups rarely
     return the same row, so this is defensive, and it covers residual 6's shared 187/187.5 id.
   - Rows become a discriminated union (round 2 S2), exported from the page module for tests:
     `type WatchedContractRow = { kind: 'live'; contract: OptionContract }
       | { kind: 'missing'; id; symbol; strike; expiry; right; reason: 'loading' | 'expired' | 'not_listed' | 'fetch_failed' }
       | { kind: 'invalid'; id }` — an unreadable id renders its raw id as the label (no `contractLabel`).
     The page exports only the TYPE (erased; Next's page-export check is unaffected); every runtime helper
     (parse, classify, sort comparator, gradingToCtx) lives in `lib/contractGrading.ts`.
     - `reason`: `expired` as above (no fetch); `fetch_failed` when the group's `allSettled` entry rejected
       (network, 422, the no-price 503, or the new empty-chain 503); `not_listed` for a fulfilled group
       without the id (the chain loaded but has no quoted row for that strike — e.g. no bid/ask/last outside
       hours; also, accepted, an expiry equal to today already delisted after the close).
     - Notes: loading -> "Loading…"; expired -> "Expired"; not_listed -> "Not in the current chain"; fetch_failed -> "Could
       not load the chain — retry"; invalid -> "Unreadable contract id".
     - Status: `loading` rows use `PENDING` (the domain Status for in-flight); other missing/invalid rows
       use `NO_DATA`.
     - Expired is classified inside `refreshContracts` (a page left open past midnight reclassifies on the
       next refresh; accepted).
     - The YAML marker (2.3.7) is shown on live rows only; a missing/invalid row's tooltip is its note.
     - `invalid` rows render exactly like `missing` rows (star with working unstar, status `NO_DATA`, dash
       cells, sort last, counted in tab and header) except the label is the raw id and the symbol cell is
       "—". The star is what lets
       the user delete a junk id the server keeps re-supplying.
     - Missing rows render the label (`contractLabel` from the id parts), status `PENDING` for
       `reason: 'loading'`, else `NO_DATA`, dashes in every
       market cell, no `DTEProgressBar`, a plain-text tooltip with the note, and the star (unstar works).
     - Sort: missing and invalid rows always last, in both directions and for every sort key, ordered
       among themselves by their position in `watchedIds` (stable across renders); live rows sort as today.
     - `ivColumnLabel(ivBasesOf(...))` receives live contracts only.
     - Offline: the page's single `offline` flag is today shared by both tabs (`page.tsx:62`, set by
       `refreshWatchlist` and `refreshContracts`), so a contracts success hides a stocks failure and vice
       versa. The contracts tab gets its own `contractsOffline` state; `offline` stays the Stocks tab's.
       `contractsOffline` is true only when at least one group was fetched and every fetched group rejected;
       with zero groups (all stars expired/invalid) it is false. The abort of the previous in-flight fetch
       (`contractsAbortRef.current?.abort()`, today at `page.tsx:102`) moves ABOVE the zero-ids early return
       (`:100`), and that return also sets `contractsOffline` false and `refreshingContracts` false, so a
       slow fetch rejecting after the last unstar is discarded as aborted and cannot raise the banner. The
       same applies to the zero-groups path (all expired/invalid): abort first, then no fetch, and set
       `contractsOffline` false, `refreshingContracts` false and clear the kept per-group results (the
       aborted run's `finally` skips `setRefreshingContracts(false)`, `page.tsx:124`, so without this the
       Refresh button could stay on "Refreshing…"). Banner text:
       a contracts-only failure (`contractsOffline` and not `offline`) says "Could not load option chains —
       retry" instead of "Backend not running"; `offline` keeps today's text. CHANGE from today, where `Promise.all` set
       it on any failure: partial failures show per-row `fetch_failed` instead. The banner shows when
       either flag is set, with the text chosen above; the contracts-only text shows only while the
       Contracts tab is active (the banner sits in the shared header, `page.tsx:273-275`).
     - The tab count and header count include missing rows (every star is a row).
7. Watchlist Contracts tab: a row whose grading is absent or has `contract_rules === null` shows a dim
   caution marker: a visible dim `<Text size={10} tone="caution">` element under the contract label whose
   text is "Graded on contract_rules.yaml — starred before the scan's rules were saved (or the scan
   recorded none)". Test 10c queries it with `getByText`. A row with recorded rules shows no marker. The tab
   header shows no global note.

### 2.4 Behaviour changes (stated)

- A contract starred in Step 6 from now on is graded in the Watchlist with the same inputs Step 6 used,
  so it shows what Step 6 would show for that contract if it fetched that expiry with the star's inputs
  (same market data, same YAML). Starred contracts no longer vanish from the tab: each is listed live, or
  as Expired / Not in the current chain / Could not load the chain / Unreadable contract id.
- Old stars (and stars whose scan recorded no rules) still grade on the YAML, now marked as such. A
  grading-less star whose DTE is above the YAML's `max_dte` (90) now shows REJECT `dte_too_long` (before,
  the default >=21-day fetch never returned its expiry, so it vanished).
- Intended, stated (round 4 S4): a star's saved hold days set its DTE floor (`widened_min_dte(lo,
  hold_max) = max(lo-10, hold_max+1)`) and preferred band, while its DTE falls every day. So a star turns
  REJECT `dte_too_short` once its DTE drops below the floor (and loses DTE-fit points on the way), long
  before expiry. Example: Quarterly preset (hold 45-60 d), multiplier 2.0 -> window 90-120, floor 80; a
  contract starred at 90 DTE is REJECT 11 days later (at DTE 79; at DTE 80 it is not hard-rejected,
  though its DTE sub-score is already 0). That is what the scan and Step 6 would say about that contract for
  that holding plan today (it no longer leaves room for the hold), so it is the honest answer; the YAML-only
  path's fixed 21-day floor hid it. Pinned by test 6f.
- The Watchlist asks for the star's own expiry and strikes only, with no limit or price cap. One chain
  request per (symbol, right, expiry, grading) group instead of per (symbol, right): more requests when a
  user stars several expiries of one name. The response is smaller (only the starred strikes).
- `stock_score` is a snapshot from star time. The Watchlist does not re-score the stock. That matches "grade
  as the scan did".

### 2.5 Residuals (logged, not fixed)

1. A contract starred on a device whose POST failed is rolled back, as today. No retry queue.
2. Stars made before this ships (backend row NULL; local v2 data migrates to `grading: {}`) stay
   grading-less, marked as YAML-graded, until unstarred and re-starred from Step 6.
3a. The Watchlist's mount-time `syncFromBackend` can overwrite `ids`/`grading` before a just-clicked
   Step-6 POST commits, dropping the star and its grading locally until the next sync. Pre-existing for
   ids; now it reaches grading too.
3. DELETE and POST are fired without awaiting each other; a fast unstar/re-star can reach the server out of
   order, leaving no row or the old grading. Pre-existing for ids; now it can also carry a stale grading.
4. Stored rules are a delta on the YAML in force at viewing time, as everywhere else; an edit to
   `contract_rules.yaml` (or the DTE multiplier/tolerance) after starring changes the Watchlist grade, with
   no marker. A full config snapshot was rejected as out of proportion.
5. Step 6's own `max_price`/`limit` cut (STEP6 deferred item 3) is unchanged.
6. Pre-existing: `market.py` truncates strikes with `int()` and the id is built from it, so 187 and 187.5
   share an id; a starred `…|187|…` can resolve to either. Not introduced here; logged.
7. Residual 3's stale-grading half is mostly closed by the POST overwrite; the no-row half remains.

## 3. Tests (each with the mutation it must kill)

Backend `tests/test_watched_contracts_grading.py` — no watched-contracts router test exists today. It
builds a minimal `FastAPI()` with only the `watched_contracts` router (not `app.main:app`, whose lifespan
starts schedulers), its own in-memory aiosqlite engine (StaticPool) with `WatchedContractModel.__table__
.create`, and `test_app.dependency_overrides[get_db]` — the shape of `tests/conftest.py`'s `client`
fixture (`:387-470`). Contracts-endpoint tests (6b-6g) extend `tests/test_step6_contract_rules.py`'s
harness, which already stubs the chain and `fetch_price_async`; every 6b-6g case stubs the price at 185.0,
so the existing no-price 503 can never stand in for the new one:
1. POST with grading -> `/detail` returns it verbatim. *Kills: not storing grading.*
2. POST without grading -> `/detail` grading null; `GET /api/watched-contracts` still `list[str]`. *Kills:
   breaking the old shape.*
3. POST twice, second with a different grading -> the second replaces it; a third POST without the field
   leaves it; a fourth with explicit `"grading": null` clears it (`/detail` null). *Kills keep-first,
   wipe-on-absent, and ignore-explicit-null.*
3b. POST with an unknown rule key -> 201 and the key is not stored.
4. 422 on: non-finite/bool rule value, hold max < min, only one hold bound, stock_score 101. *Kills a missing
   validator.*
4b. Numeric-string rule value (`"5"`), bool (`true`) and a huge int (a 400-digit integer literal in the
   raw JSON body, which Python parses as an int that overflows float) -> 422, not 500. *Kills lax pydantic coercion and the OverflowError path.*
5. Hand-written invalid grading in the row -> `/detail` serves null, 200. *Kills a 500 on bad rows.*
5b. The explicit-null clear path (which assigns Python None) leaves SQL NULL: a raw `grading IS NULL`
   query finds the row. *Kills JSON-null storage (`none_as_null` missing).*
6. Migration: `down_revision == 'f3d5c81b0a47'`, and applying `upgrade()` via
   `Operations.context(MigrationContext.configure(conn))` (the `tests/test_journal.py:384-423` pattern) on a
   sqlite DB where the OLD `watched_contracts` table was created by raw DDL (not from the current model,
   which already has `grading`) adds `grading`; `downgrade()` removes it.
   *Kills a migration that does not add the column.*
6b. `tests/test_contracts_expiry.py` (or added to `test_step6_contract_rules.py`): `expiry` reaches
   `fetch_option_chain_async`; rows of another expiry are filtered out; absent `expiry` = unchanged call.
   *Kills not forwarding / not filtering.*
6c. Parity: stubbed chain (fewer than 10 rows, all priced under $50, so the call without `strikes` is not
   cut by `limit`/`max_price`) where E is the window's expiry; hold days (20, 25) as the existing test at
   `test_step6_contract_rules.py:176` (so the widened band 30-60 differs from the YAML's 21-60 for a 45-DTE
   stub); the same rules/stock_score called once without `expiry`/`strikes` and once with
   `expiry=E&strikes=<all>` -> identical `score` and `contractConfidence` per id. Variant with
   `_THIN_NO_IV`-style rows (no vendor IV) and `strikes=` one NON-ATM strike -> that row's `iv` and `score`
   equal the no-strikes call's. *Main case kills e.g. skipping `widen_contract_overrides_for_dte` on the
   new path; the variant kills filtering strikes before the ATM Black-Scholes inversion.*
6d. `strikes`: a 150-row chain where every row scores the same and the starred strike is last in strike
   order, priced above `max_price` -> returned; and `strikes=` the LAST 12 strikes in strike order (all
   tied, some above `max_price`) -> all 12 returned (kills a `results[:limit]` left after the filter, which
   the single-strike case cannot see). Non-int item -> 422; `strikes=` -> same as absent; `expiry=` -> same
   as absent.
   *Kills `limit`/`max_price` still applying.*
6f. DTE decay, through the endpoint: `monkeypatch.setattr("app.routers.contracts.dte_holding_multiplier",
   lambda: 2.0)` (the router imports it by name and passes it uncalled; patching the float or the
   validator's name does nothing); the stub's `expiry` is `date.today() + timedelta(days=79)` (resp. 95) and
   the query's `expiry=E` equals it — the validator derives DTE from `expiry`, not the stub's `dte` field; stub one contract that
   passes every other check (liquidity, spread, delta, IV) and the price; call
   `/api/contracts?expiry=E&hold_min_days=45&hold_max_days=60&strikes=K`. At DTE 79: `contractConfidence ==
   'REJECT'` and `breakdown.dteDetail.preferred_min == 80`. At DTE 95, all else identical:
   `contractConfidence != 'REJECT'`. *Pins 2.4's stated behaviour on the new path.*
6g. `expiry` given + empty raw chain -> 503 whose `detail` starts with "Option chain unavailable";
   `expiry` given + a chain of another expiry -> 200 `[]`; `expiry` given WITH `hold_min_days=45&
   hold_max_days=60` (so main would compute non-None bounds) -> the fetch's kwargs have
   `dte_bounds is None` and `min_dte_floor` absent or None, while the response still shows
   `breakdown.dteDetail.preferred_min == 80` (grading widened; multiplier patched as in 6f); unlisted `expiry` whose fallback chain is also empty -> 503 (documented cause); no `expiry` + empty
   chain -> 200 `[]` (unchanged). `strikes=187,` and `187, 190`
   parse.
6e. scan.py's recording check goes through `is_finite_rule_value` (existing scan contract-rules tests
   stay green; one added for a huge int recorded as None, as today).

Frontend:
7. `watchedContractsStore.test.ts`: migrate v2 -> v3 adds `grading: {}` and keeps ids; `add(id, g)` stores
   g; `remove` drops it; `syncFromBackend` replaces both from `/detail`, and on `/detail` failure falls back
   to ids and keeps the surviving local grading — including after `persist.rehydrate()` from v3 storage
   (the store has `skipHydration`); `toggle` no longer exists; `add` on an existing id updates grading;
   a structurally identical sync does not call `set`.
8. `components/atoms/ContractStar/__tests__/ContractStar.test.tsx` (new; none exists): click with grading -> `api.addWatchedContract(id, grading)` and the store holds it;
   unstar whose DELETE rejects -> the id AND its grading are restored (*kills a grading-less rollback*);
   POST rejecting `new Error('API /api/watched-contracts → 422: …')` -> retried with `null`, the id stays,
   `grading[id]` is gone; retry also rejecting -> removed; POST rejecting 500 -> removed.
8c. `lib/__tests__/api.test.ts` (existing file, its `global.fetch` convention): `addWatchedContract(id,
   null)` body has `"grading":null`; omitted -> no `grading` key; `getContracts` with
   `{expiry:'2026-12-18', strikes:[187,190]}` -> URL has `expiry=2026-12-18` and `strikes=187%2C190`
   (pinned exactly to what the helper emits); `strikes: []` -> no `strikes` param.
   *Kills dropping strikes/null on the wire, which would silently restore limit/max_price.*
8b. `lib/__tests__/apiError.test.ts`: `statusOf` on the api message shapes; existing directOrder tests stay
   green. `lib/__tests__/contractGrading.test.ts`: `parseContractId` (valid, 3 parts, bad strike incl.
   `187abc`, bad expiry, lowercase symbol, `187.0` -> trunc 187), `gradingToCtx` null mapping, gradingKey normalisation, the comparator
   (missing last both directions; two missing rows in `watchedIds` order [B, A] stay [B, A] under score and
   price, both directions).
9. Step 6 page test (extends `contractRules.test.tsx`; its `api` mock gains
   `addWatchedContract: jest.fn().mockResolvedValue({ contract_id: '…' })` — ContractStar calls `.catch` on
   it):
   clicking the row star stores grading equal to the ctx `getContracts` was called with (contract_rules,
   hold, stock_score); after replacing `scanResult` with `{...scanResult, contract_rules: X}` (same
   `candidates` reference, so the load effect keyed on `rawCandidates` does not refetch), the star still
   carries the fetch-time grading. *Kills drift between the two.*
10. Watchlist page test (extends `__tests__/page.test.tsx`; its `api` mock gains
    `getWatchedContractsDetail` resolving to the ids/grading the test set, `getWatchedContracts` for the
    fallback, and `removeWatchedContract: jest.fn().mockResolvedValue(undefined)` for 10f; `beforeEach` resets `{ ids: [], grading: {} }`):
    a. A starred id with grading -> `getContracts` is called with that ctx (expiry, contract_rules, hold
       days, stock_score, strikes). *Kills the defect marker staying.*
    b. Two stars on the same symbol/right with different gradings -> two calls; each row shows its own
       group's score even when both groups return the same contract id. *Kills flat matching.*
    c. A star with no grading -> called with `{ expiry, strikes }` and no
       contract_rules, and the YAML marker is shown (`getByText('Graded on contract_rules.yaml', {exact:
       false})`); a star with rules shows no marker. A legacy `AAPL|187.0|<expiry>|C` star matched by the
       trunc fallback renders starred (`aria-pressed="true"`) and clicking it calls `removeWatchedContract`.
    d. Two stars, same symbol/right/grading, different expiries -> two calls, both rows shown.
    e. Missing rows: before the group's `getContracts` mock resolves, the row shows "Loading…" and NOT
       "Not in the current chain"; after it resolves without the id -> "Not in the current chain";
       starring a second strike into an existing group (via
       `act(() => useWatchedContractsStore.getState().add(id2, g))`; the page has no add control) shows that row "Loading…" until a request carrying
       its strike resolves, while the FIRST row keeps showing its score (not Loading) with the new request
       held pending; likewise clicking Refresh with the mock held pending keeps every live row's score;
       unstarring one of two strikes in a group, with the NEXT `getContracts` set to
       `mockReturnValueOnce(new Promise(() => {}))` (never settles), keeps the other row's score shown and
       no "Loading…" (superset match; an exact-strike-set match would blank it); a group whose first request
       rejected shows "Could not load the chain — retry", and after clicking Refresh with the next call held
       pending it STILL shows that, not "Loading…"; the loading row has `data-status="PENDING"` and a
       not-listed row `data-status="NO_DATA"` (TableRow publishes `data-status`); an aborted refresh R1
       held pending, superseded by R2 (unstar a sibling) which resolves, then R1 resolving late with a
       different score -> R2's score stays; a past expiry ->
       "Expired"; a rejected group -> "Could not load the chain — retry" while another group's rows stay
       visible; dash cells; missing rows sort last under score, price and dte in both directions; a past
       expiry makes no `getContracts` call.
    f. A malformed id (`AAPL|abc|<expiry>|C`) next to a valid star on the same symbol/right/expiry ->
       an invalid row labelled with the raw id and "Unreadable contract id", the valid row live, `strikes`
       holds only the valid strike; clicking the invalid row's star calls
       `api.removeWatchedContract(rawId)`.
    g. Every star expired or invalid -> no `getContracts` call and no offline banner. One group rejecting
       -> rows show `fetch_failed`, no banner; all groups rejecting -> banner (contracts-only text); a slow group fetch that rejects
       AFTER `ids` is cleared to `[]` -> no banner; unstarring the last valid star while one expired star
       remains (zero-groups path) -> the button reads "Refresh" (not "Refreshing…") and no banner; a contracts success does not
       clear a stocks failure.
    Clock: every Watchlist and `contractGrading` test with a dated id pins the clock
    (`jest.useFakeTimers().setSystemTime(new Date('2026-10-01T15:00:00'))`) or builds expiries relative to
    `Date.now()`, so no test starts failing when a literal date passes.

Gates: `npm run typecheck`, Jest full, backend pytest full, `python3 scripts/state.py` exit 0.
Deploy note (in the merge record): run `alembic upgrade head` (dev `sqlite+aiosqlite:///./dev.db` and prod)
before starting the new backend; `create_all` does not add the column, and until the migration runs every
`/api/watched-contracts` call (old and new) 500s because the model selects `grading`.
PROJECT_STATE: the phase verify becomes a presence probe for the grouped call (the defect marker is gone).
